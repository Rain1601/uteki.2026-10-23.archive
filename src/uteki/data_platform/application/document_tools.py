"""Document backend for the existing shared tools, not a separate Agent loop."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path

from ..contracts.common import CatalogError, canonical, digest
from ..contracts.content import ObjectRef
from ..contracts.document_query import DocumentRef, DocumentScope, PassageTarget, SectionTarget
from ..contracts.documents import BlockQuery, BlockRef
from ..contracts.query import BlockTarget, TableTarget, parse
from ..content.store import ContentStoreError
from ..documents.store import DocumentStore
from ..documents.query import DocumentStoreError
from ..retrieval.cursors import position, advance
from .evidence import result_item
from .tools import ToolExecution


@contextmanager
def open_documents(scope):
    try:
        with DocumentStore.open(Path(scope.data_root)) as store:
            yield store
    except (DocumentStoreError, ContentStoreError) as error:
        raise CatalogError(error.code, str(error)) from error


def check_version(store, reference):
    """Check explicit identities; never choose a current/default parse."""
    row = store._parse_row(reference.parse_id)
    actual = dict(kind='document_parse', material_id=row['material_id'],
                  source_version_id=row['source_version_id'], parse_id=row['parse_id'],
                  package_ref=json.loads(row['package_ref']))
    if actual != reference.model_dump(mode='json'):
        raise CatalogError('INVALID_REFERENCE', 'document identities or frozen package differ')
    return row


def validate_scope(catalog, scope, companies, policy):
    """Validate host-supplied bindings without filling unknown source metadata."""
    with open_documents(scope) as store:
        for binding in scope.bindings:
            if binding.company_id not in companies:
                raise CatalogError('SCOPE_DENIED', 'document company binding is outside context')
            source = json.loads(catalog._get('sources','source_id',binding.source_id)['payload'])
            if source['source_kind'] not in policy.source_kinds or (
                    policy.source_ids and binding.source_id not in policy.source_ids):
                raise CatalogError('SCOPE_DENIED', 'document source is outside read policy')
            check_version(store, binding.asset_ref)
            package = store.export_package(binding.asset_ref.parse_id)
            if source['canonical_url'] != package.source.source_url:
                raise CatalogError('INVALID_REFERENCE', 'registered source URL differs from frozen document')
            store.read_source(binding.asset_ref.parse_id)


def native_nodes(schema):
    result = []
    def visit(node):
        result.append({k:v for k,v in node.items() if k != 'children'})
        for child in node['children']:
            visit(child)
    for root in schema['directory']['nodes']:
        visit(root)
    return result


class DocumentToolExecution(ToolExecution):
    def preflight(self):
        self.scope = parse(DocumentScope, self.context['request']['documents'])
        self.bindings = {canonical(b.asset_ref.model_dump(mode='json')):b for b in self.scope.bindings}
        self.require_security_filter()
        if self.tool == 'request_asset_update':
            raise CatalogError('CAPABILITY_UNSUPPORTED', 'this document scope is read-only; parsing is never implicit')
        if self.tool == 'read_evidence' and (
                self.request.include_image or self.request.table_representation != 'full'):
            raise CatalogError('CAPABILITY_UNSUPPORTED',
                'document evidence currently supports full table structure and text/locations; image payloads and compact tables are not implemented')
        if self.tool != 'find_assets':
            if self.context['request'].get('as_of'):
                raise CatalogError('SCOPE_DENIED','document historical availability has not been established')
            if not isinstance(self.request.asset_ref, DocumentRef):
                raise CatalogError('SCOPE_DENIED', 'this context is pinned to explicit document versions')
            self.binding = self.bindings.get(canonical(self.request.asset_ref.model_dump(mode='json')))
            if self.binding is None:
                raise CatalogError('SCOPE_DENIED', 'document version is not admitted in this context')
            self.require_discovered(self.request.asset_ref)
            with open_documents(self.scope) as store:
                check_version(store, self.request.asset_ref)
        if self.tool == 'query_records':
            # Implemented by the document-record adapter, never by the iXBRL index.
            from ..structured.document_records import validate_request
            validate_request(self)
            for calculation in self.request.calculations:
                for operand in calculation.operands:
                    self.require_discovered(operand.asset_ref)

    def execute(self, operation_id):
        try:
            return super().execute(operation_id)
        except DocumentStoreError as error:
            raise CatalogError(error.code, str(error)) from error

    def _schema(self, store, reference):
        check_version(store, reference)
        return store.get_schema(reference.parse_id)

    def _node(self, schema, value):
        nodes = native_nodes(schema)
        matches = [n for n in nodes if value in (n['node_id'], n['code_path'])]
        if len(matches) != 1:
            raise CatalogError('TARGET_NOT_FOUND', 'choose an exact node_id or code_path from the schema')
        return matches[0]

    def _metadata(self, value, reference, source, projection):
        # Freeze only this returned projection. A schema page does not certify
        # omitted directory nodes, document contents, periods or source quality.
        return result_item(self.session,self.operation,'metadata',value | dict(
            asset_ref=reference.model_dump(mode='json'),kind='document_metadata',
            locator=dict(kind='document_metadata',projection=projection),
            source_url=source['source_url'],source_object=source['object_ref'],
            statement_scope='registered_metadata_and_parser_output_not_source_facts',
            semantic_verification='not_performed'))

    def find_assets(self):
        request = self.request
        filters = request.filters
        items, issues = [], []
        if filters and filters.content_periods:
            raise CatalogError('CAPABILITY_UNSUPPORTED', 'document discovery has no content-period projection')
        if filters and filters.roles != ('issuer', 'subject'):
            raise CatalogError('CAPABILITY_UNSUPPORTED', 'document caller bindings do not establish entity roles')
        symbol_companies, symbol_matches = set(), []
        for security in filters.securities if filters else ():
            cutoff = request.as_of or self.context['request'].get('as_of')
            if cutoff:
                from datetime import datetime
                when = datetime.fromisoformat(cutoff) if isinstance(cutoff,str) else cutoff
                rows = [self.catalog.resolve_security(security.ticker,security.exchange_mic,as_of=when.date())]
            else:
                # Discovery uses registered issuer aliases, not an assertion of
                # current listing status or an invented historical interval.
                rows = [dict(r) for r in self.catalog._db.execute(
                    "SELECT s.* FROM company_securities s JOIN companies c USING(company_id) "
                    "WHERE s.ticker=? AND s.exchange_mic=? AND s.status='confirmed' AND c.status='confirmed'",
                    (security.ticker,security.exchange_mic))]
            ids = {r['company_id'] for r in rows}
            if not ids:
                raise CatalogError('NOT_FOUND','symbol has no confirmed registered company mapping')
            if len(ids)!=1:
                raise CatalogError('AMBIGUOUS_ENTITY','symbol maps to multiple registered companies; specify an evidenced historical as_of or an explicit company_id')
            symbol_companies.update(ids)
            symbol_matches.append(dict(ticker=security.ticker,exchange_mic=security.exchange_mic,
                company_id=next(iter(ids)),basis='confirmed_registered_mapping',
                temporal_validity='checked_at_cutoff' if cutoff else 'not_asserted'))
        with open_documents(self.scope) as store:
            for binding in self.scope.bindings:
                schema = self._schema(store, binding.asset_ref)
                material, source = schema['material'], schema['source']
                company = self.catalog.get_company(binding.company_id)
                if filters:
                    if filters.securities and binding.company_id not in symbol_companies: continue
                    if filters.company_ids and binding.company_id not in filters.company_ids: continue
                    if filters.company_names and company['canonical_name'] not in filters.company_names: continue
                    if filters.asset_kinds and 'document' not in filters.asset_kinds: continue
                    if filters.formats and source['format'] not in filters.formats: continue
                    if filters.material_types and material['material_type'] not in filters.material_types: continue
                    if filters.reporting_periods:
                        period = material['reporting_period']
                        if not period:
                            issues.append(dict(code='REPORTING_PERIOD_UNKNOWN', material_id=material['material_id']))
                            continue
                        if period['label'] not in filters.reporting_periods: continue
                    if filters.published_at:
                        raise CatalogError('CAPABILITY_UNSUPPORTED', 'publication range filtering requires known source timestamps')
                if request.query and request.query.casefold() not in (material['name']+' '+company['canonical_name']+' '+material['material_type']).casefold():
                    continue
                cutoff = request.as_of or self.context['request'].get('as_of')
                gaps = []
                if cutoff:
                    # These documents carry acquisition/publication observations, not historical availability proof.
                    gaps.append('HISTORICAL_AVAILABILITY_NOT_CONFIRMED')
                    issues.append(dict(code=gaps[0],material_id=material['material_id']))
                items.append(self._metadata(dict(asset_ref=binding.asset_ref.model_dump(mode='json'),title=material['name'],
                    metadata=dict(material=material,source=source,caller_binding=binding.model_dump(mode='json'),
                                  symbol_matches=[m for m in symbol_matches if m['company_id']==binding.company_id],
                                  entity_binding_status='caller_selected_not_source_verified'),
                    readiness=dict(document=schema['status'],passages='ready' if 'read_passage' in schema['capabilities'] else 'not_ready'),
                    freshness='not_confirmed_latest',issues=gaps),binding.asset_ref,source,'find_assets'))
        selected,cursor,truncated,page_issues = self.page(items,digest(self.scope.canonical_bytes()))
        return self.response(selected,cursor=cursor,truncated=truncated,issues=issues+page_issues)

    def _outline(self, schema, outline):
        nodes = self._directory_nodes(schema)
        if outline and outline.section_id:
            parent = self._node(schema,outline.section_id)
            prefix, depth = parent['code_path']+'.', parent['depth']
            nodes = [n for n in nodes if n['code_path'].startswith(prefix)]
        else:
            depth = 0
        return [n for n in nodes if n['depth'] <= depth+(outline.depth if outline else 1)]

    def _directory_nodes(self, schema):
        """Preorder keeps children next to parents; counts explicitly distinguish scope."""
        result = []
        issues = schema['directory']['issues']
        def visit(node):
            value = dict(section_id=node['node_id'],title_raw=node['title'],parent_id=node['parent_id'],
                code_path=node['code_path'],depth=node['depth'],child_count=len(node['children']),
                direct_blocks=node['block_count'],direct_passages=node.get('passage_count',0),
                subtree_blocks=node['block_count'],subtree_passages=node.get('passage_count',0),
                boundary_basis=node.get('hierarchy_basis','native_directory'),
                issues=[issue for issue in issues if issue.endswith(':'+node['node_id'])])
            result.append(value)
            for child in node['children']:
                child_value = visit(child)
                value['subtree_blocks'] += child_value['subtree_blocks']
                value['subtree_passages'] += child_value['subtree_passages']
            return value
        for root in schema['directory']['nodes']:
            visit(root)
        return result

    def get_asset_schema(self):
        request = self.request
        with open_documents(self.scope) as store:
            schema = self._schema(store,request.asset_ref)
        facets = []
        nodes = self._directory_nodes(schema)
        wants_directory = 'outline' in request.facets or request.outline is not None
        complete_directory = wants_directory and request.outline is None and len(canonical(nodes)) <= 100000
        if wants_directory and not complete_directory:
            facets = [dict(facet='outline',value=n) for n in self._outline(schema,request.outline)]
        if 'fields' in request.facets:
            facets.append(dict(facet='fields',value=dict(source='PDF text/table observations',
                records='not native iXBRL facts; submit source-backed document extractions to query_records')))
        if 'concepts' in request.facets:
            facets.append(dict(facet='concepts',value=dict(status='not_applicable',reason='PDF has no native XBRL concepts')))
        selected,cursor,truncated,issues = self.page(facets,digest(request.asset_ref.canonical_bytes()))
        value = dict(asset_ref=request.asset_ref.model_dump(mode='json'),
            overview=dict(material=schema['material'],source=schema['source'],caller_binding=self.binding.model_dump(mode='json')),
            readiness=dict(document=schema['status'],processing=schema['processing']),
            capabilities=['get_asset_schema','search_asset.outline','search_asset.text','read_evidence.section',
                'read_evidence.block','read_evidence.table','query_records.document_records','deliver']+
                (['search_asset.passages','read_evidence.passage'] if 'read_passage' in schema['capabilities'] else []),
            coverage=dict(content_summary=schema['content_summary'],issues=schema['issues'],
                source_completeness='not_verified'),facets=selected,
            directory=dict(nodes=nodes if complete_directory else [],complete=complete_directory,
                total_nodes=len(nodes),status=schema['directory']['status'],
                has_source_directory=schema['directory']['has_source_directory'],
                issues=schema['directory']['issues'],counts_scope='direct versus subtree explicitly named',
                continuation=None if complete_directory else 'Use outline facets/next_cursor, then search_asset mode=outline on a returned section_id; omitted descendants are not absent content.'),
            tool_options=dict(text_search=dict(match=['phrase'],case_sensitive=False,
                scope_filters=dict(section_ids='one node or path, including descendants',block_kinds=['table'],text_origins=['table']),
                include=['snippet','section_title']),
                evidence=dict(table_representation=['full'],include_image=False,table_indices='zero_based',
                    neighbors='only expanded when context includes neighbors; before/after are independent',
                    semantic_context='units and consolidation are not inferred; read source context explicitly',
                    whole_table='omit rows and cols to inspect the complete grid before choosing cells',
                    section_pagination='One section_path target supports block-boundary pagination. Keep the same parent path, scope and context; pass next_cursor until null. Cite every page_evidence, not just the last page.')))
        value=self._metadata(value,request.asset_ref,schema['source'],'get_asset_schema')
        return self.response([value],cursor=cursor,truncated=truncated,issues=issues)

    def search_asset(self):
        request = self.request
        with open_documents(self.scope) as store:
            schema = self._schema(store,request.asset_ref)
            if request.mode == 'concept':
                raise CatalogError('CAPABILITY_UNSUPPORTED', 'PDF has no native XBRL concepts; use directory or text search')
            if request.mode == 'outline':
                items = [self._metadata(n,request.asset_ref,schema['source'],'search_asset.outline')
                         for n in self._outline(schema,request.outline)]
            elif request.mode == 'passages':
                if request.outline.depth != 1:
                    raise CatalogError('INVALID_REQUEST','passages does not use outline.depth; use passage_scope=direct or subtree')
                if not request.outline.section_id:
                    raise CatalogError('INVALID_REQUEST', 'passages requires outline.section_id (node_id or code_path)')
                node = self._node(schema,request.outline.section_id)
                selected_nodes = [n for n in native_nodes(schema) if n['node_id']==node['node_id'] or
                    (request.passage_scope=='subtree' and n['code_path'].startswith(node['code_path']+'.'))]
                items = []
                for current in selected_nodes:
                    for passage in store.list_passages(request.asset_ref.parse_id,node_id=current['node_id']):
                        lead = store._block(BlockRef(material_id=request.asset_ref.material_id,
                            parse_id=schema['parse_id'],block_id=passage['lead_block_id'] or passage['block_ids'][0]))
                        items.append(passage | dict(path=current['code_path']+f'.passages[{passage["index"]}]',
                            section_title=current['title'],lead_text=lead['text'],lead_locations=lead['locations'],
                            member_count=len(passage['block_ids']),scope=request.passage_scope))
            else:
                scope=request.scope
                if (request.text.match != 'phrase' or request.text.case_sensitive
                        or len(scope.section_ids)>1 or set(scope.block_kinds)-{'table'}
                        or set(scope.text_origins)-{'table'} or set(request.include)-{'snippet','section_title'}):
                    raise CatalogError('CAPABILITY_UNSUPPORTED', 'document search supports phrase, snippet/section_title, one section and table filters; read exact targets for other context')
                # Reuse the indexed query; keep its version-bound cursor in the existing session cursor record.
                from ..retrieval.cursors import position,advance
                version = digest(request.asset_ref.canonical_bytes())
                offset = position(self.session,self.tool,request,version)
                saved = self.session.data.get('document_cursors',{}).get(request.cursor) if request.cursor else None
                if request.cursor and saved is None:
                    raise CatalogError('CURSOR_MISMATCH','document cursor binding is missing')
                query = BlockQuery(parse_id=request.asset_ref.parse_id,content_view='body',text=request.text.value,
                                   directory_node_id=self._node(schema,scope.section_ids[0])['node_id'] if scope.section_ids else None,
                                   include_descendants=bool(scope.section_ids),
                                   types=('table',) if scope.block_kinds or scope.text_origins else (),
                                   limit=request.limit,max_bytes=1_000_000)
                page = store.query_blocks(query,cursor=saved)
                for hit in page['items']:
                    if 'snippet' not in request.include: hit.pop('matches',None)
                    if 'section_title' in request.include:
                        block=store.read_block(BlockRef.model_validate(hit['ref']),include_context=False)['block']
                        hit['sections']=self._sections(schema,block)
                cursor = None
                if page['next_cursor']:
                    # Opaque token is keyed by the new shared cursor, not by a query-independent offset.
                    cursor = advance(self.session,self.tool,request,version,offset+1)
                    self.session.data.setdefault('document_cursors',{})[cursor] = page['next_cursor']
                if len(canonical(page['items']))>request.max_bytes-2000:
                    raise CatalogError('RESULT_TOO_LARGE','search hits and requested metadata exceed max_bytes; reduce limit or increase max_bytes')
                return self.response(page['items'],cursor=cursor,truncated=page['has_more'],
                    navigation_asset_ref=request.asset_ref.model_dump(mode='json'))
        items,cursor,truncated,issues = self.page(items,digest(request.asset_ref.canonical_bytes()),max_bytes=request.max_bytes-2000)
        return self.response(items,cursor=cursor,truncated=truncated,issues=issues,
                             navigation_asset_ref=request.asset_ref.model_dump(mode='json'))

    def _sections(self, schema, block):
        return [dict(section_id=n['node_id'],title_raw=n['title'],code_path=n['code_path'])
                for n in native_nodes(schema) if n['node_id'] in block['directory_node_ids']]

    def _evidence(self, schema, block, *, cell=None, char_range=None, role='target'):
        text = cell['text'] if cell is not None else (block['text'] or '')
        lower, upper = char_range or (0,len(text))
        if not 0 <= lower <= upper <= len(text):
            raise CatalogError('INVALID_REQUEST','character range is outside source block')
        text = text[lower:upper]
        locator = dict(kind='document_block',block_id=block['block_id'],locations=block['locations'],
                       char_range=[lower,upper] if block['type']=='text' else None,text_sha256=digest(text.encode()))
        content = dict(text=text,type=block['type'])
        if cell is not None:
            locator.update(row=cell['row'],column=cell['column'],cell_locations=cell['locations'])
            content['cell'] = deepcopy(cell)
        elif block['table'] is not None:
            content['table'] = deepcopy(block['table'])
        value = dict(asset_ref=self.request.asset_ref.model_dump(mode='json'),locator=locator,
            reader_ref=dict(material_id=schema['material']['material_id'],parse_id=schema['parse_id'],block_id=block['block_id']),
            source_object=schema['source']['object_ref'],source_url=schema['source']['source_url'],
            kind=block['type'],role=role,content=content,dependency_refs=[],truncated=char_range is not None,
            quality=dict(extraction='document_parser',status=block['status'],parse_status=schema['status'],
                         issues=block['issues'],semantic_verification='not_performed'))
        if 'section_title' in self.request.context:
            value['sections']=self._sections(schema,block)
        return result_item(self.session,self.operation,'evidence',value)

    def _read_section_page(self, store, schema, target):
        """Page one frozen section internally; the caller never expands child paths.

        A page root references only the blocks actually returned on that page.
        It does not certify whole-section coverage or semantic sufficiency.
        """
        request = self.request
        node = self._node(schema, target.section_path)
        version = digest(canonical(dict(asset=request.asset_ref.model_dump(mode='json'),
            layout='document-section-block-pages-v1')))
        start = position(self.session, self.tool, request, version)
        query = BlockQuery(parse_id=schema['parse_id'],directory_node_id=node['node_id'],
            include_descendants=target.include_descendants,content_view='body',limit=100,max_bytes=1000000)
        references, cursor = [], None
        while True:
            self.check('section_inventory_page')
            page = store.query_blocks(query,cursor=cursor)
            references.extend(item['ref'] for item in page['items'])
            cursor = page['next_cursor']
            if cursor is None:
                break
        total = len(references)
        if start > total:
            raise CatalogError('CURSOR_EXPIRED','section cursor is outside the frozen block inventory')

        def candidate(items):
            end = start+len(items)
            coverage = dict(status='complete_section' if start==0 and end==total else 'section_page',
                block_start=start,block_end_exclusive=end,total_blocks=total,
                more_blocks=end<total,all_pages_required=True,source_completeness='not_verified')
            root = result_item(self.session,self.operation,'evidence',dict(
                asset_ref=request.asset_ref.model_dump(mode='json'),kind='section_page',role='target',
                locator=dict(kind='document_section_page',section_path=target.section_path,
                    include_descendants=target.include_descendants,block_start=start,block_end_exclusive=end),
                source_object=schema['source']['object_ref'],source_url=schema['source']['source_url'],
                content=dict(type='section_page',member_block_ids=[i['locator']['block_id'] for i in items]),
                dependency_refs=[i['result_ref'] for i in items],truncated=False,coverage=coverage,
                quality=dict(parse_status=schema['status'],semantic_verification='not_performed')))
            return dict(target=target.model_dump(mode='json'),scope='subtree' if target.include_descendants else 'direct',
                items=items,page_evidence=root,coverage=coverage,
                source_completeness='not_verified',parse_status=schema['status'])

        selected, required = [], None
        result = candidate(selected)
        for reference in references[start:]:
            self.check('section_block')
            block = store.read_block(BlockRef.model_validate(reference),include_context=False)['block']
            item = self._evidence(schema,block)
            proposed = candidate([*selected,item])
            size = len(canonical(proposed))
            if size > request.max_bytes-2000:
                required = size+2000
                break
            selected.append(item)
            result = proposed
        end = start+len(selected)
        more = end<total
        cursor = advance(self.session,self.tool,request,version,end) if more else None
        issues = []
        if more and not selected:
            issues.append(dict(code='ITEM_TOO_LARGE',required_bytes=required,
                message='One source block and its page envelope exceed max_bytes. Increase max_bytes at this cursor; no block was skipped.'))
        return self.response([result] if selected or not total else [],cursor=cursor,
            truncated=more,issues=issues,coverage=dict(status='partial' if more or start else 'complete',
                block_start=start,block_end_exclusive=end,total_blocks=total,
                all_pages_required=True,source_completeness='not_verified'))

    def read_evidence(self):
        request = self.request
        candidates = []
        with open_documents(self.scope) as store:
            schema = self._schema(store,request.asset_ref)
            store.read_source(request.asset_ref.parse_id)  # Missing/corrupt originals cannot become successful evidence.
            if len(request.targets)==1 and isinstance(request.targets[0],SectionTarget):
                return self._read_section_page(store,schema,request.targets[0])
            for target in request.targets:
                self.check('document_read')
                if isinstance(target,(PassageTarget,SectionTarget)):
                    if isinstance(target,PassageTarget):
                        value = store.read_passage(schema['parse_id'],path=target.passage_path)
                    else:
                        value = store.read_section(schema['parse_id'],code_path=target.section_path,include_descendants=target.include_descendants)
                    group = [self._evidence(schema,b['block']) for b in value['blocks']]
                    candidate = dict(target=target.model_dump(mode='json'),items=group,
                        source_completeness=value['source_completeness'],parse_status=value['parse_status'])
                    if isinstance(target,PassageTarget):
                        # A group is an immutable evidence root. Delivery expands its
                        # members through the existing observed dependency closure.
                        passage = value['passage']
                        candidate['group_evidence'] = result_item(self.session,self.operation,'evidence',dict(
                            asset_ref=request.asset_ref.model_dump(mode='json'),kind='passage',role='target',
                            locator=dict(kind='document_passage',passage_id=passage['passage_id'],
                                passage_path=target.passage_path,locations=value['locations']),
                            source_object=schema['source']['object_ref'],source_url=schema['source']['source_url'],
                            content=dict(type='passage',member_block_ids=passage['block_ids'],
                                lead_block_id=passage['lead_block_id'],grouping_basis=passage['grouping_basis']),
                            dependency_refs=[item['result_ref'] for item in group],truncated=False,
                            quality=dict(parse_status=schema['status'],issues=value['issues'],
                                semantic_verification='not_performed'),
                            coverage=dict(status='complete_group',member_count=len(group),
                                source_completeness=value['source_completeness'])))
                    else:
                        candidate['scope'] = 'subtree' if target.include_descendants else 'direct'
                    candidates.append(candidate)
                elif isinstance(target,(BlockTarget,TableTarget)):
                    bid = target.block_id if isinstance(target,BlockTarget) else target.table_id
                    ref = BlockRef(material_id=request.asset_ref.material_id,parse_id=schema['parse_id'],block_id=bid)
                    expand_neighbors='neighbors' in request.context
                    read = store.read_block(ref,include_context=True,
                        neighbors=max(request.neighbors.before,request.neighbors.after) if expand_neighbors else 0)
                    block = read['block'];dependencies = []
                    before=sorted((r for r in read['context'] if r['relation']=='neighbor' and r['block']['order']<block['order']),key=lambda r:r['block']['order'],reverse=True)
                    after=sorted((r for r in read['context'] if r['relation']=='neighbor' and r['block']['order']>block['order']),key=lambda r:r['block']['order'])
                    selected_neighbors={r['ref']['block_id'] for r in before[:request.neighbors.before]+after[:request.neighbors.after]}
                    for related in read['context']:
                        if related['relation']=='neighbor' and related['ref']['block_id'] not in selected_neighbors:
                            continue
                        dependencies.append(self._evidence(schema,related['block'],role='context'))
                    if isinstance(target,BlockTarget):
                        group = [self._evidence(schema,block,char_range=target.char_range)]
                    else:
                        table = block['table']
                        if table is None or table['status'] != 'complete':
                            raise CatalogError('TABLE_NOT_READY','table structure is incomplete; inspect the block and its issues')
                        if any(r>=table['row_count'] for r in target.rows) or any(c>=table['column_count'] for c in target.cols):
                            raise CatalogError('INVALID_REQUEST',f'table selector outside source grid: row_count={table["row_count"]}, column_count={table["column_count"]}; indices are zero-based')
                        if not target.rows and not target.cols:
                            # Whole-grid inspection needs one version/location envelope,
                            # not a duplicate envelope and header closure for every cell.
                            group = [self._evidence(schema,block)]
                        else:
                            cells = [c for c in table['cells'] if (not target.rows or any(c['row']<=r<c['row']+c['row_span'] for r in target.rows))
                                and (not target.cols or any(c['column']<=col<c['column']+c['column_span'] for col in target.cols))]
                            if not cells: raise CatalogError('TARGET_NOT_FOUND','table selection contains no cells')
                            group = [self._evidence(schema,block,cell=c) for c in cells]
                            chosen = {(c['row'],c['column']) for c in cells}
                            rows = {r for c in cells for r in range(c['row'],c['row']+c['row_span'])}
                            first_header_row = min((c['row'] for c in table['cells'] if c['is_header']),default=-1)
                            # The parser's is_header also marks row names. Keep
                            # column headers and the selected rows' names, not
                            # every other row name in the document table.
                            headers = [c for c in table['cells'] if ((c['is_header'] and (
                                c['column']+c['column_span']>1 or c['row']==first_header_row)) or (c['column']==0
                                and any(r in rows for r in range(c['row'],c['row']+c['row_span']))))
                                and (c['row'],c['column']) not in chosen]
                            dependencies += [self._evidence(schema,block,cell=c,role='table_context') for c in headers]
                    for item in group:
                        item['dependency_refs'] = [d['result_ref'] for d in dependencies]
                    candidates.append(dict(target=target.model_dump(mode='json'),items=group,context=dependencies))
                else:
                    raise CatalogError('CAPABILITY_UNSUPPORTED','document evidence supports sections, passages, blocks and table rows/cells')
        items,cursor,truncated,issues = self.page(candidates,digest(request.asset_ref.canonical_bytes()),
                                                limit=16,max_bytes=request.max_bytes-2000)
        return self.response(items,cursor=cursor,truncated=truncated,issues=issues)

    def query_records(self):
        from ..structured.document_records import execute_records
        return execute_records(self)
