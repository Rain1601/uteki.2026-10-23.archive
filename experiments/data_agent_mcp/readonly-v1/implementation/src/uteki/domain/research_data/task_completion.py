"""Engineering retrieval conditions, independent of semantic research quality."""
from typing import Literal

from pydantic import Field, model_validator

from .query_contract import Contract

COMPLETION_VERSION = 'retrieval-task-completion-v1'
ConditionStatus = Literal['satisfied', 'missing_evidence', 'blocked']


def aggregate(statuses):
    statuses = tuple(statuses)
    return 'blocked' if 'blocked' in statuses else 'missing_evidence' if 'missing_evidence' in statuses else 'satisfied'


class ConditionCheck(Contract):
    check_id: str
    status: ConditionStatus
    reason: str
    detail: str
    artifact_ids: tuple[str, ...] = ()
    record_ids: tuple[str, ...] = ()
    computed_ids: tuple[str, ...] = ()
    event_sequences: tuple[int, ...] = ()
    remaining_count: int | None = Field(default=None, ge=0)


class RequirementAssessment(Contract):
    requirement_id: str
    condition: str
    status: ConditionStatus
    checks: tuple[ConditionCheck, ...] = Field(min_length=1)
    retained_issues: tuple[dict, ...] = ()

    @model_validator(mode='after')
    def consistent_status(self):
        if len({c.check_id for c in self.checks}) != len(self.checks):
            raise ValueError('Completion check IDs must be unique within a requirement')
        if self.status != aggregate(c.status for c in self.checks):
            raise ValueError('Requirement status must follow its checks')
        return self


class TaskAssessment(Contract):
    task_id: str
    status: ConditionStatus
    dependency_checks: tuple[ConditionCheck, ...] = ()
    requirements: tuple[RequirementAssessment, ...] = Field(min_length=1)

    @model_validator(mode='after')
    def consistent_status(self):
        if len({r.requirement_id for r in self.requirements}) != len(self.requirements):
            raise ValueError('Assessment requirement IDs must be unique')
        if self.status != aggregate([r.status for r in self.requirements] + [d.status for d in self.dependency_checks]):
            raise ValueError('Task status must include its requirements and dependencies')
        return self


class CompletionAssessment(Contract):
    schema_version: Literal['retrieval-task-completion-v1'] = COMPLETION_VERSION
    plan_id: str
    plan_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    progress_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    sequence: int = Field(ge=0)
    step_limit: int = Field(ge=1)
    steps_remaining: int = Field(ge=0)
    conditions_status: ConditionStatus
    status: Literal['satisfied', 'missing_evidence', 'blocked', 'limited']
    finish_allowed: bool
    tasks: tuple[TaskAssessment, ...] = Field(min_length=1)
    semantic_completeness: Literal['not_evaluated'] = 'not_evaluated'
    scope_note: str = 'Engineering conditions for the explicit plan only; not semantic completeness, source extraction recall, or adoption.'

    @model_validator(mode='after')
    def consistent_status(self):
        if len({t.task_id for t in self.tasks}) != len(self.tasks):
            raise ValueError('Assessment task IDs must be unique')
        if self.steps_remaining != self.step_limit - self.sequence:
            raise ValueError('Completion cannot reset the execution limit')
        status = aggregate(t.status for t in self.tasks)
        if self.conditions_status != status or self.finish_allowed != (status == 'satisfied'):
            raise ValueError('Finish readiness must follow all task conditions')
        expected = 'limited' if not self.steps_remaining and status != 'satisfied' else status
        if self.status != expected:
            raise ValueError('Overall status must preserve exhaustion and condition outcomes')
        return self
