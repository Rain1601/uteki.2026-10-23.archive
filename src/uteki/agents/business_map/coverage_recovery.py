"""Resume a complete revision with redundant citation indexes omitted.

Preserve original model bytes and task ledger, materialize a deterministic index
projection, and make only one final self-audit (at most one transport retry).
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path

from agents import ModelSettings
from . import coverage_contract as contract
from . import coverage_run as run
from . import product_run as base
from .evidence_projection import project_relationship_evidence
from .product_contract import validate_draft
from .self_review import _load_input
from ..runtime.call_costs import MeteredModel, summarize
from ..runtime.claude_messages import ClaudeMessagesModel
from ..runtime.observation import observed_run, observed_step
from ..runtime.run_budget import RunBudget
from ..runtime.bounded_retry import metered_response
from ..runtime.strict_json import parse_json_object


async def execute(*, root, prior_failed_run, output, observation_root,
                  audit_max_tokens=30000, max_attempts=2):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists() or not output.is_relative_to(root) or observation_root is None:
        raise ValueError('new_output_inside_project_and_observation_root_required')
    if type(audit_max_tokens) is not int or not 1 <= audit_max_tokens <= 48000:
        raise ValueError('positive_bounded_audit_tokens_required')
    if type(max_attempts) is not int or max_attempts not in (1, 2):
        raise ValueError('at_most_one_transport_retry')
    prior_path = base.local_file(root, Path(prior_failed_run)/'summary.json')
    prior = parse_json_object(prior_path.read_text())
    attempts = prior.get('attempts', [])
    initial_recovery = (prior.get('status') == 'failed'
        and [a.get('mode') for a in attempts] == ['inventory', 'audit_initial', 'revision']
        and [a.get('status') for a in attempts] == ['completed', 'completed', 'failed']
        and attempts[-1].get('validation_error') == 'relationship_excerpt_evidence_mismatch')
    predispatch_recovery = (prior.get('status') == 'candidate'
        and prior.get('execution_mode') == 'completed_revision_index_projection_and_final_audit'
        and [a.get('mode') for a in attempts] == ['inventory', 'audit_initial', 'revision', 'audit_final']
        and [a.get('status') for a in attempts] == ['completed', 'completed', 'candidate', 'failed']
        and attempts[-1].get('stop_reason') in ('RequestEnvelopeTooLarge', 'BudgetExceeded'))
    if prior.get('schema_version') != 'business-coverage-run-v1' or not (initial_recovery or predispatch_recovery):
        raise ValueError('completed_revision_index_failure_required')
    original, prepared, initial, parent = _load_input(root, prior['input_run'])
    await prepared['native'].aclose()
    if any(prior.get(key) != parent.get(key) for key in ('source_packet_sha256', 'skill_sha256')):
        raise ValueError('prior_source_or_skill_mismatch')
    if prior['input_trace_id'] != parent['trace_id']:
        raise ValueError('prior_input_trace_mismatch')
    dependencies = {str(prior_path.relative_to(root)): base.digest(prior_path.read_bytes())}
    stages = {}
    for attempt in attempts[:3]:
        stage = base.local_file(root, Path(attempt['path'])/'result.json').parent
        names = ['request.json', 'response.txt', 'response_metadata.json', 'configuration.json',
                 'result.json', 'source_packet.json', 'manifest.json', 'output_schema.json', 'source_wire.json', 'skill.md']
        if attempt['mode'] == 'inventory':
            names.append('inventory.json')
        dependencies.update(run.verify_published_artifacts(root=root, observation_root=observation_root,
            stage=stage, trace_id=attempt['trace_id'], relative_paths=names))
        metadata = parse_json_object((stage/'response_metadata.json').read_text())
        if metadata.get('stop_reason') != 'end_turn' or metadata.get('usage_presence') != 'reported':
            raise ValueError('complete_reported_prior_response_required')
        if parse_json_object((stage/'source_packet.json').read_text()) != prepared['packet']:
            raise ValueError('prior_source_packet_mismatch')
        receipt = parse_json_object((stage/'result.json').read_text())
        if receipt['request_sha256'] != base.digest((stage/'request.json').read_bytes()):
            raise ValueError('prior_request_receipt_mismatch')
        stages[attempt['mode']] = stage
    if predispatch_recovery:
        failed = base.local_file(root, Path(attempts[-1]['path'])/'result.json').parent
        dependencies.update(run.verify_published_artifacts(root=root, observation_root=observation_root,
            stage=failed, trace_id=attempts[-1]['trace_id'],
            relative_paths=['request.json', 'configuration.json', 'response_metadata.json', 'result.json']))
        failed_result = parse_json_object((failed/'result.json').read_text())
        if failed_result.get('costs', {}).get('requests') != 0:
            raise ValueError('predispatch_recovery_requires_no_provider_call')
    inventory = contract.validate_inventory(parse_json_object((stages['inventory']/'inventory.json').read_text()), prepared['packet'])
    audit = contract.validate_audit(parse_json_object((stages['audit_initial']/'response.txt').read_text()),
                                   prepared['packet'], inventory, initial)
    revision = stages['revision']
    request = parse_json_object((revision/'request.json').read_text())
    payload = parse_json_object(request['messages'][0]['content'])
    if (payload.get('frozen_source_packet') != prepared['packet'] or payload.get('source_inventory') != inventory
            or payload.get('own_candidate') != initial or payload.get('own_audit') != audit
            or request.get('model') != parent['model']):
        raise ValueError('prior_revision_inputs_mismatch')
    raw = (revision/'response.txt').read_text()
    projected, projection = project_relationship_evidence(parse_json_object(raw), prepared['packet'],
        expected_version=parent['output_contract_version'])
    if not projection['changes']:
        raise ValueError('missing_index_projection_required')
    draft_model = validate_draft(projected, prepared['packet'], expected_version=parent['output_contract_version'])
    draft = draft_model.model_dump()
    budget_path = base.local_file(root, prior.get('budget_path') or prior_path.parent/'budget.sqlite')
    budget = RunBudget(budget_path, prior['budget']['limit_usd'], allow_unknown_reservations=True)
    if budget.summary() != prior['budget'] or prior['budget']['in_flight_requests']:
        raise ValueError('prior_budget_snapshot_mismatch_or_in_flight')

    async def verify_inputs():
        _, fresh, old_draft, old_parent = _load_input(root, prior['input_run'])
        await fresh['native'].aclose()
        if old_draft != initial or old_parent != parent or fresh['request'] != prepared['request']:
            raise ValueError('original_candidate_changed_after_preflight')
        for name, expected in dependencies.items():
            if base.digest(base.local_file(root, name).read_bytes()) != expected:
                raise ValueError('recovery_dependency_changed')

    await verify_inputs()
    # Same sidecar as the normal recovery path prevents a second successor.
    try:
        with (prior_path.parent/'recovery-claim.json').open('x') as stream:
            json.dump(dict(successor=str(output.relative_to(root)),
                prior_summary_sha256=base.digest(prior_path.read_bytes()),
                policy='one_successor_shared_ledger_final_audit_only'), stream)
    except FileExistsError:
        raise ValueError('prior_failed_run_already_has_successor') from None
    output.mkdir(parents=True)
    summary = deepcopy(prior)
    summary.update(status='candidate', execution_mode='completed_revision_index_projection_and_final_audit',
        max_calls=max_attempts, budget_path=str(budget_path.relative_to(root)),
        prior_failed_run=str(prior_path.parent.relative_to(root)),
        self_check_status='pending_final_audit', final_audit_candidate_sha256=None,
        stop_reason='projection_not_started', attempts=deepcopy(attempts[:2]),
        retry_policy=dict(max_attempts_per_stage=max_attempts, transient_only=True, unknown_cost='retain_full_reservation'))
    base.write_json(output/'recovery.json', dict(prior_failed_run=summary['prior_failed_run'],
        prior_summary_sha256=base.digest(prior_path.read_bytes()), budget_path=summary['budget_path'],
        inherited_budget=prior['budget'], verified_published_artifacts=dependencies))
    (output/'inventory').mkdir()
    base.write_json(output/'inventory/inventory.json', inventory)
    dependencies[str((output/'inventory/inventory.json').relative_to(root))] = base.digest((output/'inventory/inventory.json').read_bytes())
    try:
        stage = output/'revision'
        with observed_run(output=stage, kind='extraction', role='repairer',
                origin='business_map_evidence_index_projection', observation_root=observation_root,
                scope={k:parent[k] for k in ('company_id', 'period_end', 'task_type')},
                title='业务图引用索引补齐（零模型调用）') as context:
            stage.mkdir()
            with observed_step(context, 1, phase='从既有摘录派生索引并验证') as step:
                step.guard()
                await verify_inputs()
                for name in ('response.txt','response_metadata.json','request.json','configuration.json',
                             'source_packet.json','source_wire.json','output_schema.json','skill.md'):
                    (stage/name).write_bytes((revision/name).read_bytes())
                manifest = dict(parse_json_object((revision/'manifest.json').read_text()),
                    trace_id=context.run_id, parent_trace_id=attempts[2]['trace_id'],
                    actual_model_response_trace_id=parse_json_object((revision/'manifest.json').read_text()).get(
                        'actual_model_response_trace_id', attempts[2]['trace_id']),
                    execution_mode='deterministic_evidence_index_projection', model_calls_in_this_trace=0,
                    projection_implementation_sha256=base.digest(Path(__file__).with_name('evidence_projection.py').read_bytes()),
                    recovery_implementation_sha256=base.digest(Path(__file__).read_bytes()),
                    original_response_sha256=base.digest(raw.encode()))
                base.write_json(stage/'manifest.json', manifest)
                base.write_json(stage/'projection.json', projection)
                base.write_json(stage/'projected-raw.json', projected)
                base.write_json(stage/'draft.json', draft)
                counts = base.materialize(draft_model, prepared['packet'], root=root, output=stage,
                                         manifest=manifest, trace_id=context.run_id)
                result = dict(manifest, status='candidate', validation='passed', counts=counts,
                    semantic_acceptance='not_evaluated', budget=budget.summary(),
                    artifacts_sha256={name:base.digest((stage/name).read_bytes()) for name in ('business_map.json','evidence.html')})
                base.write_json(stage/'result.json', result)
                for file in stage.iterdir():
                    if file.is_file(): step.publish(file)
            summary['attempts'].append(dict(mode='revision', status='candidate', path=str(stage.relative_to(root)),
                trace_id=context.run_id, counts=counts, projection=projection, model_calls=0))
            summary.update(candidate_path=str(stage.relative_to(root)), candidate_sha256=contract.canonical_hash(draft),
                           stop_reason='candidate_projected_final_audit_pending')
        for file in stage.iterdir():
            if file.is_file(): dependencies[str(file.relative_to(root))] = base.digest(file.read_bytes())

        stage = output/'audit_final'
        attempt = dict(mode='audit_final', status='failed', path=str(stage.relative_to(root)))
        summary['attempts'].append(attempt)
        native = ClaudeMessagesModel(parent['model'], timeout_seconds=prepared['native'].timeout_seconds,
            reasoning_effort=prepared['native'].reasoning_effort, stream=prepared['native'].stream,
            max_output_tokens_limit=prepared['native'].max_output_tokens_limit,
            thinking_type=prepared['native'].thinking_type)
        schema = contract.Audit.model_json_schema()
        payload = dict(frozen_source_packet=prepared['packet'], source_inventory=inventory, own_candidate=draft,
            candidate_sha256=contract.canonical_hash(draft), inventory_sha256=contract.canonical_hash(inventory),
            check_targets=contract.check_targets(draft))
        kwargs = dict(system_instructions=run.AUDIT+run.COMMON.format(skill=prepared['skill'],schema=run._json(schema)),
            input=run._json(payload), model_settings=ModelSettings(max_tokens=audit_max_tokens),
            tools=[], output_schema=None, handoffs=[])
        audit_manifest = {}
        try:
            with observed_run(output=stage, kind='extraction', role='repairer', origin='business_map_coverage_audit_final',
                    observation_root=observation_root, scope={k:parent[k] for k in ('company_id','period_end','task_type')},
                    title='修订业务图最终自检') as context:
                stage.mkdir()
                attempt['trace_id'] = context.run_id
                try:
                    with observed_step(context, 1, phase='最终自检（只读本次候选）') as step:
                        step.guard()
                        await verify_inputs()
                        (stage/'request.json').write_bytes(native.request_body(**kwargs))
                        (stage/'source_packet.json').write_bytes(prepared['packet_raw'])
                        (stage/'skill.md').write_text(prepared['skill'])
                        (stage/'source_wire.json').write_text(kwargs['input'])
                        base.write_json(stage/'configuration.json', native.request_configuration(**kwargs))
                        base.write_json(stage/'output_schema.json', schema)
                        audit_manifest = dict(parent, trace_id=context.run_id,
                            execution_mode='coverage_audit_final', parent_trace_id=summary['attempts'][-2]['trace_id'],
                            request_sha256=base.digest((stage/'request.json').read_bytes()),
                            request_bytes=len((stage/'request.json').read_bytes()),
                            output_contract_version='business-coverage-audit-v1',
                            source_business_contract_version=parent['output_contract_version'],
                            source_wire_sha256=base.digest(kwargs['input'].encode()),
                            source_wire_bytes=len(kwargs['input'].encode()), source_wire_mode='own_candidate_inventory',
                            output_schema_sha256=base.digest(run._json(schema).encode()),
                            input_candidate_sha256=contract.canonical_hash(draft),
                            inventory_sha256=contract.canonical_hash(inventory), dependencies_sha256=dict(dependencies),
                            implementation_sha256={
                                'coverage_recovery.py':base.digest(Path(__file__).read_bytes()),
                                'runtime/run_budget.py':base.digest((Path(__file__).parent.parent/'runtime/run_budget.py').read_bytes()),
                                'runtime/call_costs.py':base.digest((Path(__file__).parent.parent/'runtime/call_costs.py').read_bytes())},
                            calls_max=max_attempts, retries=max_attempts-1)
                        audit_manifest.pop('reserved_estimated_usd', None)
                        base.write_json(stage/'manifest.json', audit_manifest)
                        for file in stage.iterdir():
                            if file.is_file(): step.publish(file)
                        meter = MeteredModel(native, stage/'model-calls', 'business_map_coverage_audit_final',
                            'aihubmix', parent['model'], parent['pricing_snapshot'], budget)
                        try:
                            await metered_response(meter.with_observation(step), folder=stage/'transport-attempts',
                                kwargs=kwargs, max_attempts=max_attempts, before_attempt=verify_inputs)
                        finally:
                            if native.response_text is not None:
                                (stage/'response.txt').write_text(native.response_text)
                            base.write_json(stage/'response_metadata.json', native.response_metadata)
                            for file in stage.iterdir():
                                if file.is_file(): step.publish(file)
                        if (native.response_metadata.get('usage_presence') != 'reported'
                                or native.response_metadata.get('stop_reason') != 'end_turn' or budget.summary()['in_flight_requests']):
                            raise ValueError('complete_reported_final_audit_required')
                        await verify_inputs()
                        final = contract.validate_audit(parse_json_object(native.response_text), prepared['packet'], inventory, draft)
                        before = {m['mention_id'] for m in audit['mappings'] if m['disposition']=='node'}
                        after = {m['mention_id'] for m in final['mappings'] if m['disposition']=='node'}
                        final['regressed_mention_ids'] = sorted(before-after)
                        if before-after:
                            final['computed_status'] = 'needs_revision'
                            final['gaps'].append(dict(kind='lost_previously_mapped_mentions', mention_ids=sorted(before-after)))
                        base.write_json(stage/'audit.json', final)
                        step.publish(stage/'audit.json')
                        attempt.update(status='completed', self_check_status=final['computed_status'])
                        summary.update(self_check_status=final['computed_status'],
                            final_audit_candidate_sha256=contract.canonical_hash(draft),
                            stop_reason='final_self_audit_'+final['computed_status'])
                except BaseException as error:
                    attempt.update(stop_reason=type(error).__name__)
                    summary.update(stop_reason='audit_final_failed_'+type(error).__name__, self_check_status='not_completed')
                    raise
                finally:
                    base.write_json(stage/'result.json', dict(audit_manifest, **attempt, semantic_acceptance='not_evaluated',
                        budget=budget.summary(), costs=summarize(stage/'model-calls') if (stage/'model-calls').exists() else None))
                    context.publish(stage/'result.json')
        finally:
            await native.aclose()
    except Exception as error:
        # A valid projected candidate remains inspectable even if audit cannot run.
        summary['recovery_error_type'] = type(error).__name__
        if summary['stop_reason'] == 'projection_not_started':
            summary.update(status='failed', stop_reason='projection_failed_'+type(error).__name__)
    finally:
        summary.update(budget=budget.summary(), estimated_spent_usd=budget.summary()['estimated_spent_usd'],
            unknown_requests=budget.summary()['unknown_requests'], in_flight_requests=budget.summary()['in_flight_requests'])
        base.write_json(output/'summary.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'prior-failed-run', 'output', 'observation-root'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--audit-max-tokens', type=int, default=30000)
    parser.add_argument('--max-attempts', type=int, default=2)
    args = parser.parse_args()
    from ..runtime.local_credentials import load_provider_key
    load_provider_key(args.root, 'aihubmix')
    result = asyncio.run(execute(**vars(args)))
    print(json.dumps({key:result[key] for key in ('status','stop_reason','candidate_path','budget')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
