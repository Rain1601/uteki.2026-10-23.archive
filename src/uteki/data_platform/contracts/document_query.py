"""Explicit document-version bindings for the shared query tools.

These are caller-selected materials, not inferred company or financial facts.
The package fingerprint binds the SQL projection to an immutable parse.
"""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .assets import CompanyId, SourceId
from .common import Contract, Text
from .content import ObjectRef
from .run import ResultRef, SourceQuote


class DocumentRef(Contract):
    kind: Literal['document_parse']
    material_id: Text
    source_version_id: Text
    parse_id: Text
    package_ref: ObjectRef


class DocumentBinding(Contract):
    asset_ref: DocumentRef
    company_id: CompanyId
    source_id: SourceId
    selection_basis: Text = Field(description='Explicit caller selection; not proof of financial entity scope.')


class DocumentScope(Contract):
    data_root: Text
    bindings: Annotated[tuple[DocumentBinding, ...], Field(min_length=1, max_length=100)]

    @model_validator(mode='after')
    def unique(self):
        keys = [b.asset_ref.parse_id for b in self.bindings]
        if len(set(keys)) != len(keys):
            raise ValueError('duplicate document parse binding')
        return self


class SectionTarget(Contract):
    section_path: Text = Field(description='Exact native code_path returned by schema. By default reads only content directly assigned to this node, not child sections.')
    include_descendants: bool = Field(default=False, description='True reads the entire subtree; false reads only this node. For a single section target, follow next_cursor with this same target to read all pages; do not construct child paths. Parent introductions do not include child sections.')


class PassageTarget(Contract):
    passage_path: Text = Field(description='Exact native code_path followed by .passages[index], in this parse version.')


class RecordSupport(Contract):
    metric: Annotated[tuple[SourceQuote, ...], Field(min_length=1, max_length=4)]
    period: Annotated[tuple[SourceQuote, ...], Field(min_length=1, max_length=4)]
    unit: Annotated[tuple[SourceQuote, ...], Field(min_length=1, max_length=4)]
    entity: Annotated[tuple[SourceQuote, ...], Field(min_length=1, max_length=4)]
    scope: Annotated[tuple[SourceQuote, ...], Field(min_length=1, max_length=4)]


class DocumentRecordInput(Contract):
    record_id: Text
    value_evidence: ResultRef = Field(description='Previously observed exact numeric cell or character-range evidence.')
    raw_value: Text = Field(description='Must equal that evidence text. Code parses it; do not supply a computed value.')
    metric: Text
    period_label: Text
    fiscal_year: Annotated[int, Field(ge=1800, le=2500)]
    period_kind: Literal['annual', 'quarter', 'instant', 'other']
    unit: Text = Field(description='Unambiguous unit/currency label literally present in support.unit quotes. Copy the original full name if the source has no ISO code; do not infer USD or another currency from an ambiguous symbol. Keep the decimal multiplier in scale.')
    scale: Annotated[int, Field(ge=-12, le=12)] = Field(description='Base-10 exponent; e.g. 6 for source amounts in millions. Preserve source scale evidence.')
    entity: Text
    entity_scope: Text
    support: RecordSupport
    interpretation: Text = Field(description='Explain how quoted source text establishes metric, period, unit and scope; this is a model interpretation, not independently verified metadata.')
