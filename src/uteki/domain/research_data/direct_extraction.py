"""Candidate drafts from source text; normalization and adoption are separate."""
from typing import Literal
from pydantic import Field
from .query_contract import Contract


class DraftEvidence(Contract):
    block_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    occurrence_id: str | None = None


class DraftRecord(Contract):
    draft_id: str = Field(min_length=1)
    kind: Literal['financial', 'guidance', 'statement']
    entity: str = Field(min_length=1)
    entity_id: str | None = None
    metric: str = Field(min_length=1)
    metric_id: str | None = None
    period: str | None = None
    period_id: str | None = None
    value: str | None = None
    upper: str | None = None
    value_relation: Literal['eq', 'range', 'approx', 'gt', 'gte', 'qualitative', 'unresolved']
    unit: str | None = None
    denominator: str | None = None
    accounting_basis: str | None = None
    summary: str
    speaker: str | None = None
    evidence: list[DraftEvidence] = Field(default_factory=list)
    qualifiers: list[DraftEvidence] = Field(default_factory=list)
    question_refs: list[str] = Field(default_factory=list, description=(
        'Only source block IDs of analyst questions, when applicable. Never put task IDs, '
        'requirement IDs or record IDs here. Use [] for a financial statement without analyst questions.'))
    unresolved_fields: list[str] = Field(default_factory=list)


class DraftRelation(Contract):
    relation_id: str = Field(min_length=1)
    relation_type: str = Field(min_length=1)
    record_ids: list[str] = Field(min_length=1)
    description: str
    evidence: list[DraftEvidence] = Field(default_factory=list)


class DirectExtraction(Contract):
    records: list[DraftRecord] = Field(default_factory=list)
    relations: list[DraftRelation] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
