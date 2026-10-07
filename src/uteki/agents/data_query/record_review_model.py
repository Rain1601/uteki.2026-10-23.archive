"""Metered record-review JSON with immutable raw responses, including rejected output."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from agents import Agent, AgentOutputSchema, ModelSettings, Runner, RunConfig
from openai import AsyncOpenAI, APIConnectionError, APITimeoutError, RateLimitError, InternalServerError

from uteki.agents.runtime.call_costs import MeteredModel, pricing_snapshot, summarize
from uteki.agents.runtime.local_credentials import load_provider_key
from uteki.agents.runtime.model_factory import model_adapter
from uteki.agents.runtime.run_budget import RunBudget
from uteki.infrastructure.research_data.financial_records import digest
from .artifacts import write_new
from .autonomous_model import _RequestLimitedBudget


REVIEW_INPUT_FORMATS = ('packet_json_v1', 'review_turns_v1')


def review_model_input(packet, input_format):
    """Rearrange a review envelope into turns without changing its source data."""
    if input_format not in REVIEW_INPUT_FORMATS:
        raise ValueError('Unsupported review input format')
    encode = lambda value: json.dumps(value, ensure_ascii=False)
    if input_format == 'packet_json_v1' or 'host_validation_feedback' not in packet:
        return encode(packet)
    feedback = deepcopy(packet['host_validation_feedback'])
    if not isinstance(feedback, dict) or feedback.get('stage') not in ('proposal', 'audit', 'semantic_audit'):
        raise ValueError('Explicit supported review feedback stage required')
    original = {key: value for key, value in packet.items() if key != 'host_validation_feedback'}
    messages = [{'role': 'user', 'content': encode(original)}]
    has_draft = 'previous_assessment' in feedback
    draft = feedback.pop('previous_assessment', None)
    if has_draft:
        if not isinstance(draft, dict):
            raise ValueError('Previous assessment must be an explicit model draft object')
        messages.append({'role': 'assistant', 'content': encode(draft)})
    semantic = feedback['stage'] == 'semantic_audit'
    audit_protocol = feedback['stage'] == 'audit'
    request = {
        'operation': ('Correct and return a complete JSON critique of the SAME assessment. Preserve its packet_id and assessment_sha256; do not modify the assessment.'
                      if audit_protocol else 'Recheck the supplied feedback against the original sources and return a complete replacement JSON assessment.'),
        'feedback_kind': 'model_critique_to_verify' if semantic else 'host_protocol_diagnostics',
        'boundary': ('Critic opinions are not source facts. Verify material errors; suggestions do not require changes.'
                     if semantic else 'Diagnostics establish protocol defects only, not financial truth. Do not invent missing source evidence.'),
        'previous_assessment_sha256': digest(draft) if has_draft else None,
        'previous_assessment_status': feedback.get('previous_assessment_status',
            'protocol_validated_normalized' if semantic and has_draft else 'unspecified'),
        'host_validation_feedback': feedback,
    }
    messages.append({'role': 'user', 'content': encode(request)})
    return messages


class SdkRecordReviewer:
    """DeepSeek raw capture is supported; the caller owns business validation and authorization."""
    def __init__(self, provider, model, *, budget, max_requests_total, output, credentials_root, prompt,
                 max_tokens=8192, request_timeout=180, max_retries=0, client_factory=None, output_schema=None,
                 input_format='packet_json_v1', reasoning_effort=None, max_request_bytes=400000):
        if reasoning_effort is not None and (not isinstance(reasoning_effort, str)
                or provider != 'deepseek' or reasoning_effort not in {'none', 'low', 'high', 'max'}):
            raise ValueError('Explicit reasoning effort is supported only for DeepSeek: none, low, high, max')
        effort = (reasoning_effort or 'none') if provider == 'deepseek' else None
        thinking = 'enabled' if effort not in {None, 'none'} else 'disabled'
        if not isinstance(budget, RunBudget):
            raise ValueError('An explicit shared RunBudget is required')
        if max_requests_total is not None and (type(max_requests_total) is not int or max_requests_total < 1):
            raise ValueError('Shared request limit must be positive or explicitly None')
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError('Explicit nonblank record-review prompt required')
        if type(max_tokens) is not int or not 256 <= max_tokens <= 16384:
            raise ValueError('Output token limit must be within 256..16384')
        if isinstance(request_timeout, bool) or not isinstance(request_timeout, (int, float)) or not 0 < request_timeout <= 300:
            raise ValueError('Request timeout must be within 0..300 seconds')
        if type(max_retries) is not int or not 0 <= max_retries <= 3:
            raise ValueError('Explicit retries must be within 0..3')
        if type(max_request_bytes) is not int or max_request_bytes < 1:
            raise ValueError('max_request_bytes must be a positive integer')
        if input_format not in REVIEW_INPUT_FORMATS:
            raise ValueError('Unsupported review input format')
        pricing = pricing_snapshot(provider, model)
        if provider != 'deepseek' or not pricing:
            raise ValueError('Raw record-review capture requires a registered DeepSeek model')
        schema = AgentOutputSchema(output_schema or dict, strict_json_schema=False)
        self.output = Path(output).resolve()
        if self.output.exists():
            raise FileExistsError('Review artifact output already exists')
        self._plan_origin = 'scripted_fixture' if client_factory is not None else 'model'
        self._budget = budget
        cap = _RequestLimitedBudget(budget, max_requests_total)
        credential_origin = load_provider_key(credentials_root, provider)
        self.output.mkdir(parents=True, exist_ok=False)
        self._clients = []
        factory = client_factory or AsyncOpenAI
        def create_client(**kwargs):
            if kwargs.get('max_retries') != 0:
                raise ValueError('Hidden provider retries are forbidden')
            kwargs['timeout'] = request_timeout
            client = factory(**kwargs)
            self._clients.append(client)
            return client
        self._inner = model_adapter(model, provider, client_factory=create_client)
        metered = MeteredModel(self._inner, self.output/'calls', 'record_review', provider, model, pricing, cap,
                               max_request_bytes=max_request_bytes)
        self._agent = Agent(name='RecordReviewer', instructions=prompt, model=metered, output_type=schema,
            model_settings=ModelSettings(max_tokens=max_tokens, temperature=None if thinking == 'enabled' else 0, store=False,
                extra_body={'thinking': {'type': thinking}, 'reasoning_effort': effort} if provider == 'deepseek' else None))
        self._config = {'schema_version': 'record-review-model-config-v1', 'plan_origin': self.plan_origin,
            'provider': provider, 'model': model, 'prompt': prompt, 'prompt_sha256': digest(prompt),
            'input_format': input_format,
            'output_schema': schema.json_schema(), 'strict_provider_schema': False,
            'business_validation': 'caller_responsibility', 'pricing_snapshot': deepcopy(pricing),
            'max_tokens': max_tokens, 'request_timeout': request_timeout, 'max_retries': max_retries,
            'max_request_bytes': max_request_bytes,
            'reasoning_effort': effort, 'thinking_mode': thinking if provider == 'deepseek' else None,
            'provider_sdk_retries': 0, 'max_requests_total': max_requests_total,
            'budget_ledger': str(budget.path.resolve()), 'budget_policy': 'enforced' if budget.enforce else 'record_only',
            'credential_origin': credential_origin, 'budget_at_start': budget.summary()}
        write_new(self.output/'model-config.json', self._config)
        self._config_sha256 = digest((self.output/'model-config.json').read_bytes())
        self._lock = asyncio.Lock()
        self._reviews, self._snapshots, self._closed = 0, 0, False

    @property
    def plan_origin(self):
        return self._plan_origin

    @property
    def frozen_config(self):
        return deepcopy(self._config)

    def _references(self, paths):
        return [{'path': str(path.relative_to(self.output)), 'sha256': digest(path.read_bytes())} for path in sorted(paths)]

    def snapshot_usage(self):
        self._snapshots += 1
        value = {'schema_version': 'record-review-model-usage-v1', 'plan_origin': self.plan_origin,
            'provider': self._config['provider'], 'model': self._config['model'],
            'reasoning_effort': self._config['reasoning_effort'], 'thinking_mode': self._config['thinking_mode'],
            'max_request_bytes': self._config['max_request_bytes'],
            'model_config_sha256': self._config_sha256, 'prompt_sha256': self._config['prompt_sha256'],
            'calls': summarize(self.output/'calls'), 'shared_budget': self._budget.summary(),
            'artifacts': self._references([self.output/'model-config.json', *(self.output/'calls').glob('*.json'),
                                         *self.output.glob('review-*.json')]),
            'business_validation': 'not_evaluated'}
        path = self.output/f'usage-{self._snapshots:04d}.json'
        write_new(path, value)
        return {'artifact_root': str(self.output), 'path': path.name, 'sha256': digest(path.read_bytes()), 'summary': value}

    async def review(self, packet, *, observation_context=None):
        async with self._lock:
            if self._closed:
                raise ValueError('Reviewer is closed')
            if digest((self.output/'model-config.json').read_bytes()) != self._config_sha256:
                raise ValueError('Frozen review model configuration changed')
            self._reviews += 1
            encoded = json.dumps(packet, ensure_ascii=False)
            model_input = review_model_input(packet, self._config['input_format'])
            request_path = self.output/f'review-{self._reviews:04d}-input.json'
            write_new(request_path, {'packet': packet, 'packet_sha256': digest(encoded),
                'model_input': model_input, 'model_input_sha256': digest(model_input),
                'model_config_sha256': self._config_sha256, 'prompt_sha256': self._config['prompt_sha256']})
            if observation_context:
                observation_context.publish(request_path, kind='model_input', owned_by_context=True)
            for attempt in range(self._config['max_retries'] + 1):
                before = set((self.output/'calls').glob('*.json'))
                # A budget rejection before get_response must not inherit the last response.
                self._inner.response_text = None
                self._inner.response_metadata = None
                started = time.monotonic()
                record = {'schema_version': 'record-review-attempt-v1', 'review': self._reviews,
                    'attempt': attempt + 1, 'retry': attempt > 0, 'plan_origin': self.plan_origin,
                    'provider': self._config['provider'], 'model': self._config['model'],
                    'request': self._references([request_path])[0], 'status': 'started',
                    'started_at': datetime.now(timezone.utc).isoformat()}
                try:
                    agent = self._agent
                    if observation_context:
                        observation_context.guard()
                        agent = agent.clone(model=self._agent.model.with_observation(observation_context.for_attempt(attempt + 1)))
                    result = await asyncio.wait_for(Runner.run(agent, model_input, max_turns=1,
                        run_config=RunConfig(tracing_disabled=True)), timeout=self._config['request_timeout'])
                    value = result.final_output
                    if hasattr(value, 'model_dump'): value = value.model_dump(mode='json')
                    if not isinstance(value, dict): raise ValueError('Record-review output must be a JSON object')
                    record['status'] = 'json_returned'
                    write_new(self.output/f'review-{self._reviews:04d}-parsed.json', value)
                    return value
                except BaseException as error:
                    record.update(status='timed_out' if isinstance(error, (TimeoutError, APITimeoutError)) else 'failed_or_cancelled',
                                  error_type=type(error).__name__)
                    retry = isinstance(error, (TimeoutError, APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)) and attempt < self._config['max_retries']
                    if not retry: raise
                finally:
                    # DeepSeek captures text/metadata before rejecting finish_reason or invalid content.
                    record.update(raw_text=self._inner.response_text,
                                  response_text=self._inner.response_text,
                                  response_metadata=deepcopy(self._inner.response_metadata),
                                  elapsed_seconds=time.monotonic()-started,
                                  ended_at=datetime.now(timezone.utc).isoformat())
                    record['calls'] = self._references(set((self.output/'calls').glob('*.json')) - before)
                    write_new(self.output/f'review-{self._reviews:04d}-attempt-{attempt + 1:02d}.json', record)
                    self.snapshot_usage()
                    if observation_context:
                        observation_context.publish(self.output/f'review-{self._reviews:04d}-attempt-{attempt + 1:02d}.json',
                            kind='model_attempt', owned_by_context=True)
                        parsed = self.output/f'review-{self._reviews:04d}-parsed.json'
                        if parsed.exists():
                            observation_context.publish(parsed, kind='model_output', owned_by_context=True)

    async def aclose(self):
        async with self._lock:
            if not self._closed:
                self._closed = True
                for client in self._clients:
                    await client.close()
