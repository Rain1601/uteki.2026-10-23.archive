# 六个业务工具的确定性实现：读取冻结资产、返回来源证据，或在授权范围内建设资产。
# 每次 ToolExecution 只承载一个操作；会话接受、最终响应登记及幂等确认由 DataService 统一处理。
"""Business tool implementations over the existing catalog and frozen HTML."""
from __future__ import annotations

from copy import deepcopy

from ..contracts.assets import AssetRef
from ..contracts.common import CatalogError, canonical, digest
from ..contracts.query import parse
from ..retrieval.assets import candidates, check_scope
from ..retrieval.content import HtmlReader
from ..retrieval.cursors import position, advance
from ..retrieval.index import DerivedIndex, concept_id, sql_connection
from .evidence import result_item, source_evidence, fit_page


# 单次工具执行上下文，缓存读者和元数据，并累计副作用、资源使用及阶段检查。
class ToolExecution:
    # 绑定目录、会话和已解析请求；取消、检查点、时限与获取能力由宿主注入。
    def __init__(self,catalog,session,tool,request,*,should_cancel=None,checkpoint=None,acquisition_adapter=None,limit=None):
        self.catalog,self.session,self.tool,self.request = catalog,session,tool,request
        self.should_cancel = should_cancel or (lambda:False)
        self.checkpoint = checkpoint or (lambda phase:None)
        self.readers = {}
        self.metas = {}
        self.context = session.data['context']
        self.acquisition_adapter = acquisition_adapter
        self.resource_usage = dict(external_calls=0,model_calls=0,cost_usd='0')
        self.limit = limit
        self.effects = []

    # 副作用完成或状态变化后立即保存回执及耗时下界，供中断恢复核验。
    def effect(self, **value):
        self.effects.append(value)
        operation = self.session.data['operations'][self.operation]
        operation['effects'] = deepcopy(self.effects)
        operation['resource_usage'] = deepcopy(self.resource_usage)
        operation['elapsed_lower_bound'] = self.limit.elapsed() if self.limit else 0
        self.session.save()

    # 切换派生索引前先保存目标和预期响应，防止文件已发布但业务回执丢失。
    def prepare_index(self, intent):
        operation = self.session.data['operations'][self.operation]
        operation['effect_intent'] = dict(kind='index_head',target=intent,
            response=self.process_response(intent['generation']))
        operation['elapsed_lower_bound'] = self.limit.elapsed() if self.limit else 0
        self.session.save()

    # 逐阶段保存原获取意图、进度和资源消耗；无法确认落盘时立即要求恢复。
    def prepare_acquisition(self, **target):
        operation = self.session.data['operations'][self.operation]
        intent = operation.setdefault('effect_intent',dict(kind='official_acquisition',target={}))
        if intent['kind'] != 'official_acquisition':
            raise CatalogError('RECOVERY_REQUIRED','operation already owns a different effect intent')
        intent['target'].update(deepcopy(target))
        operation.setdefault('acquisition_progress',[]).append(deepcopy(target))
        operation['resource_usage'] = deepcopy(self.resource_usage)
        operation['elapsed_lower_bound'] = self.limit.elapsed() if self.limit else 0
        try:
            self.session.save()
        except (OSError,ValueError) as error:
            raise CatalogError('RECOVERY_REQUIRED','acquisition intent could not be durably acknowledged') from error

    # 为已完成的索引代次组装建设响应；返回的是原资产引用及新的派生代次。
    def process_response(self, generation):
        return self.response([dict(update_id=self.operation,status='completed',policy_decision=dict(allowed=True,denied_reason=None),
            new_asset_refs=[self.request.process.asset_ref.model_dump(mode='json')],derived_generation=generation,gaps=[],
            resource_usage=dict(model_calls=0,external_calls=0,cost_usd='0'))])

    # 在阶段边界检查时限与取消；检查点本身也可能阻塞，因此执行后再检查时限。
    def check(self,phase):
        if self.limit is not None:
            self.limit.check(phase)
        if self.should_cancel():
            raise CatalogError('CANCELLED','cancelled at '+phase)
        self.checkpoint(phase)
        # The checkpoint itself may block or signal cancellation.
        if self.limit is not None:
            self.limit.check(phase)

    # 先校验资产版本及读取范围，再缓存 HtmlReader；缓存键包含完整 AssetRef。
    def reader(self,reference):
        self.check('before_read')
        reference = parse(AssetRef,reference)
        key = canonical(reference.model_dump(mode='json'))
        if key not in self.readers:
            self.metas[key] = check_scope(self.catalog,self.context,reference)
            self.readers[key] = HtmlReader(self.catalog,reference)
        self.check('after_read')
        return self.readers[key]

    # 为当前已校验的资产读者创建派生索引访问器，沿用同一执行时限。
    def index(self,reference):
        return DerivedIndex(self.catalog,self.reader(reference),limit=self.limit)

    # 调用方指定证券时，发现必须显式按该证券过滤；公司 ID 或预先准入不能替代符号查找。
    def require_security_filter(self):
        self.required_securities = {(s['ticker'],s['exchange_mic'])
            for s in self.context['request'].get('required_securities',[])}
        if self.tool == 'find_assets' and self.required_securities:
            supplied = {(s.ticker,s.exchange_mic) for s in self.request.filters.securities} if self.request.filters else set()
            if supplied != self.required_securities:
                raise CatalogError('SECURITY_FILTER_REQUIRED',
                    'find_assets must explicitly use context.request.required_securities in filters.securities; company_ids do not replace the requested security lookup')

    # 读取的资产必须来自本次运行中按所需证券完成的发现结果，不接受猜测或仅准入的引用。
    def require_discovered(self, reference):
        if not self.required_securities:
            return
        wanted = reference.model_dump(mode='json')
        for operation in self.session.data['operations'].values():
            if operation['tool'] != 'find_assets' or operation['status'] != 'completed':
                continue
            for item in operation['response']['items']:
                if item.get('asset_ref') == wanted and any((m['ticker'],m['exchange_mic']) in self.required_securities
                        for m in item.get('metadata',{}).get('symbol_matches',[])):
                    return
        raise CatalogError('ASSET_DISCOVERY_REQUIRED',
            'first call find_assets with the caller required_securities, then use its returned asset_ref; admission alone does not establish the requested symbol binding')

    # 列出本次请求将读取的全部资产，包括计算操作数和建设目标。
    def requested_assets(self):
        request = self.request
        if self.tool == 'find_assets' or (self.tool == 'request_asset_update' and request.action != 'process'):
            return []
        refs = [request.process.asset_ref if self.tool == 'request_asset_update' else request.asset_ref]
        if self.tool == 'query_records':
            refs += [operand.asset_ref for calculation in request.calculations for operand in calculation.operands]
        return refs

    # 在接受操作前验证范围、能力和筛选语法；本步骤失败不提交会话计划。
    def preflight(self):
        request = self.request
        self.require_security_filter()
        for reference in self.requested_assets():
            self.require_discovered(reference)
        if self.tool == 'find_assets':
            self.found = candidates(self.catalog,self.context,request,limit=self.limit)
        elif self.tool == 'request_asset_update':
            if request.action == 'process':
                self.reader(request.process.asset_ref)
            elif request.acquire.company_id not in self.context['company_ids']:
                raise CatalogError('SCOPE_DENIED','acquisition would widen entity scope')
        else:
            self.reader(request.asset_ref)
            if self.tool=='search_asset' and request.mode!='text' and any(request.scope.model_dump(mode='json').values()):
                raise CatalogError('CAPABILITY_UNSUPPORTED','block/origin scope is supported only for text search')
            if self.tool=='search_asset' and request.mode!='text' and set(request.include)!={'snippet'}:
                raise CatalogError('CAPABILITY_UNSUPPORTED','additional source context is supported in text search; use read_evidence for concept targets')
            if self.tool == 'query_records':
                for calculation in request.calculations:
                    for operand in calculation.operands:
                        self.reader(operand.asset_ref)
                self._validate_filters(request.filters)
                request.select.validate_fields()
            if self.tool == 'search_asset' and request.mode == 'text' and request.text.match == 'regex':
                with sql_connection(':memory:',readonly=False,limit=self.limit) as db:
                    try:
                        db.execute('SELECT regexp_matches(?,?)',['',request.text.value]).fetchone()
                    except Exception as error:
                        if self.limit is not None:
                            self.limit.check('regex_preflight')
                        raise CatalogError('INVALID_REQUEST','invalid or unsupported RE2 expression') from error

    # 拒绝尚未具备证据的合并/分部口径推断；有维度不等于已确定实体范围。
    def _validate_filters(self,filters):
        if filters.entity_scope:
            raise CatalogError('CAPABILITY_UNSUPPORTED','dimension presence alone does not prove consolidated or segment scope; use explicit dimensions')

    # 绑定已接受的操作 ID，再分派到已由服务入口校验过的工具名。
    def execute(self,operation_id):
        self.operation = operation_id
        self.check('tool_started')
        return getattr(self,self.tool)()

    # 生成共同响应信封；存在问题或截断时明确返回 partial。
    def response(self,items,*,cursor=None,issues=(),truncated=False,coverage=None,**extras):
        return dict(operation_id=self.operation,status='partial' if issues or truncated else 'ok',items=items,
            next_cursor=cursor,truncated=truncated,coverage=coverage or {'status':'complete'},
            issues=list(issues),error=None,**extras)

    # 按冻结版本和游标选择完整条目；单条过大时保留位置并显式报告。
    def page(self,items,version,*,limit=None,max_bytes=180000):
        offset = position(self.session,self.tool,self.request,version)
        if offset > len(items):
            raise CatalogError('CURSOR_EXPIRED','cursor is outside this view')
        selected,end,truncated = fit_page(items,offset,limit=limit or self.request.limit,max_bytes=max_bytes)
        issues = []
        if end == offset and offset < len(items):
            issues.append(dict(code='ITEM_TOO_LARGE',message='one item exceeds output budget; increase max_bytes or narrow the target'))
        cursor = advance(self.session,self.tool,self.request,version,end) if end<len(items) else None
        return selected,cursor,truncated,issues

    # 组合冻结内容能力与当前索引可用性；索引失效不改变原件或发布时的记录。
    def schema(self,reference):
        reader = self.reader(reference)
        inventory = reader.inventory()
        index = DerivedIndex(self.catalog,reader,limit=self.limit)
        available = index.availability()
        frozen = inventory['schema']
        # readiness 是实时能力视图；content_readiness/published_readiness 保留发布时的事实。
        effective = deepcopy(frozen['content_readiness'])
        has_records = bool(inventory['records'])
        effective['text_search'] = available['status']
        effective['records'] = ('partial' if any(r['status']!='parsed' for r in inventory['records']) else 'ready') if has_records and available['status']=='ready' else 'not_ready'
        effective['concepts'] = 'partial' if has_records and available['status']=='ready' else 'not_ready'
        capabilities = ['read_evidence']
        if inventory['sections']:
            capabilities.append('search_asset.outline')
        if available['status']=='ready':
            capabilities += ['search_asset.text']
            if has_records:
                capabilities += ['search_asset.concept','query_records']
        return dict(asset_ref=reader.reference.model_dump(mode='json'),content_readiness=frozen['content_readiness'],
            published_readiness=frozen['published_readiness'],readiness=effective,availability=available,
            capabilities=capabilities,gaps=frozen['gaps'],records_applicable=has_records,
            concept_basis='source_inline_qname_only',freshness='not_confirmed_latest')

    # 分页返回预检得到的候选，并刷新读取时的能力状态；不隐式获取缺失材料。
    def find_assets(self):
        items,issues,version = self.found
        selected,cursor,truncated,page_issues = self.page(items,version)
        for item in selected:
            self.check('asset_description')
            try:
                description = self.schema(item['asset_ref'])
                item['readiness'] = description['readiness']
            except CatalogError as error:
                if error.code != 'UNSUPPORTED_FORMAT':
                    raise
                item['readiness'] = {}
                item['issues'].append(dict(code='CAPABILITY_UNSUPPORTED',message='format has no HTML query adapter'))
        return self.response(selected,cursor=cursor,issues=issues+page_issues,truncated=truncated,
            coverage=dict(status='partial' if issues else 'complete',catalog_view=version,matched_candidates=len(items)))

    # 从指定父章节按层展开至 depth；返回原始章节及其块数量，不推断业务分类。
    def _outline(self,inventory,section_id,depth):
        sections = {s['id']:s for s in inventory['sections']}
        if section_id is not None and section_id not in sections:
            raise CatalogError('TARGET_NOT_FOUND','section does not exist')
        result = []
        parents = {section_id}
        for level in range(depth):
            layer = [s for s in inventory['sections'] if s['parent_id'] in parents]
            result.extend(dict(section_id=s['id'],title_raw=s['title'],parent_id=s['parent_id'],basis=s['basis'],
                block_id=s['block_id'],block_count=sum(b['section_id']==s['id'] for b in inventory['blocks'])) for s in layer)
            parents = {s['id'] for s in layer}
        return result

    # 返回资产概览和所请求的目录/字段/概念分面，分页与当前可用性绑定。
    def get_asset_schema(self):
        request = self.request
        reader = self.reader(request.asset_ref)
        inventory = reader.inventory()
        value = self.schema(request.asset_ref)
        meta = self.metas[canonical(request.asset_ref.model_dump(mode='json'))]
        value['overview'] = {k:meta['asset_data'][k] for k in ('title','asset_kind','material_type','language','reporting_period')}
        value['overview'].update(source=meta['source'],source_id=meta['source_id'],acquisition=meta['acquisition'],
            entity_relations=meta['relations'],format=meta['format'])
        entries = []
        if 'outline' in request.facets or request.outline:
            outline = request.outline
            entries += [dict(facet='outline',value=v) for v in self._outline(inventory,outline.section_id if outline else None,outline.depth if outline else 1)]
        if 'fields' in request.facets:
            entries += [dict(facet='fields',value=dict(name=k,type='string_or_struct',nullable_meaning='source missing or unsupported')) for k in ('record_id','concept_id','value','raw_value','status','period','unit','dimensions','locator')]
        if 'concepts' in request.facets:
            concepts = sorted({concept_id(r) for r in inventory['records'] if concept_id(r)})
            entries += [dict(facet='concepts',value=dict(concept_id=c,target_count=sum(concept_id(r)==c for r in inventory['records']),basis='source_inline_qname')) for c in concepts]
        version = digest(canonical([request.asset_ref.model_dump(mode='json'),value['availability']]))
        selected,cursor,truncated,issues = self.page(entries,version)
        value['facets'] = selected
        value['coverage'] = dict(blocks=len(inventory['blocks']),records=len(inventory['records']),images_unread=len(inventory['images']),semantic_annotation='not_performed')
        return self.response([value],cursor=cursor,truncated=truncated,issues=issues)

    # 分派目录、原生 QName 概念或文本检索，并将命中片段与上下文绑定为证据。
    def search_asset(self):
        request = self.request
        reader = self.reader(request.asset_ref)
        inventory = reader.inventory()
        blocks = {b['id']:b for b in inventory['blocks']}
        issues = []
        item_issues = {}
        if request.mode == 'outline':
            items = self._outline(inventory,request.outline.section_id,request.outline.depth)
            version = digest(canonical(request.asset_ref.model_dump(mode='json')))
        elif request.mode == 'concept':
            if not inventory['records']:
                raise CatalogError('CAPABILITY_UNSUPPORTED','no inline concept annotations in this source')
            if request.concept.roles:
                raise CatalogError('CAPABILITY_UNSUPPORTED','semantic concept roles have not been annotated')
            from ..contracts.query import RecordFilters
            filters = RecordFilters(periods=request.concept.periods,dimensions=request.concept.dimensions)
            self._validate_filters(filters)
            rows,version = self.index(request.asset_ref).record_rows(concepts=(request.concept.concept_id,),filters=filters)
            items = [dict(record_id=r['id'],concept_id=concept_id(r),evidence=result_item(self.session,self.operation,'evidence',source_evidence(reader,'record_field',r['id']))) for r in rows]
            issues.append(dict(code='CONCEPT_COVERAGE_PARTIAL',message='only source inline QName annotations searched; unannotated prose was not classified'))
        else:
            if 'ocr' in request.scope.text_origins or 'caption' in request.scope.text_origins:
                raise CatalogError('CAPABILITY_UNSUPPORTED','OCR/caption origin classification is not available for this HTML recipe')
            ids,version,matched_ranges = self.index(request.asset_ref).text_candidates(request.text,with_ranges=True)
            if request.scope.section_ids and any(s not in {v['id'] for v in inventory['sections']} for s in request.scope.section_ids):
                raise CatalogError('TARGET_NOT_FOUND','section scope does not exist')
            items = []
            for identity in ids:
                self.check('search_result')
                block = blocks[identity]
                if request.scope.section_ids and block['section_id'] not in request.scope.section_ids:
                    continue
                if request.scope.block_kinds and block['kind'] not in request.scope.block_kinds:
                    continue
                origin = 'table' if block['kind']=='table' else 'text_layer'
                if request.scope.text_origins and origin not in request.scope.text_origins:
                    continue
                item = dict(block_id=identity,section_id=block['section_id'],origin=origin,match_mode=request.text.match)
                if 'snippet' in request.include:
                    text = block['text']
                    match_start,match_end = matched_ranges[identity]
                    # 片段围绕实际命中位置截取；返回范围只证明该片段已展示，不代表全文已阅读。
                    begin = max(0,match_start-80)
                    evidence = source_evidence(reader,'block',identity,start=begin,end=min(begin+300,len(text)))
                    item['evidence'] = result_item(self.session,self.operation,'evidence',evidence)
                    item['snippet_scope'] = 'returned_range_only'
                    item['match_range'] = dict(char_start=match_start,char_end=match_end)
                if 'section_title' in request.include:
                    item['section_title'] = next((s['title'] for s in inventory['sections'] if s['id']==block['section_id']),None)
                from .reading import table_context, block_context
                from ..contracts.query import Neighbors
                context_options = tuple('table_headers' if v=='table_header' else v for v in request.include)
                contexts = block_context(reader,inventory,block,context_options,Neighbors())
                table = next((t for t in inventory['tables'] if t['block_id']==identity),None)
                if table:
                    extra,gaps = table_context(reader,inventory,table,table['cells'],context_options)
                    contexts += extra
                    item_issues[identity] = gaps
                if contexts:
                    item['context_evidence'] = [result_item(self.session,self.operation,'evidence',v) for v in contexts]
                    if 'evidence' in item:
                        item['evidence']['dependency_refs'] = [v['result_ref'] for v in item['context_evidence']]
                items.append(item)
        return self.search_page(items,version,issues,item_issues,
            dict(mode=request.mode,matched_items=len(items),blocks_total=len(blocks),
                scope=request.scope.model_dump(mode='json'),not_searched=['unannotated_prose'] if request.mode=='concept' else []))

    # 按整个响应的字节预算分页；命中与必要上下文作为整体保留，不裁掉依赖。
    def search_page(self,items,version,issues,item_issues,coverage):
        """Bound the complete envelope; keep each hit and its dependencies whole."""
        request = self.request
        offset = position(self.session,self.tool,request,version)
        if offset > len(items):
            raise CatalogError('CURSOR_EXPIRED','cursor is outside this search view')
        selected,selected_issues,end = [],list(issues),offset
        # Stored cursor IDs have fixed width; leave 512 bytes for resource_usage
        # added by DataService, which also checks the final serialized size.
        placeholder = 'cur_'+'0'*26
        required_bytes = None
        while end < len(items) and len(selected) < request.limit:
            self.check('search_page')
            candidate = items[end]
            proposed_issues = selected_issues+item_issues.get(candidate.get('block_id'),[])
            more = end+1 < len(items)
            proposed = self.response(selected+[candidate],cursor=placeholder if more else None,
                truncated=more,issues=proposed_issues,
                coverage=coverage | {'status':'partial' if more or proposed_issues else 'complete'})
            required_bytes = len(canonical(proposed))+512
            # 放不下时不推进 end，调用方可增大预算或缩小目标后从同一位置继续。
            if required_bytes > request.max_bytes:
                break
            selected.append(candidate)
            selected_issues = proposed_issues
            end += 1
        if end == offset and end < len(items):
            target = {k:items[end][k] for k in ('block_id','record_id','section_id') if k in items[end]}
            selected_issues.append(dict(code='ITEM_TOO_LARGE',target=target,required_bytes=required_bytes,
                message='Hit and required context exceed max_bytes; position retained. Increase max_bytes at this cursor, or start a narrower search/read_evidence for this target.'))
        cursor = advance(self.session,self.tool,request,version,end) if end < len(items) else None
        return self.response(selected,cursor=cursor,truncated=cursor is not None,issues=selected_issues,
            coverage=coverage | {'status':'partial' if cursor or selected_issues else 'complete'})

    # 交给统一读取器解析目标、补取上下文并限制实际返回范围。
    def read_evidence(self):
        from .reading import read_targets
        return read_targets(self)

    # 交给结构化查询层执行字段筛选与 Decimal 计算。
    def query_records(self):
        from ..structured.records import execute_records
        return execute_records(self)

    # 先检查需求归属和扩展授权，再获取原件或重建整份 HTML 的派生能力。
    def request_asset_update(self):
        request = self.request
        if request.need_id not in {n['need_id'] for n in self.session.data['plan']['needs']}:
            raise CatalogError('INVALID_REQUEST','update refers to an unknown need')
        policy = self.context['request']['expansion']
        action = request.action
        capabilities = request.process.capabilities if request.process else ()
        allowed = policy['mode']=='controlled' and (action in policy['allow'] or bool(capabilities) and all(action+':'+c in policy['allow'] for c in capabilities))
        denied = action in policy['deny'] or any(action+':'+c in policy['deny'] for c in capabilities)
        # 拒绝规则优先；权限不足在外部调用或处理开始前返回明确的 denied。
        if not allowed or denied:
            return self.response([dict(update_id=self.operation,status='denied',policy_decision=dict(allowed=False,denied_reason='expansion_policy'),new_asset_refs=[],gaps=['POLICY_DENIED'])],
                issues=[dict(code='POLICY_DENIED',message='update denied before any external call or processing')])
        if action=='acquire':
            if self.acquisition_adapter is None:
                return self.response([dict(update_id=self.operation,status='denied',policy_decision=dict(allowed=False,denied_reason='acquisition_adapter_not_configured'),new_asset_refs=[],gaps=['ACQUISITION_NOT_ENABLED'])],
                    issues=[dict(code='ACQUISITION_NOT_ENABLED',message='no host-approved acquisition adapter configured')])
            plan = self.acquisition_adapter.validate(self)
            result = self.acquisition_adapter.execute(self,plan)
            return self.response([result],issues=[dict(code='ACQUISITION_PARTIAL',message=g) for g in result['gaps']])
        if request.process.targets or any(c not in {'text_search','records','concepts','tables'} for c in capabilities):
            raise CatalogError('CAPABILITY_UNSUPPORTED','only whole-build HTML derived processing is supported')
        reader = self.reader(request.process.asset_ref)
        if any(c in {'records','concepts'} for c in capabilities) and not reader.inventory()['records']:
            raise CatalogError('CAPABILITY_UNSUPPORTED','source has no inline records to derive')
        manifest = self.index(request.process.asset_ref).build(checkpoint=self.check,on_effect=self.effect,on_prepare=self.prepare_index)
        return self.process_response(manifest['generation'])
