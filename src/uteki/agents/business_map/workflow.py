"""System-owned selection -> verified original material -> business candidate.

No caller-selected sections or excerpts. Selection sufficiency and candidate
quality remain separate from mechanical source-reading checks.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from uteki.domain.research_data.company_agent import CompanyQueryInput
from uteki.domain.research_data.query_contract import Contract
from uteki.agents.data_query.artifacts import write_new
from uteki.agents.data_query.coordinator import CompanyDataCoordinator, inspect_run
from uteki.agents.data_query.autonomous_model import _RequestLimitedBudget
from uteki.agents.runtime.local_credentials import load_provider_key
from uteki.agents.runtime.run_budget import RunBudget
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort
from . import product_run


class BusinessTaskInput(Contract):
    query: CompanyQueryInput
    skill_path: str = Field(min_length=1, pattern=r'\S')
    skill_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    max_material_bytes: int = Field(strict=True, ge=1)
    output_contract_version: Literal['business-draft-v2'] = 'business-draft-v2'
    wire_mode: Literal['full'] = 'full'

    @model_validator(mode='after')
    def selection_task(self):
        if self.query.purpose != 'business_materials':
            raise ValueError('business task requires purpose=business_materials')
        if self.query.financial_tasks:
            raise ValueError('business material selection cannot register financial extraction tasks')
        return self


async def run_business_task(request, *, root, workspace, output, planner_model_config,
                            extractor_model_config, credentials_root, observation_root,
                            sec_user_agent=None):
    """Public model-only path. Fixtures test the component boundaries separately."""
    from .runtime_materials import build_runtime_packet

    request = BusinessTaskInput.model_validate(request)
    root, output = Path(root).resolve(), Path(output).resolve()
    workspace = Path(workspace).resolve()
    if not output.is_relative_to(root) or output.exists():
        raise ValueError('new_business_task_output_inside_root_required')
    if output == workspace or output.is_relative_to(workspace/'sources') or output.is_relative_to(workspace/'source-runs'):
        raise ValueError('business_task_output_must_not_replace_source_storage')
    if observation_root is None:
        raise ValueError('business_task_observation_root_required')
    observation_root = Path(observation_root).resolve()
    if observation_root.is_relative_to(output) or output.is_relative_to(observation_root):
        raise ValueError('business_task_observations_must_be_separate')
    CompanyDataCoordinator._validate_shared_model_configs(planner_model_config, extractor_model_config)
    if extractor_model_config['provider'] != 'aihubmix' or extractor_model_config['model'] not in {
            'claude-sonnet-5-5', 'claude-opus-5-5'}:
        raise ValueError('business_extractor_requires_registered_native_claude')
    if (type(extractor_model_config.get('max_tokens')) is not int
            or not 256 <= extractor_model_config['max_tokens'] <= 64000):
        raise ValueError('business_extractor_requires_explicit_bounded_max_tokens')
    if not isinstance(extractor_model_config.get('request_timeout'), (int, float)) or not (
            0 < extractor_model_config['request_timeout'] <= 300):
        raise ValueError('business_extractor_requires_explicit_request_timeout')
    # Exercise the actual adapter's local validation before paying for planning.
    # This creates no HTTP client, request reservation or network request.
    from agents import ModelSettings
    from uteki.agents.runtime.claude_messages import ClaudeMessagesModel
    probe = ClaudeMessagesModel(extractor_model_config['model'], stream=True,
        reasoning_effort=extractor_model_config['reasoning_effort'],
        timeout_seconds=extractor_model_config['request_timeout'],
        max_output_tokens_limit=max(16000, extractor_model_config['max_tokens']))
    try:
        probe.request_body(system_instructions='Configuration validation only.', input='No dispatch.',
            model_settings=ModelSettings(max_tokens=extractor_model_config['max_tokens']),
            tools=[], output_schema=None, handoffs=[])
    finally:
        await probe.aclose()
    ledger = Path(planner_model_config['budget_ledger']).resolve()
    protected = [output]
    if request.query.dataset:
        protected.append(Path(request.query.dataset).resolve())
    if request.query.prepared_run:
        prepared_root = Path(request.query.prepared_run).resolve()
        protected.append(prepared_root)
        prepared_result = inspect_run(prepared_root)['result']
        if prepared_result.get('dataset'):
            protected.append(Path(prepared_result['dataset']['path']).resolve())
    if any(ledger.is_relative_to(path) for path in protected):
        raise ValueError('shared_business_budget_must_be_outside_frozen_outputs')
    if any(output.is_relative_to(path) for path in protected[1:]):
        raise ValueError('business_output_must_be_outside_frozen_inputs')
    skill_file = product_run.local_file(root, request.skill_path)
    skill_bytes = skill_file.read_bytes()
    if digest(skill_bytes) != request.skill_sha256 or not skill_bytes.decode('utf-8').strip():
        raise ValueError('business_skill_hash_mismatch_or_empty')
    # Validate the existing ledger policy before any model request. No stage may
    # silently reset its allowance or replace an unknown charge with zero.
    ledger_budget = RunBudget(ledger, planner_model_config['budget_usd'],
                             enforce=planner_model_config['budget_policy'] == 'enforced')
    shared_budget = _RequestLimitedBudget(ledger_budget, planner_model_config['max_requests_total'])
    output.mkdir(parents=True, exist_ok=False)
    # Freeze before planning; editing the repository Skill during a long read
    # must not change the extraction policy for an already-started task.
    (output/'skill.md').write_bytes(skill_bytes)
    write_new(output/'request.json', request.model_dump(mode='json'))
    write_new(output/'model-configs.json', {'planner': planner_model_config, 'extractor': extractor_model_config})
    result = {'schema_version': 'business-system-task-v1', 'status': 'failed',
              'plan_origin': 'model', 'selection_sufficiency': 'not_evaluated',
              'semantic_acceptance': 'not_evaluated', 'adoption': 'candidate',
              'material_selection': None, 'extraction': None, 'gaps': [],
              'budget_ledger': str(ledger)}
    stage = 'selection'
    prepared = None
    try:
        coordinator = CompanyDataCoordinator(workspace, sec_user_agent=sec_user_agent)
        selection = await coordinator.query(request.query, output=output/'selection',
            model_config=planner_model_config, credential_root=credentials_root,
            observation_root=observation_root)
        result['material_selection'] = {'path': 'selection/result.json', 'status': selection['status']}
        if selection['status'] != 'evidence_ready':
            result.update(status='material_gap', gaps=selection.get('gaps', []), stop_reason=selection.get('stop_reason'))
            return result
        stage = 'material_handoff'
        # Reverify the frozen query and selected dataset, not just an in-memory
        # success string returned by the planner.
        inspect_run(output/'selection')
        query_output = output/'selection/query'
        query_result = json.loads((query_output/'result.json').read_text())
        if query_result.get('plan_origin') != 'model' or query_result.get('purpose') != 'business_materials':
            raise ValueError('model_origin_business_selection_required')
        with QueryDataPort(Path(selection['dataset']['path'])) as owner:
            materials = build_runtime_packet(owner.scoped(query_result['active_scope']), query_result,
                query_output=query_output, output=output/'materials', root=root,
                max_bytes=request.max_material_bytes)
        result['material_selection'].update(materials_path='materials',
            reading_status='declared_materials_delivered', selection_sufficiency='not_evaluated')
        stage = 'extraction_preflight'
        packet_path = Path(materials['packet_path'])
        if not packet_path.is_absolute():
            packet_path = root/packet_path
        packet = json.loads(packet_path.read_text())
        prepared = product_run.prepare(root=root, packet_path=packet_path, skill_path=output/'skill.md',
            company_id=packet['company_id'], document_id=packet['document_id'], period_end=packet['period_end'],
            model=extractor_model_config['model'], effort=extractor_model_config['reasoning_effort'],
            max_tokens=extractor_model_config['max_tokens'], timeout_seconds=extractor_model_config['request_timeout'],
            stream=True, contract_version=request.output_contract_version, wire_mode=request.wire_mode)
        write_new(output/'extraction-preflight.json', prepared['manifest'])
        write_new(output/'handoff.json', {
            'selection_result_sha256': digest((query_output/'result.json').read_bytes()),
            'source_packet_sha256': prepared['manifest']['source_packet_sha256'],
            'request_sha256': prepared['manifest']['request_sha256'],
            'selection_sufficiency': 'not_evaluated', 'semantic_acceptance': 'not_evaluated',
            'budget_ledger': str(ledger)})
        stage = 'extraction'
        load_provider_key(credentials_root, 'aihubmix')
        extracted = await product_run.execute(prepared, root=root, output=output/'extraction',
            observation_root=observation_root, budget_limit_usd=extractor_model_config['budget_usd'],
            shared_budget=shared_budget)
        result.update(status=extracted['status'], stop_reason=extracted['stop_reason'],
            extraction={'path': 'extraction/result.json', 'trace_id': extracted['trace_id'],
                        'counts': extracted.get('counts'), 'validation': extracted.get('validation')})
        return result
    except asyncio.CancelledError:
        result.update(status='cancelled', stop_reason='cancelled', stage=stage)
        raise
    except Exception as error:
        result.update(status='material_gap' if stage == 'material_handoff' else 'failed',
                      stop_reason=type(error).__name__, stage=stage)
        # Avoid provider exception repr or credentials in task artifacts.
        result['gaps'].append({'stage': stage, 'reason': str(error)[:1000] if isinstance(error, ValueError) else type(error).__name__})
        return result
    finally:
        if prepared is not None and not getattr(prepared['native'], '_closed', False):
            await prepared['native'].aclose()
        result['budget'] = shared_budget.summary()
        write_new(output/'result.json', result)
        write_new(output/'manifest.json', {'files': {
            str(path.relative_to(output)): digest(path.read_bytes())
            for path in sorted(output.rglob('*')) if path.is_file()}})
