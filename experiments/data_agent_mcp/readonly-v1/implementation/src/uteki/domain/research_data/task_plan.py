"""Explicit retrieval requirements; neither a semantic planner nor a completion judge."""
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .agent_query import QueryPlan
from .execution_scope import ExecutionScope, SourceOutlineRequest, SourceReadRequest, SourceSearchRequest
from .period_scope import explicit_periods, validate_plan_periods
from .query_contract import Contract

ID = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
TEXT = Annotated[str, Field(min_length=1, max_length=2000, pattern=r"\S")]
PLAN_VERSION = "retrieval-task-plan-v1"
PROGRESS_VERSION = "retrieval-task-progress-v1"


class ReadRequirement(Contract):
    kind: Literal['read_node']
    requirement_id: ID
    source_snapshot_id: ID
    node_id: ID
    condition: Literal['all_body_blocks_returned'] = 'all_body_blocks_returned'


class QueryRequirement(Contract):
    kind: Literal['query']
    requirement_id: ID
    query: QueryPlan
    condition: Literal['requested_records_and_calculations_returned'] = 'requested_records_and_calculations_returned'

    @model_validator(mode='after')
    def explicit_navigation(self):
        if self.query.documents:
            raise ValueError('Use an explicit read_node requirement for document navigation')
        if any(r.period is None for r in self.query.records):
            raise ValueError('Task queries require explicit periods; use a clarification requirement otherwise')
        return self


class ClarificationRequirement(Contract):
    kind: Literal['clarification']
    requirement_id: ID
    question: TEXT
    condition: Literal['caller_clarification_required'] = 'caller_clarification_required'


Requirement = Annotated[ReadRequirement | QueryRequirement | ClarificationRequirement, Field(discriminator='kind')]


class RetrievalTask(Contract):
    task_id: ID
    requested_information: TEXT
    source_snapshot_ids: tuple[ID, ...] = Field(min_length=1, max_length=64)
    depends_on: tuple[ID, ...] = Field(default=(), max_length=16)
    requirements: tuple[Requirement, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode='after')
    def distinct_and_scoped(self):
        for values in (self.source_snapshot_ids, self.depends_on, tuple(r.requirement_id for r in self.requirements)):
            if len(values) != len(set(values)):
                raise ValueError('Task sources, dependencies and requirement IDs must be unique')
        if any(r.source_snapshot_id not in self.source_snapshot_ids for r in self.requirements if r.kind == 'read_node'):
            raise ValueError('Reading requirement is outside task sources')
        return self


class TaskPlan(Contract):
    schema_version: Literal['retrieval-task-plan-v1'] = PLAN_VERSION
    plan_id: ID
    revision: Literal[1] = 1
    question: TEXT
    scope: ExecutionScope
    origin: Literal['caller', 'scripted_fixture', 'model']
    tasks: tuple[RetrievalTask, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode='after')
    def consistent_graph(self):
        tasks = {t.task_id: t for t in self.tasks}
        if len(tasks) != len(self.tasks):
            raise ValueError('Task IDs must be unique')
        allowed = explicit_periods(self.question)
        for task in self.tasks:
            if set(task.source_snapshot_ids) - set(self.scope.source_snapshot_ids):
                raise ValueError('Task sources exceed plan scope')
            if set(task.depends_on) - tasks.keys():
                raise ValueError('Task dependency does not exist')
            for requirement in task.requirements:
                if requirement.kind == 'query':
                    validate_plan_periods(requirement.query, allowed)
        visiting, visited = set(), set()
        def visit(key):
            if key in visiting:
                raise ValueError('Task dependency cycle')
            if key in visited:
                return
            visiting.add(key)
            for parent in tasks[key].depends_on:
                visit(parent)
            visiting.remove(key)
            visited.add(key)
        for key in tasks:
            visit(key)
        return self


class TaskStep(Contract):
    """Requests only: no imported result, progress, completion or scope override."""
    task_id: ID
    requirement_id: ID
    action: Literal['outline_source', 'read_source', 'search_source', 'query']
    outline: SourceOutlineRequest | None = None
    read: SourceReadRequest | None = None
    search: SourceSearchRequest | None = None
    query: QueryPlan | None = None

    @model_validator(mode='after')
    def exclusive_payload(self):
        payloads = {'outline_source': self.outline, 'read_source': self.read,
                    'search_source': self.search, 'query': self.query}
        if payloads[self.action] is None or sum(v is not None for v in payloads.values()) != 1:
            raise ValueError('Provide exactly the selected tool payload')
        return self


class BlockRef(Contract):
    snapshot_id: ID
    source_snapshot_id: ID
    index_id: ID
    block_id: ID


class TaskPlannerDecision(Contract):
    """Choose an existing task step or request a host completion check."""
    action: Literal['execute', 'finish', 'clarify']
    step: TaskStep | None = None
    clarification: TEXT | None = None

    @model_validator(mode='after')
    def exclusive_action(self):
        if ((self.action == 'execute') != (self.step is not None)
                or (self.action == 'clarify') != (self.clarification is not None)):
            raise ValueError('Provide only the selected action payload')
        return self


class TaskPlanProposal(Contract):
    """Model proposes requirements; the host supplies the original question/scope."""
    action: Literal['plan', 'clarify']
    tasks: tuple[RetrievalTask, ...] = Field(default=(), max_length=16)
    clarification: TEXT | None = None

    @model_validator(mode='after')
    def exclusive_proposal(self):
        if ((self.action == 'plan') != bool(self.tasks)
                or (self.action == 'clarify') != (self.clarification is not None)):
            raise ValueError('Provide a nonempty task proposal or a clarification')
        return self


class RequirementProgress(Contract):
    requirement_id: ID
    kind: Literal['read_node', 'query', 'clarification']
    availability: str
    required_body: tuple[BlockRef, ...] = ()
    returned_body: tuple[BlockRef, ...] = ()
    unread_body: tuple[BlockRef, ...] = ()
    image_references: tuple[BlockRef, ...] = ()
    non_body_blocks: tuple[BlockRef, ...] = ()
    context_ids: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()
    record_ids: tuple[str, ...] = ()
    computed_ids: tuple[str, ...] = ()
    last_read_cursor: dict | None = None
    first_unread: BlockRef | None = None
    observed_query_status: str | None = None
    query_selections: tuple[dict, ...] = ()
    events: tuple[int, ...] = ()
    issues: tuple[dict, ...] = ()
    completion: Literal['not_evaluated'] = 'not_evaluated'


class TaskProgress(Contract):
    task_id: ID
    requirements: tuple[RequirementProgress, ...]
    completion: Literal['not_evaluated'] = 'not_evaluated'


class ProgressSnapshot(Contract):
    schema_version: Literal['retrieval-task-progress-v1'] = PROGRESS_VERSION
    plan_id: ID
    plan_sha256: str
    snapshot_id: ID
    sequence: int = Field(ge=0)
    tasks: tuple[TaskProgress, ...]
    semantic_completeness: Literal['not_evaluated'] = 'not_evaluated'
