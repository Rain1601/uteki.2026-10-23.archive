"""Strict requests for the deterministic, version-bound data tools."""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .assets import AssetRef, CompanyId, SourceId
from .common import Contract, FiscalPeriod, Text, canonical
from .evidence import HtmlLocator


def parse(model, value):
    """JSON is the common boundary for Python callers and future SDK adapters."""
    if isinstance(value, model):
        return model.model_validate(value)
    return model.model_validate_json(canonical(value))


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


def validate_unit(unit):
    if set(unit) not in ({'measures'},{'numerator','denominator'}):
        raise ValueError('unit requires measures or numerator/denominator')
    if any(not values or any(not value.strip() for value in values) for values in unit.values()):
        raise ValueError('unit must contain nonempty source measures')


def validate_dimensions(dimensions):
    if dimensions is not None and any(not key.strip() or not value.strip() for key,value in dimensions.items()):
        raise ValueError('dimension names and members cannot be empty')


class ReadPolicy(Contract):
    schema_version: Literal['uteki-read-policy-v1']
    source_kinds: tuple[Literal['sec_edgar', 'sec_xbrl_api', 'official_site', 'user_file'], ...]
    source_ids: tuple[SourceId, ...] = ()

    @model_validator(mode='after')
    def nonempty(self):
        if not self.source_kinds:
            raise ValueError('explicit allowed source kinds required')
        return self


class Security(Contract):
    ticker: Text
    exchange_mic: Text


class Entities(Contract):
    company_ids: tuple[CompanyId, ...] = ()
    company_names: tuple[Text, ...] = ()
    securities: tuple[Security, ...] = ()

    @model_validator(mode='after')
    def nonempty(self):
        if not (self.company_ids or self.company_names or self.securities):
            raise ValueError('explicit registered entities required')
        return self


class Expansion(Contract):
    mode: Literal['disabled', 'controlled']
    allow: tuple[Text, ...]
    deny: tuple[Text, ...]

    @model_validator(mode='after')
    def explicit_allow(self):
        if self.mode == 'controlled' and not self.allow:
            raise ValueError('controlled expansion requires explicit allow rules')
        return self


class RunPolicy(Contract):
    max_usd: Annotated[str, Field(pattern=r'^(0|[1-9]\d*)(\.\d+)?$')]
    max_turns: Annotated[int, Field(ge=1, le=1000)]
    max_wall_seconds: Annotated[int, Field(ge=1, le=3600)]
    max_no_progress_turns: Annotated[int, Field(ge=1, le=1000)]


class Caller(Contract):
    kind: Literal['user', 'analysis_agent']
    prior_delivery_refs: tuple[Text, ...] = ()


class ContextRequest(Contract):
    question: Text
    caller: Caller
    entities: Entities
    periods: tuple[FiscalPeriod, ...] = ()
    as_of: datetime | None = None
    source_policy_ref: Text
    expansion: Expansion
    run_policy: RunPolicy

    @model_validator(mode='after')
    def timezone(self):
        if self.as_of is not None and self.as_of.tzinfo is None:
            raise ValueError('as_of requires a timezone')
        return self


class DateRange(Contract):
    gte: datetime | None = None
    lt: datetime | None = None

    @model_validator(mode='after')
    def interval(self):
        if self.gte is None and self.lt is None:
            raise ValueError('at least one time bound required')
        if any(v is not None and v.tzinfo is None for v in (self.gte, self.lt)):
            raise ValueError('time bounds require timezones')
        if self.gte and self.lt and self.gte >= self.lt:
            raise ValueError('reversed time interval')
        return self


class AssetFilters(Contract):
    company_ids: tuple[CompanyId, ...] = ()
    company_names: tuple[Text, ...] = ()
    securities: tuple[Security, ...] = ()
    roles: tuple[Literal['issuer', 'subject', 'mentioned'], ...] = ('issuer', 'subject')
    asset_kinds: tuple[Literal['document', 'dataset'], ...] = ()
    material_types: tuple[Text, ...] = ()
    formats: tuple[Literal['html', 'pdf', 'xbrl_instance', 'api_json'], ...] = ()
    reporting_periods: tuple[Text, ...] = ()
    content_periods: tuple[Text, ...] = ()
    published_at: DateRange | None = None


class FindAssets(Contract):
    query: Annotated[str, Field(max_length=500)] | None = None
    filters: AssetFilters | None = None
    as_of: datetime | None = None
    limit: Annotated[int, Field(ge=1, le=50)] = 10
    cursor: Text | None = None

    @model_validator(mode='after')
    def input(self):
        if not (self.query and self.query.strip()) and self.filters is None:
            raise ValueError('query or filters required')
        if self.as_of is not None and self.as_of.tzinfo is None:
            raise ValueError('as_of requires a timezone')
        return self


class Outline(Contract):
    section_id: Text | None = None
    depth: Annotated[int, Field(ge=1, le=3)] = 1


class GetAssetSchema(Contract):
    asset_ref: AssetRef
    facets: tuple[Literal['overview', 'outline', 'fields', 'concepts', 'coverage', 'readiness', 'capabilities'], ...] = ('overview', 'outline', 'readiness', 'capabilities')
    outline: Outline | None = None
    limit: Annotated[int, Field(ge=1, le=40)] = 40
    cursor: Text | None = None


class TextSearch(Contract):
    match: Literal['phrase', 'all_terms', 'any_terms', 'regex']
    value: Annotated[Text, Field(max_length=500)]
    case_sensitive: bool = False

    @model_validator(mode='after')
    def regex_limit(self):
        if self.match == 'regex' and len(self.value) > 200:
            raise ValueError('regex length exceeds 200')
        return self


class RecordFilters(Contract):
    periods: tuple[dict[str, str], ...] = ()
    dimensions: dict[str, str] | None = None
    units: tuple[dict[str, list[str]], ...] = ()
    entity_scope: Literal['consolidated', 'segment'] | None = None
    statuses: tuple[Literal['parsed', 'nil', 'unsupported', 'invalid'], ...] = ()

    @model_validator(mode='after')
    def exact_values(self):
        for period in self.periods:
            validate_period(period)
        for unit in self.units:
            validate_unit(unit)
        validate_dimensions(self.dimensions)
        return self


class ConceptSearch(Contract):
    concept_id: Text
    roles: tuple[Text, ...] = ()
    dimensions: dict[str, str] | None = None
    periods: tuple[dict[str, str], ...] = ()

    @model_validator(mode='after')
    def exact_values(self):
        for period in self.periods:
            validate_period(period)
        validate_dimensions(self.dimensions)
        return self


class SearchScope(Contract):
    section_ids: tuple[Text, ...] = ()
    block_kinds: tuple[Literal['paragraph', 'heading', 'list_item', 'table', 'other'], ...] = ()
    text_origins: tuple[Literal['text_layer', 'table', 'caption', 'ocr'], ...] = ()


class SearchAsset(Contract):
    asset_ref: AssetRef
    mode: Literal['outline', 'text', 'concept']
    outline: Outline | None = None
    text: TextSearch | None = None
    concept: ConceptSearch | None = None
    scope: SearchScope = SearchScope()
    include: tuple[Literal['snippet', 'section_title', 'table_header', 'units'], ...] = ('snippet',)
    limit: Annotated[int, Field(ge=1, le=20)] = 8
    cursor: Text | None = None

    @model_validator(mode='after')
    def matching_mode(self):
        if any((getattr(self, name) is not None) != (self.mode == name) for name in ('outline', 'text', 'concept')):
            raise ValueError('search mode and parameters differ')
        return self


class BlockTarget(Contract):
    block_id: Text
    char_range: tuple[Annotated[int, Field(ge=0)], Annotated[int, Field(ge=0)]] | None = None


class TableTarget(Contract):
    table_id: Text
    rows: tuple[Annotated[int, Field(ge=0)], ...] = ()
    cols: tuple[Annotated[int, Field(ge=0)], ...] = ()


class RecordTarget(Contract):
    record_id: Text


class LocatorTarget(Contract):
    locator: HtmlLocator


class ImageTarget(Contract):
    image_id: Text
    region: tuple[int, int, int, int] | None = None


class Neighbors(Contract):
    before: Annotated[int, Field(ge=0, le=5)] = 1
    after: Annotated[int, Field(ge=0, le=5)] = 1


class ReadEvidence(Contract):
    asset_ref: AssetRef
    targets: Annotated[tuple[BlockTarget | TableTarget | RecordTarget | LocatorTarget | ImageTarget, ...], Field(min_length=1, max_length=16)]
    context: tuple[Literal['section_title', 'table_headers', 'units', 'footnotes', 'neighbors', 'continuation'], ...] = ()
    neighbors: Neighbors = Neighbors()
    table_representation: Literal['compact', 'full'] = 'full'
    include_image: bool = False
    max_bytes: Annotated[int, Field(ge=2000, le=200000)] = 24000
    cursor: Text | None = None


class RecordSelect(Contract):
    concepts: tuple[Text, ...] = ()
    fields: tuple[Text, ...] = ()


class RecordSelector(Contract):
    record_id: Text | None = None
    concept_id: Text | None = None
    period: dict[str, str] | None = None
    dimensions: dict[str, str] | None = None
    unit: dict[str, list[str]] | None = None

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


class Operand(Contract):
    asset_ref: AssetRef
    record_selector: RecordSelector


class Calculation(Contract):
    calc_id: Text
    op: Literal['difference', 'ratio', 'growth', 'sum']
    operands: Annotated[tuple[Operand, ...], Field(min_length=2, max_length=50)]
    output_unit: dict[str, list[str]] | Literal['ratio']
    period_policy: Literal['same', 'distinct_nonoverlapping']
    comparison_basis: Text

    @model_validator(mode='after')
    def arity(self):
        if self.op != 'sum' and len(self.operands) != 2:
            raise ValueError('binary calculation needs two operands')
        if isinstance(self.output_unit,dict):
            validate_unit(self.output_unit)
        return self


class RecordOrder(Contract):
    field: Literal['record_id', 'concept_id', 'period_end'] = 'record_id'
    direction: Literal['asc', 'desc'] = 'asc'


class QueryRecords(Contract):
    asset_ref: AssetRef
    select: RecordSelect
    filters: RecordFilters = RecordFilters()
    calculations: Annotated[tuple[Calculation, ...], Field(max_length=8)] = ()
    order_by: RecordOrder = RecordOrder()
    limit: Annotated[int, Field(ge=1, le=200)] = 50
    max_bytes: Annotated[int, Field(ge=2000, le=200000)] = 24000
    cursor: Text | None = None

    @model_validator(mode='after')
    def unique_calcs(self):
        if len({c.calc_id for c in self.calculations}) != len(self.calculations):
            raise ValueError('duplicate calculation IDs')
        return self


class ProcessUpdate(Contract):
    asset_ref: AssetRef
    capabilities: Annotated[tuple[Literal['text_search', 'records', 'concepts', 'tables', 'ocr', 'vision'], ...], Field(min_length=1)]
    targets: tuple[Text, ...] = ()


class AcquireUpdate(Contract):
    company_id: CompanyId
    material_types: tuple[Text, ...]
    periods: tuple[FiscalPeriod, ...]
    source_hints: tuple[dict[str, str], ...]


class RequestAssetUpdate(Contract):
    need_id: Text
    action: Literal['process', 'acquire']
    process: ProcessUpdate | None = None
    acquire: AcquireUpdate | None = None
    reason: Text

    @model_validator(mode='after')
    def action_params(self):
        if (self.process is not None) != (self.action == 'process') or (self.acquire is not None) != (self.action == 'acquire'):
            raise ValueError('update action and parameters differ')
        return self


TOOLS = dict(find_assets=FindAssets, get_asset_schema=GetAssetSchema, search_asset=SearchAsset,
             read_evidence=ReadEvidence, query_records=QueryRecords, request_asset_update=RequestAssetUpdate)
