"""Caller-selected preparation or frozen-dataset input for the company agent."""
from typing import Literal
from pydantic import Field, model_validator

from .execution_scope import ExecutionScope
from .query_contract import Contract


class RegisteredFinancialTask(Contract):
    """Caller-owned financial scope and allowed method; never supplied by a planner."""
    task_id: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')
    job: dict
    task_profile: str = Field(min_length=1, pattern=r'\S')
    task_profile_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    max_new_batches: int = Field(strict=True, ge=1, le=32)


class CompanyQueryInput(Contract):
    question: str = Field(min_length=1, max_length=20000, pattern=r'\S')
    purpose: Literal['question_answer', 'business_materials'] = 'question_answer'
    dataset: str | None = Field(default=None, min_length=1, pattern=r'\S')
    scope: ExecutionScope | None = None
    prepared_run: str | None = Field(default=None, min_length=1, pattern=r'\S')
    company_config: dict | None = None
    include_candidates: bool | None = None
    limits: dict = Field(default_factory=dict)
    financial_tasks: tuple[RegisteredFinancialTask, ...] = Field(default=(), max_length=16)

    @model_validator(mode='after')
    def explicit_input(self):
        if len({task.task_id for task in self.financial_tasks}) != len(self.financial_tasks):
            raise ValueError('financial task IDs must be unique')
        if sum(x is not None for x in (self.dataset, self.prepared_run, self.company_config)) != 1:
            raise ValueError('select exactly one dataset, prepared_run or company_config')
        if self.dataset is not None:
            if self.scope is None or self.include_candidates is not None:
                raise ValueError('dataset requires a full scope; candidate policy belongs in scope')
        elif self.scope is not None or self.include_candidates is None:
            raise ValueError('preparation requires explicit include_candidates; scope comes from verified sources')
        return self
