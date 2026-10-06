"""Evidence-bearing semantic constraints, kept separate from numeric acceptance."""
from typing import Literal

from pydantic import Field, model_validator

from .query_contract import Contract
from .record_review import ReviewCitation, Verdict

SemanticAxis = Literal['comparability', 'allocation', 'additivity', 'dimensions', 'geography', 'value']


class ReviewAssertion(Contract):
    assertion_id: str = Field(min_length=1)
    record_ids: tuple[str, ...] = Field(min_length=1, max_length=24)
    text: str = Field(min_length=1, max_length=4000)


class SemanticConstraint(Contract):
    record_ids: tuple[str, ...] = Field(min_length=1, max_length=24)
    statement: str = Field(min_length=1, max_length=4000)
    citations: tuple[ReviewCitation, ...] = Field(min_length=1, max_length=8)


class AxisCheck(Contract):
    axis: SemanticAxis
    status: Literal['constraints_found', 'none_found_in_context', 'insufficient_evidence']
    reason: str = Field(min_length=1, max_length=4000)
    constraints: tuple[SemanticConstraint, ...] = Field(default=(), max_length=24)
    unresolved_questions: tuple[str, ...] = Field(default=(), max_length=12)

    @model_validator(mode='after')
    def consistent_status(self):
        if self.status == 'constraints_found' and not self.constraints:
            raise ValueError('constraints_found requires cited constraints')
        if self.status == 'none_found_in_context' and self.constraints:
            raise ValueError('none_found_in_context cannot contain constraints')
        if self.status == 'insufficient_evidence' and not self.unresolved_questions:
            raise ValueError('insufficient_evidence requires concrete unresolved questions')
        return self


class AssertionAssessment(Contract):
    assertion_id: str = Field(min_length=1)
    verdict: Verdict
    reason: str = Field(min_length=1, max_length=4000)
    citations: tuple[ReviewCitation, ...] = Field(default=(), max_length=8)

    @model_validator(mode='after')
    def needs_evidence(self):
        if self.verdict != 'insufficient_evidence' and not self.citations:
            raise ValueError('supported or contradicted assertion needs source citations')
        return self


class SemanticAssessment(Contract):
    packet_id: str = Field(min_length=1)
    checks: tuple[AxisCheck, ...] = Field(min_length=1, max_length=6)
    assertions: tuple[AssertionAssessment, ...] = Field(default=(), max_length=24)
    limitations: tuple[str, ...] = Field(default=(), max_length=20)


class SemanticCitationV2(ReviewCitation):
    source_start: int | None = Field(default=None, ge=0, strict=True)


class SemanticConstraintV2(SemanticConstraint):
    citations: tuple[SemanticCitationV2, ...] = Field(min_length=1, max_length=8)


class AxisCheckV2(AxisCheck):
    constraints: tuple[SemanticConstraintV2, ...] = Field(default=(), max_length=24)


class AssertionAssessmentV2(AssertionAssessment):
    citations: tuple[SemanticCitationV2, ...] = Field(default=(), max_length=8)


class ContextClaim(Contract):
    """Delivery state of a host-identified object, not an inference about a note."""
    object_id: str = Field(min_length=1)
    status: Literal['supplied', 'not_supplied', 'unresolved']


class ContextRequest(Contract):
    """A model question; it never establishes that material was not delivered."""
    question: str = Field(min_length=1, max_length=2000)
    reviewed_block_ids: tuple[str, ...] = Field(min_length=1, max_length=80)
    reference_ids: tuple[str, ...] = Field(default=(), max_length=20)


class SemanticAssessmentV2(Contract):
    packet_id: str = Field(min_length=1)
    checks: tuple[AxisCheckV2, ...] = Field(min_length=1, max_length=6)
    assertions: tuple[AssertionAssessmentV2, ...] = Field(default=(), max_length=24)
    context_claims: tuple[ContextClaim, ...] = Field(default=(), max_length=80)
    context_requests: tuple[ContextRequest, ...] = Field(default=(), max_length=20)


class SemanticTask(Contract):
    task_id: str = Field(min_length=1, max_length=200)
    record_ids: tuple[str, ...] = Field(min_length=1, max_length=24)
    axes: tuple[SemanticAxis, ...] = Field(min_length=1, max_length=6)
    assertions: tuple[ReviewAssertion, ...] = Field(default=(), max_length=24)
    additional_block_ids: tuple[str, ...] = Field(default=(), max_length=40)

    @model_validator(mode='after')
    def explicit_unique_scope(self):
        for values in (self.record_ids, self.axes, self.additional_block_ids,
                       tuple(a.assertion_id for a in self.assertions)):
            if len(set(values)) != len(values):
                raise ValueError('semantic task identifiers must be unique')
        if any(not set(a.record_ids) <= set(self.record_ids) or len(set(a.record_ids)) != len(a.record_ids)
               for a in self.assertions):
            raise ValueError('assertion records outside semantic task')
        return self
