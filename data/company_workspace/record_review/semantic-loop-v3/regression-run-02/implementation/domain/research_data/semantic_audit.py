"""Independent critique opinions, bound to one normalized semantic assessment."""
from typing import Literal

from pydantic import Field, model_validator

from .query_contract import Contract
from .semantic_review import SemanticCitationV2


class SemanticAuditIssue(Contract):
    issue_id: str = Field(min_length=1, max_length=200, pattern=r'^\S+$')
    kind: Literal['unsupported_claim', 'omission', 'record_scope', 'context_conflict']
    severity: Literal['error', 'suggestion'] = 'error'
    location: str = Field(min_length=1, max_length=512,
                          pattern=r'^[A-Za-z_][A-Za-z_0-9]*(?:\.(?:[A-Za-z_][A-Za-z_0-9]*|0|[1-9][0-9]*))*$')
    record_ids: tuple[str, ...] = Field(default=(), max_length=24)
    explanation: str = Field(min_length=1, max_length=6000, pattern=r'\S')
    citations: tuple[SemanticCitationV2, ...] = Field(default=(), max_length=12)

    @model_validator(mode='after')
    def unique_records(self):
        if len(set(self.record_ids)) != len(self.record_ids):
            raise ValueError('audit issue record IDs must be unique')
        return self


class SemanticAuditResult(Contract):
    packet_id: str = Field(min_length=1)
    assessment_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    status: Literal['pass', 'revise']
    issues: tuple[SemanticAuditIssue, ...] = Field(default=(), max_length=48)

    @model_validator(mode='after')
    def consistent_status(self):
        if (self.status == 'pass') != (not any(issue.severity == 'error' for issue in self.issues)):
            raise ValueError('audit passes if and only if there are no error-severity issues')
        if len({issue.issue_id for issue in self.issues}) != len(self.issues):
            raise ValueError('audit issue IDs must be unique')
        return self
