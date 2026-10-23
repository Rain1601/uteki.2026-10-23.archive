"""Strict requests for the deterministic, version-bound data tools."""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field, model_serializer, model_validator

from .assets import AssetRef, CompanyId, SourceId
from .common import Contract, FiscalPeriod, Text, canonical, id_type
from .evidence import HtmlLocator
from .document_query import DocumentRef, DocumentScope, PassageTarget, SectionTarget, DocumentRecordInput

ReadableAssetRef = AssetRef | DocumentRef


# 统一 Python 和 JSON 调用入口；已有模型也重新校验，普通值经规范 JSON 进入严格契约。
def parse(model, value):
    """JSON is the common boundary for Python callers and future SDK adapters."""
    if isinstance(value, model):
        return model.model_validate(value)
    return model.model_validate_json(canonical(value))


# 只接受完整起止期间或单个时点；拒绝日期/时间混用和无时区时间，以免比较口径含混。
def validate_period(period):
    if set(period) not in ({'start','end'},{'instant'}):
        raise ValueError('period requires exactly start/end or instant')
    parsed = []
    for value in period.values():
        if not isinstance(value,str):
            raise ValueError('source period value must be text')
        if 'T' in value:
            point = datetime.fromisoformat(value)
            if point.tzinfo is None:
                raise ValueError('datetime period requires explicit timezone')
        else:
            point = date.fromisoformat(value)
            if point.isoformat()!=value:
                raise ValueError('date period requires YYYY-MM-DD')
        parsed.append(point)
    if len({type(p) for p in parsed})!=1:
        raise ValueError('mixed date/datetime period is ambiguous')
    if 'start' in period:
        parser = datetime.fromisoformat if 'T' in period['start'] else date.fromisoformat
        if parser(period['start'])>parser(period['end']):
            raise ValueError('reversed period')


# 单位必须是原始度量列表或分子/分母两组度量，不自动换算或补造单位。
def validate_unit(unit):
    if set(unit) not in ({'measures'},{'numerator','denominator'}):
        raise ValueError('unit requires measures or numerator/denominator')
    if any(not values or any(not value.strip() for value in values) for values in unit.values()):
        raise ValueError('unit must contain nonempty source measures')


# 维度可显式未知，但提供时维度名与成员值都必须非空。
def validate_dimensions(dimensions):
    if dimensions is not None and any(not key.strip() or not value.strip() for key,value in dimensions.items()):
        raise ValueError('dimension names and members cannot be empty')


# 冻结可读取的来源类别及可选来源 ID 白名单，为后续每次读取提供共同范围约束。
class ReadPolicy(Contract):
    schema_version: Literal['uteki-read-policy-v1']
    source_kinds: tuple[Literal['sec_edgar', 'sec_xbrl_api', 'official_site', 'user_file'], ...]
    source_ids: tuple[SourceId, ...] = ()

    # 必须显式选择至少一种来源类别，空配置不能被解释成允许所有来源。
    @model_validator(mode='after')
    def nonempty(self):
        if not self.source_kinds:
            raise ValueError('explicit allowed source kinds required')
        return self


# 用 ticker 与交易所 MIC 联合定位登记证券，避免只靠代码猜测公司身份。
class Security(Contract):
    ticker: Text
    exchange_mic: Text


# 请求中的公司身份线索；不同种类线索是否解析到同一公司集合由目录解析层检查。
class Entities(Contract):
    company_ids: tuple[CompanyId, ...] = ()
    company_names: tuple[Text, ...] = ()
    securities: tuple[Security, ...] = ()

    # 至少提供一种实体线索，禁止无公司范围的查询上下文。
    @model_validator(mode='after')
    def nonempty(self):
        if not (self.company_ids or self.company_names or self.securities):
            raise ValueError('explicit registered entities required')
        return self


# 显式声明来源扩展是否开启及允许/禁止规则，不从查询文本自动扩大范围。
class Expansion(Contract):
    mode: Literal['disabled', 'controlled']
    allow: tuple[Text, ...]
    deny: tuple[Text, ...]

    # 受控扩展必须有允许规则，不能只声明 controlled 而留下开放边界。
    @model_validator(mode='after')
    def explicit_allow(self):
        if self.mode == 'controlled' and not self.allow:
            raise ValueError('controlled expansion requires explicit allow rules')
        return self


# 业务运行预算和停止边界；金额使用十进制文本，避免浮点金额表示误差。
class RunPolicy(Contract):
    max_usd: Annotated[str, Field(pattern=r'^(0|[1-9]\d*)(\.\d+)?$')]
    max_turns: Annotated[int, Field(ge=1, le=1000)]
    max_wall_seconds: Annotated[int, Field(ge=1, le=3600)]
    max_no_progress_turns: Annotated[int, Field(ge=1, le=1000)]


# 保留调用者身份类型及已有交付引用，供新上下文说明其来源。
class Caller(Contract):
    kind: Literal['user', 'analysis_agent']
    prior_delivery_refs: tuple[Text, ...] = ()


# 回答通过 clarification_id 绑定到一次明确的澄清请求。
class ClarificationAnswer(Contract):
    clarification_id: id_type('cl')
    answer: Text


# 查询上下文的完整输入：问题、实体、期间、来源策略和资源限制都由调用方显式提供。
class ContextRequest(Contract):
    question: Text
    caller: Caller
    entities: Entities
    periods: tuple[FiscalPeriod, ...] = ()
    as_of: datetime | None = None
    source_policy_ref: Text
    expansion: Expansion
    run_policy: RunPolicy
    revises_context_ref: id_type('req') | None = None
    clarification_response: ClarificationAnswer | None = None
    documents: DocumentScope | None = None
    required_securities: Annotated[tuple[Security, ...], Field(max_length=100)] = Field(
        default=(), description='Caller-supplied securities that asset discovery must explicitly filter and bind. Not inferred from question text or material names.')

    # 历史截止必须带时区；澄清回答必须同时声明被修订的上下文。
    @model_validator(mode='after')
    def timezone(self):
        if self.as_of is not None and self.as_of.tzinfo is None:
            raise ValueError('as_of requires a timezone')
        if self.clarification_response is not None and self.revises_context_ref is None:
            raise ValueError('clarification answer requires revises_context_ref')
        if len({(s.ticker,s.exchange_mic) for s in self.required_securities}) != len(self.required_securities):
            raise ValueError('duplicate required securities')
        return self

    # 省略未使用的续接字段，保持旧请求的规范字节与持久化身份兼容。
    def context_payload(self):
        # Preserve canonical requests created before continuation fields existed.
        value = self.model_dump(mode='json')
        for key in ('revises_context_ref','clarification_response','documents'):
            if value[key] is None:value.pop(key)
        if not value['required_securities']:
            value.pop('required_securities')
        return value


# 时间过滤区间采用包含下界 gte、排除上界 lt，至少需要一个明确边界。
class DateRange(Contract):
    gte: datetime | None = None
    lt: datetime | None = None

    # 验证边界存在、时区明确且区间方向正确，不自动交换用户给反的时间。
    @model_validator(mode='after')
    def interval(self):
        if self.gte is None and self.lt is None:
            raise ValueError('at least one time bound required')
        if any(v is not None and v.tzinfo is None for v in (self.gte, self.lt)):
            raise ValueError('time bounds require timezones')
        if self.gte and self.lt and self.gte >= self.lt:
            raise ValueError('reversed time interval')
        return self


# 资产发现的精确元数据条件；材料类型须使用登记名，未知过滤项由查询层明确处理。
class AssetFilters(Contract):
    company_ids: tuple[CompanyId, ...] = ()
    company_names: tuple[Text, ...] = ()
    securities: tuple[Security, ...] = ()
    roles: tuple[Literal['issuer', 'subject', 'mentioned'], ...] = ('issuer', 'subject')
    asset_kinds: tuple[Literal['document', 'dataset'], ...] = ()
    material_types: tuple[Text, ...] = Field(default=(), description='Exact registered material type names from discovery metadata, not guessed form titles. If unknown, omit this filter and use query first.')
    formats: tuple[Literal['html', 'pdf', 'xbrl_instance', 'api_json'], ...] = ()
    reporting_periods: tuple[Text, ...] = ()
    content_periods: tuple[Text, ...] = ()
    published_at: DateRange | None = None


# 在已冻结上下文范围内发现资产；本次 as_of 只能进一步收紧历史可用性范围。
class FindAssets(Contract):
    query: Annotated[str, Field(max_length=500, description='Optional short phrase matched against asset metadata (title, registered type, company names/aliases), not document contents or a natural-language question. Prefer company/period filters to enumerate candidates when the exact title is unknown; omit query to avoid excluding candidates.')] | None = None
    filters: AssetFilters | None = None
    as_of: datetime | None = Field(default=None, description='Optional explicit historical availability cutoff. Omit to inherit context.request.as_of; when that is null there is no cutoff. Never copy context.clock/created_at here merely because it is the current time. Unknown availability under a cutoff remains a gap.')
    limit: Annotated[int, Field(ge=1, le=50)] = 10
    cursor: Text | None = None

    # 必须有有效查询文本或过滤器，且额外指定的截止时间必须带时区。
    @model_validator(mode='after')
    def input(self):
        if not (self.query and self.query.strip()) and self.filters is None:
            raise ValueError('query or filters required')
        if self.as_of is not None and self.as_of.tzinfo is None:
            raise ValueError('as_of requires a timezone')
        return self


# 限定目录读取起点与展开深度；深度上限用于控制一次响应的范围。
class Outline(Contract):
    section_id: Text | None = None
    depth: Annotated[int, Field(ge=1, le=3)] = 1


# 读取指定构建的能力与结构概览，按请求 facets 和目录范围提供分页结果。
class GetAssetSchema(Contract):
    asset_ref: ReadableAssetRef
    facets: tuple[Literal['overview', 'outline', 'fields', 'concepts', 'coverage', 'readiness', 'capabilities'], ...] = ('overview', 'outline', 'readiness', 'capabilities')
    outline: Outline | None = None
    limit: Annotated[int, Field(ge=1, le=40)] = 40
    cursor: Text | None = None


# 声明文本匹配方式及大小写要求；普通文本和正则使用不同长度上限。
class TextSearch(Contract):
    match: Literal['phrase', 'all_terms', 'any_terms', 'regex']
    value: Annotated[Text, Field(max_length=500)]
    case_sensitive: bool = False

    # 正则单独限制为 200 字符；表达式语法是否受支持由执行层检查。
    @model_validator(mode='after')
    def regex_limit(self):
        if self.match == 'regex' and len(self.value) > 200:
            raise ValueError('regex length exceeds 200')
        return self


# 记录筛选保留原始期间、维度、单位与状态，不把解析失败事实自动删去。
class RecordFilters(Contract):
    periods: tuple[dict[str, str], ...] = ()
    dimensions: dict[str, str] | None = None
    units: tuple[dict[str, list[str]], ...] = ()
    entity_scope: Literal['consolidated', 'segment'] | None = None
    statuses: tuple[Literal['parsed', 'nil', 'unsupported', 'invalid'], ...] = ()

    # 复用期间、单位和维度校验，保证精确匹配条件本身有清晰语义。
    @model_validator(mode='after')
    def exact_values(self):
        for period in self.periods:
            validate_period(period)
        for unit in self.units:
            validate_unit(unit)
        validate_dimensions(self.dimensions)
        return self


# 按明确 concept_id 查询事实，可附角色、维度和期间限制；不在契约层做概念猜测。
class ConceptSearch(Contract):
    concept_id: Text = Field(description='Exact expanded {namespace}local-name from get_asset_schema facets=["concepts"]; do not invent a prefix or namespace.')
    roles: tuple[Text, ...] = ()
    dimensions: dict[str, str] | None = None
    periods: tuple[dict[str, str], ...] = ()

    # 检查期间和维度形状，避免不完整筛选条件被当作精确来源条件。
    @model_validator(mode='after')
    def exact_values(self):
        for period in self.periods:
            validate_period(period)
        validate_dimensions(self.dimensions)
        return self


# 将搜索范围限定到指定章节、块类型和文本来源，空元组表示未增加该项限制。
class SearchScope(Contract):
    section_ids: tuple[Text, ...] = ()
    block_kinds: tuple[Literal['paragraph', 'heading', 'list_item', 'table', 'other'], ...] = ()
    text_origins: tuple[Literal['text_layer', 'table', 'caption', 'ocr'], ...] = ()


# 在一个明确构建内选择目录、文本或概念搜索；数量和字节预算同时限制返回规模。
class SearchAsset(Contract):
    asset_ref: ReadableAssetRef
    mode: Literal['outline', 'text', 'concept', 'passages']
    outline: Outline | None = None
    passage_scope: Literal['direct', 'subtree'] = Field(default='direct',
        description='For passages only: direct lists this node; subtree includes descendants without renumbering their groups.')
    text: TextSearch | None = None
    concept: ConceptSearch | None = None
    scope: SearchScope = SearchScope()
    include: tuple[Literal['snippet', 'section_title', 'table_header', 'units'], ...] = Field(default=('snippet',),
        description='Start with snippet-only discovery. table_header/units can attach a large indivisible context bundle for an entire table. After locating hits, prefer read_evidence with specific table rows/cells and required context. Requested dependencies are never silently dropped to fit a page.')
    limit: Annotated[int, Field(ge=1, le=20)] = 8
    max_bytes: Annotated[int, Field(ge=2000, le=200000,
        description='UTF-8 budget for the complete response, including context dependencies. Default 24000. Follow next_cursor; budget may change between pages. ITEM_TOO_LARGE retains the position: increase the budget or start a narrower query/read the indicated target.')] = 24000
    cursor: Text | None = None

    # 旧请求未显式传 max_bytes 时继续省略该字段，保持持久化请求和游标身份兼容。
    @model_serializer(mode='wrap')
    def preserve_legacy_request(self, handler):
        value = handler(self)
        # Old persisted requests/cursors did not contain max_bytes. Keep their
        # identity so exact replay returns the original response and references.
        if 'max_bytes' not in self.model_fields_set:
            value.pop('max_bytes', None)
        if 'passage_scope' not in self.model_fields_set:
            value.pop('passage_scope', None)
        return value

    # 三类参数必须与 mode 一一对应，禁止混传参数后由执行层猜测用户意图。
    @model_validator(mode='after')
    def matching_mode(self):
        if self.mode != 'passages' and self.passage_scope != 'direct':
            raise ValueError('passage_scope applies only to passages')
        selected = 'outline' if self.mode == 'passages' else self.mode
        if any((getattr(self, name) is not None) != (selected == name) for name in ('outline', 'text', 'concept')):
            raise ValueError('search mode and parameters differ')
        if self.mode == 'passages' and not isinstance(self.asset_ref, DocumentRef):
            raise ValueError('passages requires a document_parse reference')
        return self


# 读取某块全部文本或指定字符范围；字符边界是否有效由证据读取逻辑检查。
class BlockTarget(Contract):
    block_id: Text
    char_range: tuple[Annotated[int, Field(ge=0)], Annotated[int, Field(ge=0)]] | None = None


# 用表格 ID 和行列选择器缩小读取范围，避免为少量单元格返回整张大表。
class TableTarget(Contract):
    table_id: Text
    rows: tuple[Annotated[int, Field(ge=0)], ...] = ()
    cols: tuple[Annotated[int, Field(ge=0)], ...] = ()


# 按本构建内的记录 ID 读取单个事实及其来源。
class RecordTarget(Contract):
    record_id: Text


# 使用已知 HTML 定位直接读取原文，同时沿用投影、字符范围和摘要校验。
class LocatorTarget(Contract):
    locator: HtmlLocator


# 声明图片及可选区域的读取目标；字段存在不代表底层已经具备图像能力。
class ImageTarget(Contract):
    image_id: Text
    region: tuple[int, int, int, int] | None = None


# 控制证据附近块的前后展开量，每侧最多五个，避免上下文无界增长。
class Neighbors(Contract):
    before: Annotated[int, Field(ge=0, le=5)] = 1
    after: Annotated[int, Field(ge=0, le=5)] = 1


# 批量读取明确目标并按需附带表头、单位、脚注等上下文，受完整响应字节预算约束。
class ReadEvidence(Contract):
    asset_ref: ReadableAssetRef
    targets: Annotated[tuple[BlockTarget | TableTarget | RecordTarget | LocatorTarget | ImageTarget | SectionTarget | PassageTarget, ...], Field(min_length=1, max_length=16)]
    context: tuple[Literal['section_title', 'table_headers', 'units', 'footnotes', 'neighbors', 'continuation'], ...] = ()
    neighbors: Neighbors = Neighbors()
    table_representation: Literal['compact', 'full'] = 'full'
    include_image: bool = False
    max_bytes: Annotated[int, Field(ge=2000, le=200000)] = 24000
    cursor: Text | None = None

    @model_validator(mode='after')
    def document_targets(self):
        if not isinstance(self.asset_ref, DocumentRef) and any(
                isinstance(target, (SectionTarget, PassageTarget)) for target in self.targets):
            raise ValueError('section_path and passage_path require a document_parse reference')
        return self


# 声明要读取的概念与返回字段；允许字段名单由记录执行器进一步检查。
RECORD_FIELDS = ('record_id','concept_id','value','raw_value','status','period','unit','dimensions','entity_identifier',
    'entity_scheme','context_ref','decimals','scale','sign','duplicate_group','issues','locator','source_object','source_url',
    'context_source','unit_source','asset_ref','result_ref')


class RecordSelect(Contract):
    concepts: tuple[Text, ...] = Field(default=(), description='Exact expanded {namespace}local-name identifiers from get_asset_schema facets=["concepts"]. Prefix:local-name is invalid. Empty means no concept filter.')
    fields: tuple[Text, ...] = Field(default=(), description='Optional requested record fields: '+', '.join(RECORD_FIELDS)+'. Empty is allowed. Period is a nested object; mandatory source/provenance fields remain present.')

    def validate_fields(self):
        unknown=sorted(set(self.fields)-set(RECORD_FIELDS))
        if unknown:
            from .common import CatalogError
            raise CatalogError('INVALID_REQUEST',f'select.fields contains unknown fields {unknown}; supported fields: {list(RECORD_FIELDS)}')


# 计算操作数的精确选择器；至少指定记录 ID 或概念，并可进一步限定来源口径。
class RecordSelector(Contract):
    record_id: Text | None = None
    concept_id: Text | None = Field(default=None, description='Exact expanded {namespace}local-name returned by the source schema, not prefix:local-name. Prefer an observed record_id for a specific occurrence.')
    period: dict[str, str] | None = None
    dimensions: dict[str, str] | None = None
    unit: dict[str, list[str]] | None = None

    # 校验选择器形状；是否恰好命中一条来源记录由执行阶段决定。
    @model_validator(mode='after')
    def input(self):
        if self.record_id is None and self.concept_id is None:
            raise ValueError('record ID or expanded concept required')
        if self.period is not None:
            validate_period(self.period)
        if self.unit is not None:
            validate_unit(self.unit)
        validate_dimensions(self.dimensions)
        return self


# 每个操作数都绑定完整资产版本和选择器，允许跨构建计算同时保持来源可追踪。
class Operand(Contract):
    asset_ref: ReadableAssetRef
    record_selector: RecordSelector


# 显式计算规格，保留操作顺序、输出单位、期间策略与业务比较依据。
class Calculation(Contract):
    calc_id: Text
    op: Literal['difference', 'ratio', 'growth', 'sum']
    operands: Annotated[tuple[Operand, ...], Field(min_length=2, max_length=50)]
    output_unit: dict[str, list[str]] | Literal['ratio']
    period_policy: Literal['same', 'distinct_nonoverlapping']
    comparison_basis: Text

    # 除求和外都要求两个操作数；这里只校验输入形状，实际可比性仍由计算器检查。
    @model_validator(mode='after')
    def arity(self):
        if self.op != 'sum' and len(self.operands) != 2:
            raise ValueError('binary calculation needs two operands')
        if isinstance(self.output_unit,dict):
            validate_unit(self.output_unit)
        return self


# 仅允许受支持字段和方向排序，避免把任意 SQL 片段传给索引层。
class RecordOrder(Contract):
    field: Literal['record_id', 'concept_id', 'period_end'] = 'record_id'
    direction: Literal['asc', 'desc'] = 'asc'


# 在指定构建上查询记录，可附少量显式计算；主记录和计算依赖共享数量与字节预算。
class QueryRecords(Contract):
    asset_ref: ReadableAssetRef
    select: RecordSelect
    filters: RecordFilters = RecordFilters()
    calculations: Annotated[tuple[Calculation, ...], Field(max_length=8)] = ()
    order_by: RecordOrder = RecordOrder()
    limit: Annotated[int, Field(ge=1, le=200)] = 50
    max_bytes: Annotated[int, Field(ge=2000, le=200000)] = 24000
    cursor: Text | None = None
    document_records: Annotated[tuple[DocumentRecordInput, ...], Field(max_length=20)] = ()

    @model_serializer(mode='wrap')
    def preserve_legacy_record_requests(self, handler):
        value = handler(self)
        if 'document_records' not in self.model_fields_set:
            value.pop('document_records', None)
        return value

    # 同一请求的计算 ID 必须唯一，保证结果引用能明确对应某一计算。
    @model_validator(mode='after')
    def unique_calcs(self):
        if self.document_records and not isinstance(self.asset_ref, DocumentRef):
            raise ValueError('document_records requires a document_parse reference')
        if len({r.record_id for r in self.document_records}) != len(self.document_records):
            raise ValueError('duplicate document record IDs')
        if len({c.calc_id for c in self.calculations}) != len(self.calculations):
            raise ValueError('duplicate calculation IDs')
        return self


# 请求为已有构建准备指定能力与目标，实际可支持范围由处理入口核验。
class ProcessUpdate(Contract):
    asset_ref: AssetRef
    capabilities: Annotated[tuple[Literal['text_search', 'records', 'concepts', 'tables', 'ocr', 'vision'], ...], Field(min_length=1)]
    targets: tuple[Text, ...] = ()


# 采集意图包含明确公司、材料类型、期间与来源线索，不隐式选择样本公司或日期。
class AcquireUpdate(Contract):
    company_id: CompanyId
    material_types: tuple[Text, ...]
    periods: tuple[FiscalPeriod, ...]
    source_hints: tuple[dict[str, str], ...]


# 把补处理或补采集操作绑定到业务 need_id，并要求说明本次更新原因。
class RequestAssetUpdate(Contract):
    need_id: Text
    action: Literal['process', 'acquire']
    process: ProcessUpdate | None = None
    acquire: AcquireUpdate | None = None
    reason: Text

    # process 与 acquire 参数严格互斥，且必须与 action 一致。
    @model_validator(mode='after')
    def action_params(self):
        if (self.process is not None) != (self.action == 'process') or (self.acquire is not None) != (self.action == 'acquire'):
            raise ValueError('update action and parameters differ')
        return self


# 工具名到请求契约的唯一映射；调用入口据此校验形状，执行职责仍在应用层。
TOOLS = dict(find_assets=FindAssets, get_asset_schema=GetAssetSchema, search_asset=SearchAsset,
             read_evidence=ReadEvidence, query_records=QueryRecords, request_asset_update=RequestAssetUpdate)
