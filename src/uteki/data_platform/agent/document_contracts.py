"""Model-facing projection of the supported document backend, shared by both SDKs.

The service contracts remain canonical. Omitted unsupported fields receive only
their existing service defaults; supplied unsupported fields are rejected.
"""
from typing import Annotated, Literal

from pydantic import Field, create_model

from ..contracts.common import Contract, Text, project
from ..contracts.document_query import DocumentRef, PassageTarget, SectionTarget, DocumentRecordInput
from ..contracts.query import (
    AssetFilters, FindAssets, GetAssetSchema, Outline, TextSearch, SearchScope,
    ReadEvidence, BlockTarget, TableTarget, QueryRecords, Calculation, Operand,
)
from ..contracts.run import TaskState


DocumentFilters = project('DocumentFilters', AssetFilters,
    ('company_ids', 'company_names', 'securities', 'asset_kinds', 'material_types', 'formats', 'reporting_periods'))
DocumentFind = project('DocumentFind', FindAssets, ('query', 'as_of', 'limit', 'cursor'),
    filters=(DocumentFilters | None, None))
DocumentSchema = project('DocumentSchema', GetAssetSchema, ('outline', 'limit', 'cursor'),
    asset_ref=(DocumentRef, ...),
    facets=(tuple[Literal['overview', 'outline', 'fields', 'coverage', 'readiness', 'capabilities'], ...],
            ('overview', 'outline', 'readiness', 'capabilities')))
DocumentText = project('DocumentText', TextSearch, ('value',),
    match=(Literal['phrase'], 'phrase'), case_sensitive=(Literal[False], False))
DocumentSearchScope = project('DocumentSearchScope', SearchScope, (),
    section_ids=(Annotated[tuple[Text, ...], Field(max_length=1)], ()),
    block_kinds=(tuple[Literal['table'], ...], ()), text_origins=(tuple[Literal['table'], ...], ()))


class PassageOutline(Contract):
    section_id: Text = Field(description='Exact returned node ID or code_path. Passage scope is controlled by passage_scope, not outline depth.')


class SearchBase(Contract):
    asset_ref: DocumentRef
    limit: Annotated[int, Field(ge=1, le=20)] = 8
    max_bytes: Annotated[int, Field(ge=2000, le=200000)] = 24000
    cursor: Text | None = None


class OutlineSearch(SearchBase):
    mode: Literal['outline']
    outline: Outline


class PassageSearch(SearchBase):
    mode: Literal['passages']
    outline: PassageOutline
    passage_scope: Literal['direct', 'subtree'] = 'direct'


class TextSearchRequest(SearchBase):
    mode: Literal['text']
    text: DocumentText
    scope: DocumentSearchScope = DocumentSearchScope()
    include: tuple[Literal['snippet', 'section_title'], ...] = ('snippet', 'section_title')


DocumentRead = project('DocumentRead', ReadEvidence,
    ('context', 'neighbors', 'max_bytes', 'cursor'), asset_ref=(DocumentRef, ...),
    targets=(Annotated[tuple[BlockTarget | TableTarget | SectionTarget | PassageTarget, ...],
                       Field(min_length=1, max_length=16)], ...),
    table_representation=(Literal['full'], 'full'), include_image=(Literal[False], False))


class EmptySelection(Contract):
    """PDF records have no XBRL concepts or field projection."""


class DocumentRecordSelector(Contract):
    record_id: Text


DocumentOperand = project('DocumentOperand', Operand, (),
    asset_ref=(DocumentRef, ...), record_selector=(DocumentRecordSelector, ...))
DocumentCalculation = project('DocumentCalculation', Calculation,
    ('calc_id', 'op', 'output_unit', 'period_policy', 'comparison_basis'),
    operands=(Annotated[tuple[DocumentOperand, ...], Field(min_length=2, max_length=50)], ...))
DocumentRecords = project('DocumentRecords', QueryRecords, ('limit', 'max_bytes'),
    max_bytes=(Annotated[int, Field(ge=2000, le=200000)], 200000),
    asset_ref=(DocumentRef, ...), select=(EmptySelection, EmptySelection()),
    document_records=(Annotated[tuple[DocumentRecordInput, ...], Field(max_length=20)], ()),
    calculations=(Annotated[tuple[DocumentCalculation, ...], Field(max_length=8)], ()))


def document_envelopes(shared):
    requests = dict(find_assets=DocumentFind, get_asset_schema=DocumentSchema,
        search_asset=OutlineSearch | PassageSearch | TextSearchRequest,
        read_evidence=DocumentRead, query_records=DocumentRecords)
    result = {name: create_model('Document'+name.title().replace('_', '')+'Call', __base__=Contract,
        request=(request, ...), state=(TaskState, ...)) for name, request in requests.items()}
    result['deliver'] = shared['deliver']
    result['clarify'] = shared['clarify']
    return result
