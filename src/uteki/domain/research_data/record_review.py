"""Independent source-grounded opinions; never mutations of candidate facts."""
from typing import Literal
from pydantic import Field, model_validator
from .query_contract import Contract

Verdict = Literal['supported', 'contradicted', 'insufficient_evidence']


class FieldChecks(Contract):
    metric: Verdict
    period: Verdict
    value_unit_scale_sign: Verdict
    entity_dimensions: Verdict
    qualifiers: Verdict


class ReviewCitation(Contract):
    source_snapshot_id: str
    block_id: str
    quote: str = Field(min_length=1, max_length=2000)


class RecordAssessment(Contract):
    record_id: str
    verdict: Verdict
    checks: FieldChecks
    reason: str = Field(min_length=1, max_length=4000)
    citations: tuple[ReviewCitation, ...] = Field(default=(), max_length=8)
    limitations: tuple[str, ...] = Field(default=(), max_length=12)

    @model_validator(mode='after')
    def consistent_verdict(self):
        values = self.checks.model_dump().values()
        expected = ('contradicted' if 'contradicted' in values else
                    'insufficient_evidence' if 'insufficient_evidence' in values else 'supported')
        if self.verdict != expected:
            raise ValueError('overall verdict disagrees with field checks')
        if self.verdict != 'insufficient_evidence' and not self.citations:
            raise ValueError('supported or contradicted review needs source citations')
        return self


class BatchAssessment(Contract):
    packet_id: str
    records: tuple[RecordAssessment, ...] = Field(min_length=1, max_length=24)
    source_limitations: tuple[str, ...] = Field(default=(), max_length=30)
