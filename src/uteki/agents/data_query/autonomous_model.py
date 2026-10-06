"""Metered SDK decisions for the autonomous loop; no separate model-call allowance."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time

from agents import Agent, AgentOutputSchema, ModelSettings, Runner, RunConfig
from agents.exceptions import ModelBehaviorError
from openai import AsyncOpenAI, APIConnectionError, APITimeoutError, RateLimitError, InternalServerError
from pydantic import ValidationError

from uteki.agents.runtime.call_costs import MeteredModel, pricing_snapshot, summarize
from uteki.agents.runtime.local_credentials import load_provider_key
from uteki.agents.runtime.model_factory import model_adapter
from uteki.agents.runtime.run_budget import RunBudget, BudgetExceeded
from uteki.infrastructure.research_data.financial_records import digest
from .artifacts import write_new
from .autonomous import AUTONOMOUS_PROMPT, AUTONOMOUS_PROMPT_VERSION, WORKER_PROMPT, AutonomousDecision


VISIBLE_OUTPUT_CHAR_LIMIT = 128000

# Match only contract-owned literal messages. Never echo an exception message,
# context or rejected input into the next model packet.
_DECISION_RULE_HINTS = {
    'Value error, unrelated action payloads are not allowed': (
        'one_action_payload',
        'Return only the selected action payload. requirements is allowed only with action=plan; '
        'use requirement_ids to reference existing requirements. For action=finish omit all '
        'action payloads, including evidence_ids.'),
    'Value error, selected action requires its payload': (
        'selected_action_requires_payload',
        'Provide the selected action payload using this action-to-field map: '
        'delegate=delegation, discover_catalog=catalog, probe_schema=schema_probe, '
        'read_artifact=artifact_read, load_skill=skill, plan=requirements, query=plan, '
        'outline_source=outline, read_source=read, search_source=search, read_context=context, '
        'reread=evidence_ids, extract=extracts, answer=answer, acquire=arguments, materialize=arguments, '
        'financial_extract=financial_extraction. '
        'The selected payload must be non-null and required lists must be nonempty.'),
    'Value error, source_id belongs to read_node, source_evidence or source_answer; node_id belongs only to read_node': (
        'requirement_source_fields',
        'Within requirements, source_id is allowed for kind=read_node, kind=source_evidence or kind=source_answer; '
        'node_id is allowed only for kind=read_node. For source_evidence or source_answer provide source_id and omit node_id. '
        'Omit them for information, query or financial_extract requirements; keep query scope in its QueryPlan '
        'and financial extraction scope in the registered task.'),
    'Value error, source_evidence requires explicit source_id': (
        'source_evidence_requires_source',
        'For kind=source_evidence provide a nonblank source_id from the scoped catalog and omit node_id.'),
    'Value error, source_answer requires explicit source_id': (
        'source_answer_requires_source',
        'For kind=source_answer provide a nonblank source_id from the scoped catalog and omit node_id.'),
    'Value error, partial answer requires unresolved questions; claimed_complete must have none': (
        'answer_coverage_consistency',
        'When the answer is incomplete, keep model_claimed_coverage=partial and list the remaining '
        'unresolved_questions. claimed_complete requires no unresolved_questions. Do not claim '
        'completion merely to satisfy validation; this coverage claim is not host semantic verification.'),
    'Value error, unresolved questions must be nonblank and at most 2000 characters': (
        'answer_unresolved_questions',
        'Each unresolved_questions entry must be nonblank and at most 2000 characters.'),
    'Value error, read_node requires explicit source_id and node_id': (
        'read_node_requires_source',
        'For kind=read_node provide both source_id and node_id from the scoped catalog.'),
    'Value error, query requirement needs an explicit QueryPlan': (
        'query_requirement_requires_plan',
        'For kind=query provide an explicit query payload containing its QueryPlan.'),
    'Value error, query payload belongs to a query requirement': (
        'requirement_query_payload',
        'Within requirements, query is allowed only for kind=query. Omit it for other kinds.'),
    'Value error, plan and gap require a reason': (
        'action_requires_reason',
        'For action=plan or action=gap provide a nonblank reason.'),
    'Value error, arguments belong to acquisition or materialization': (
        'arguments_action_scope',
        'arguments is allowed only for action=acquire or action=materialize.'),
    'Value error, financial_extract requires financial_task_id and batch_index': (
        'financial_requirement_task_batch',
        'For kind=financial_extract provide financial_task_id and an integer batch_index from financial_tasks. '
        'Omit source_id, node_id and query; the registered task pins source scope.'),
    'Value error, financial task and batch belong only to financial_extract requirements': (
        'financial_requirement_fields',
        'financial_task_id and batch_index are allowed only for kind=financial_extract.'),
}


def _decision_validation_hints(content):
    """Report structure and allowlisted repairs without arbitrary validation text."""
    try:
        AutonomousDecision.model_validate_json(content)
    except ValidationError as error:
        fields = set(AutonomousDecision.model_fields)
        hints = []
        for item in error.errors(include_url=False, include_context=False, include_input=False)[:8]:
            hint = {'type': item['type'],
                    'location': [part if type(part) is int or part in fields else '<field>'
                                 for part in item['loc'][:8]]}
            repair = _DECISION_RULE_HINTS.get(item['msg']) if item['type'] == 'value_error' else None
            if item['type'] == 'json_invalid':
                repair = ('single_json_object',
                          'Return exactly one valid JSON object; no prose, Markdown fences, '
                          'or multiple concatenated JSON objects.')
            if repair is not None:
                hint.update(rule=repair[0], suggestion=repair[1])
            hints.append(hint)
        return hints
    return [{'type': 'sdk_output_validation', 'location': []}]


class _RequestLimitedBudget:
    """Pin the shared request policy; an explicit None records without a ceiling."""
    def __init__(self, budget, maximum):
        self.budget = budget
        with budget._transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS autonomous_request_limit (id INTEGER PRIMARY KEY, maximum INTEGER)')
            db.execute('INSERT OR IGNORE INTO autonomous_request_limit VALUES (1, ?)', (maximum,))
            if db.execute('SELECT maximum FROM autonomous_request_limit WHERE id=1').fetchone()[0] != maximum:
                raise ValueError('Existing shared request limit cannot be silently changed')
            db.execute('''CREATE TRIGGER IF NOT EXISTS autonomous_request_limit_guard
                BEFORE INSERT ON reservations
                WHEN (SELECT COUNT(*) FROM reservations) >= (SELECT maximum FROM autonomous_request_limit WHERE id=1)
                BEGIN SELECT RAISE(ABORT, 'autonomous_shared_request_limit'); END''')

    def reserve(self, amount):
        try:
            return self.budget.reserve(amount)
        except sqlite3.IntegrityError as error:
            if 'autonomous_shared_request_limit' in str(error):
                raise BudgetExceeded('Shared model request limit exhausted') from error
            raise

    def settle(self, token, actual):
        return self.budget.settle(token, actual)


class SdkAutonomousPlanner:
    """Only the default provider path is model-origin; injected HTTP is a fixture.

    The caller owns the shared RunBudget and explicit authorization. This class
    never creates a fresh cost allowance or reconciles prior unknown charges.
    """
    def __init__(self, provider, model, *, budget, max_requests_total, output, credentials_root,
                 max_tokens=3000, request_timeout=90, max_retries=0, pricing=None, client_factory=None,
                 role='planner', reasoning_effort=None):
        if role not in {'planner', 'worker'}:
            raise ValueError('Role must be planner or worker')
        prompt = AUTONOMOUS_PROMPT if role == 'planner' else WORKER_PROMPT
        if reasoning_effort is not None and (not isinstance(reasoning_effort, str)
                or provider != 'deepseek' or reasoning_effort not in {'none', 'low', 'high', 'max'}):
            raise ValueError('Explicit reasoning effort is supported only for DeepSeek: none, low, high, max')
        effort = (reasoning_effort or 'none') if provider == 'deepseek' else None
        thinking = 'enabled' if effort not in {None, 'none'} else 'disabled'
        if not isinstance(budget, RunBudget):
            raise ValueError('An explicit shared RunBudget is required')
        if max_requests_total is not None and (type(max_requests_total) is not int or max_requests_total < 1):
            raise ValueError('Shared request limit must be positive or explicitly None')
        if type(max_tokens) is not int or not 256 <= max_tokens <= 8192:
            raise ValueError('Output token limit must be within 256..8192')
        if isinstance(request_timeout, bool) or not isinstance(request_timeout, (int, float)) or not 0 < request_timeout <= 300:
            raise ValueError('Request timeout must be within 0..300 seconds')
        if type(max_retries) is not int or not 0 <= max_retries <= 3:
            raise ValueError('Explicit retries must be within 0..3')
        registered_pricing = pricing_snapshot(provider, model)
        if not registered_pricing or provider not in {'deepseek', 'aihubmix'}:
            raise ValueError('Provider/model requires supported credentials and a recorded price snapshot')
        if pricing is not None and pricing != registered_pricing:
            raise ValueError('Explicit pricing differs from the registered provider/model snapshot')
        pricing = deepcopy(registered_pricing)
        self.output = Path(output).resolve()
        if self.output.exists():
            raise FileExistsError('Model artifact output already exists')
        self._plan_origin = 'scripted_fixture' if client_factory is not None else 'model'
        self._budget = budget
        self._capped_budget = _RequestLimitedBudget(budget, max_requests_total)
        credential_origin = load_provider_key(credentials_root, provider)
        self.output.mkdir(parents=True, exist_ok=False)
        self._clients = []
        factory = client_factory or AsyncOpenAI
        def create_client(**kwargs):
            # model_factory disables hidden SDK retries; keep that contract exact.
            if kwargs.get('max_retries') != 0:
                raise ValueError('Provider SDK retries must be disabled for per-attempt accounting')
            # The provider transport must respect the same role-specific timeout
            # as the outer decision call, rather than the factory's older default.
            kwargs['timeout'] = request_timeout
            client = factory(**kwargs)
            self._clients.append(client)
            return client
        inner = model_adapter(model, provider, client_factory=create_client)
        self._model = MeteredModel(inner, self.output/'calls', f'autonomous_{role}_decision', provider, model, pricing, self._capped_budget)
        self._agent = Agent(name='AutonomousDataPlanner' if role == 'planner' else 'BoundedDataWorker', instructions=prompt, model=self._model,
            output_type=AgentOutputSchema(AutonomousDecision, strict_json_schema=False),
            model_settings=ModelSettings(max_tokens=max_tokens, temperature=None if thinking == 'enabled' else 0, store=False,
                extra_body={'thinking': {'type': thinking}, 'reasoning_effort': effort} if provider == 'deepseek' else None))
        self._config = {'schema_version': 'autonomous-model-config-v1', 'plan_origin': self.plan_origin, 'role': role,
            'provider': provider, 'model': model, 'prompt': prompt, 'prompt_version': AUTONOMOUS_PROMPT_VERSION,
            'prompt_sha256': digest(prompt),
            'decision_schema': AutonomousDecision.model_json_schema(), 'pricing_snapshot': deepcopy(pricing),
            'strict_provider_schema': False, 'local_output_validation': 'AutonomousDecision',
            'max_tokens': max_tokens, 'request_timeout': request_timeout, 'max_retries': max_retries,
            'reasoning_effort': effort, 'thinking_mode': thinking if provider == 'deepseek' else None,
            'provider_sdk_retries': 0, 'max_requests_total': max_requests_total,
            'budget_ledger': str(budget.path.resolve()), 'budget_policy': 'enforced' if budget.enforce else 'record_only',
            'credential_origin': credential_origin, 'budget_at_start': budget.summary()}
        write_new(self.output/'model-config.json', self._config)
        self._config_sha256 = digest((self.output/'model-config.json').read_bytes())
        self._lock = asyncio.Lock()
        self._decisions, self._snapshots, self._closed = 0, 0, False

    @property
    def plan_origin(self):
        return self._plan_origin

    @property
    def frozen_config(self):
        return deepcopy(self._config)

    def _references(self, paths):
        return [{'path': str(path.relative_to(self.output)), 'sha256': digest(path.read_bytes())} for path in sorted(paths)]

    def snapshot_usage(self):
        """Immutable accounting snapshot; estimates and actual bills stay separate."""
        self._snapshots += 1
        summary = summarize(self.output/'calls')
        value = {'schema_version': 'autonomous-model-usage-v1', 'plan_origin': self.plan_origin, 'role': self._config['role'],
            'provider': self._config['provider'], 'model': self._config['model'],
            'reasoning_effort': self._config['reasoning_effort'], 'thinking_mode': self._config['thinking_mode'],
            'model_config_sha256': digest((self.output/'model-config.json').read_bytes()),
            'prompt_sha256': self._config['prompt_sha256'], 'calls': summary,
            'shared_budget': self._budget.summary(),
            'artifacts': self._references([self.output/'model-config.json', *(self.output/'calls').glob('*.json'),
                                         *self.output.glob('decision-*-attempt-*.json'),
                                         *self.output.glob('decision-*-output.json')]),
            'benchmark_status': 'not_evaluated'}
        path = self.output/f'usage-{self._snapshots:04d}.json'
        write_new(path, value)
        return {'artifact_root': str(self.output), 'path': path.name, 'sha256': digest(path.read_bytes()), 'summary': value}

    async def decide(self, packet):
        async with self._lock:
            if self._closed:
                raise ValueError('Planner is closed')
            # Assert the frozen provider/model/prompt contract before SDK execution.
            if digest((self.output/'model-config.json').read_bytes()) != self._config_sha256:
                raise ValueError('Frozen model configuration changed')
            self._decisions += 1
            encoded = json.dumps(packet, ensure_ascii=False)
            for attempt in range(self._config['max_retries'] + 1):
                # A failed reservation can happen before the adapter is invoked.
                # Do not attribute a previous call's response to this attempt.
                if self._config['provider'] == 'deepseek':
                    self._model.inner.response_text = None
                    self._model.inner.response_metadata = None
                before = set((self.output/'calls').glob('*.json'))
                started = time.monotonic()
                output_path = self.output/f'decision-{self._decisions:04d}-{attempt + 1:02d}-output.json'
                record = {'decision': self._decisions, 'attempt': attempt + 1, 'retry': attempt > 0,
                    'plan_origin': self.plan_origin, 'role': self._config['role'], 'packet_sha256': digest(encoded),
                    'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'started'}
                retry = False
                try:
                    result = await asyncio.wait_for(Runner.run(self._agent, encoded, max_turns=1,
                        run_config=RunConfig(tracing_disabled=True)), timeout=self._config['request_timeout'])
                    decision = AutonomousDecision.model_validate(result.final_output)
                    record['status'] = 'decision_returned'
                    return decision
                except BaseException as error:
                    record.update(status='timed_out' if isinstance(error, (TimeoutError, APITimeoutError)) else 'failed_or_cancelled',
                                  error_type=type(error).__name__)
                    metadata = getattr(self._model.inner, 'response_metadata', None) or {}
                    content = getattr(self._model.inner, 'response_text', None)
                    if (isinstance(error, ModelBehaviorError) and self._config['provider'] == 'deepseek'
                            and metadata.get('finish_reason') == 'stop'
                            and isinstance(content, str)):
                        # A normal stop with empty/whitespace text is an invalid
                        # decision, too. Let the host spend its next bounded turn
                        # requesting JSON; never execute an action or retry here.
                        hints = _decision_validation_hints(content)
                        record.update(status='invalid_model_decision', validation=hints)
                        raise ValueError('invalid_model_decision; visible_output=' + output_path.name
                                         + '; validation=' + json.dumps(hints, ensure_ascii=True)) from None
                    retry = isinstance(error, (TimeoutError, APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)) and attempt < self._config['max_retries']
                    if not retry: raise
                finally:
                    content = getattr(self._model.inner, 'response_text', None)
                    if self._config['provider'] == 'deepseek' and isinstance(content, str):
                        metadata = getattr(self._model.inner, 'response_metadata', None) or {}
                        write_new(output_path, {'schema_version': 'autonomous-visible-output-v1',
                            'decision': self._decisions, 'attempt': attempt + 1, 'role': self._config['role'],
                            'finish_reason': metadata.get('finish_reason'),
                            'content': content[:VISIBLE_OUTPUT_CHAR_LIMIT], 'content_chars': len(content),
                            'content_sha256': digest(content), 'truncated': len(content) > VISIBLE_OUTPUT_CHAR_LIMIT})
                        record['visible_output'] = self._references([output_path])[0]
                    record['elapsed_seconds'] = time.monotonic() - started
                    record['calls'] = self._references(set((self.output/'calls').glob('*.json')) - before)
                    write_new(self.output/f'decision-{self._decisions:04d}-attempt-{attempt + 1:02d}.json', record)
                    self.snapshot_usage()

    async def aclose(self):
        async with self._lock:
            if not self._closed:
                self._closed = True
                for client in self._clients:
                    await client.close()
