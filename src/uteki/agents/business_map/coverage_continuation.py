"""One explicitly authorized revision and fresh audit on the original task ledger."""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from decimal import Decimal

from agents import ModelSettings
from . import coverage_contract as contract, coverage_run as run, product_run as base
from .evidence_projection import project_relationship_evidence
from .product_contract import validate_draft
from .self_review import _load_input
from ..runtime.call_costs import MeteredModel, summarize
from ..runtime.claude_messages import ClaudeMessagesModel
from ..runtime.observation import observed_run, observed_step
from ..runtime.run_budget import RunBudget
from ..runtime.bounded_retry import metered_response
from ..runtime.strict_json import parse_json_object

REVISION_INSTRUCTION = run.REVISE + '''
Your own audit can contain false negatives. Recheck exact cited excerpts against
every full claim and relationship, including items previously marked supported;
a true fact elsewhere in the block is not enough. Keep unchanged supported
content. All repairs must follow the selected source and existing output contract.
'''


async def execute(*, root, prior_run, output, observation_root, authorization_path,
                  revision_max_tokens=48000, audit_max_tokens=24000, max_attempts=2):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists() or not output.is_relative_to(root) or observation_root is None:
        raise ValueError('new_output_inside_project_and_observation_root_required')
    if any(type(n) is not int or not 1 <= n <= 48000 for n in (revision_max_tokens,audit_max_tokens)):
        raise ValueError('positive_bounded_stage_tokens_required')
    if type(max_attempts) is not int or max_attempts not in (1,2):
        raise ValueError('at_most_one_transport_retry_per_stage')
    prior_path = base.local_file(root, Path(prior_run)/'summary.json')
    read = lambda path: parse_json_object(base.local_file(root,path).read_text())
    prior = read(prior_path)
    if (prior.get('schema_version') != 'business-coverage-run-v1' or prior.get('status') != 'candidate'
            or prior.get('self_check_status') != 'needs_revision' or prior.get('semantic_acceptance') != 'not_evaluated'):
        raise ValueError('candidate_with_completed_self_audit_required')
    original, prepared, initial, parent = _load_input(root, prior['input_run'])
    await prepared['native'].aclose()
    if (prior['input_trace_id'] != parent['trace_id']
            or any(prior[k] != parent[k] for k in ('source_packet_sha256','skill_sha256'))):
        raise ValueError('prior_input_scope_mismatch')
    candidate = base.local_file(root,Path(prior['candidate_path'])/'result.json').parent
    revision_attempt = next((a for a in prior['attempts']
        if (root/a['path']).resolve()==candidate and a['mode']=='revision' and a['status']=='candidate'), None)
    final_attempt = next((a for a in reversed(prior['attempts'])
        if a['mode']=='audit_final' and a['status']=='completed'),None)
    inventory_attempt = next((a for a in prior['attempts'] if a['mode']=='inventory' and a['status']=='completed'),None)
    if not all((revision_attempt,final_attempt,inventory_attempt)):
        raise ValueError('published_inventory_revision_and_final_audit_required')
    audit_stage = base.local_file(root,Path(final_attempt['path'])/'audit.json').parent
    inv_stage = base.local_file(root,Path(inventory_attempt['path'])/'inventory.json').parent
    authorization_file = base.local_file(root,authorization_path)
    authorization = read(authorization_file)
    dependencies = {str(p.relative_to(root)):base.digest(p.read_bytes()) for p in (prior_path,authorization_file)}
    for stage, attempt, names in (
        (candidate,revision_attempt,['draft.json','response.txt','result.json','manifest.json','source_packet.json',
                                    'skill.md','request.json','configuration.json','response_metadata.json']),
        (audit_stage,final_attempt,['audit.json','request.json','response.txt','response_metadata.json','result.json',
                                   'manifest.json','source_packet.json','skill.md','configuration.json']),
        (inv_stage,inventory_attempt,['inventory.json','request.json','response.txt','result.json'])):
        dependencies.update(run.verify_published_artifacts(root=root,observation_root=observation_root,
            stage=stage,trace_id=attempt['trace_id'],relative_paths=names))
    packet = prepared['packet']
    if read(candidate/'source_packet.json') != packet or (candidate/'skill.md').read_text() != prepared['skill']:
        raise ValueError('candidate_packet_or_skill_changed')
    inventory = contract.validate_inventory(read(inv_stage/'inventory.json'),packet)
    draft = validate_draft(read(candidate/'draft.json'),packet,expected_version=parent['output_contract_version']).model_dump()
    projected, _ = project_relationship_evidence(read(candidate/'response.txt'),packet,
        expected_version=parent['output_contract_version'])
    if validate_draft(projected,packet,expected_version=parent['output_contract_version']).model_dump() != draft:
        raise ValueError('candidate_not_derived_from_own_response')
    if prior['candidate_sha256'] != contract.canonical_hash(draft) or prior['final_audit_candidate_sha256'] != contract.canonical_hash(draft):
        raise ValueError('candidate_summary_hash_mismatch')
    audit_request = read(audit_stage/'request.json')
    payload = parse_json_object(audit_request['messages'][0]['content'])
    if (payload.get('frozen_source_packet') != packet or payload.get('source_inventory') != inventory
            or payload.get('own_candidate') != draft or payload.get('check_targets') != contract.check_targets(draft)):
        raise ValueError('prior_audit_input_mismatch')
    if read(audit_stage/'response_metadata.json').get('stop_reason') != 'end_turn':
        raise ValueError('completed_prior_audit_required')
    audit = contract.validate_audit(read(audit_stage/'response.txt'),packet,inventory,draft)
    # Preserve host regression findings, after binding the model's original ledger.
    published_audit = read(audit_stage/'audit.json')
    if any(published_audit[k] != audit[k] for k in ('candidate_sha256','inventory_sha256','mappings','checks')):
        raise ValueError('published_audit_response_mismatch')
    if published_audit.get('computed_status') != 'needs_revision':
        raise ValueError('prior_audit_has_no_revision_request')
    audit = published_audit
    initial_draft, initial_audit = deepcopy(draft), deepcopy(audit)
    budget_path = run._existing_budget_path(root, prior_path.parent, prior)
    budget = RunBudget(budget_path,prior['budget']['limit_usd'],allow_unknown_reservations=True)
    if budget.summary()!=prior['budget'] or prior['budget']['in_flight_requests']:
        raise ValueError('prior_budget_snapshot_mismatch_or_in_flight')
    if (authorization.get('prior_run') != str(prior_path.parent.relative_to(root))
            or authorization.get('budget_path') != str(budget_path.relative_to(root))
            or authorization.get('prior_summary_sha256') != base.digest(prior_path.read_bytes())
            or authorization.get('authorized_by') != 'user'
            or authorization.get('old_limit_usd') != prior['budget']['limit_usd']
            or not all(isinstance(authorization.get(k),str) and authorization[k].strip()
                       for k in ('confirmation','authorization_id','scope','new_limit_usd'))):
        raise ValueError('authorization_scope_mismatch')
    old_limit,new_limit=Decimal(authorization['old_limit_usd']),Decimal(authorization['new_limit_usd'])
    if (not new_limit.is_finite() or new_limit<=old_limit
            or not isinstance(authorization.get('scope'),str) or not authorization['scope'].strip()):
        raise ValueError('authorization_limit_or_scope_invalid')

    async def guard():
        _, fresh, old, old_parent = _load_input(root,prior['input_run'])
        await fresh['native'].aclose()
        if old!=initial or old_parent!=parent or fresh['request']!=prepared['request']:
            raise ValueError('original_scope_changed')
        for name, expected in dependencies.items():
            if base.digest(base.local_file(root,name).read_bytes()) != expected:
                raise ValueError('continuation_dependency_changed')

    await guard()
    try:
        with (prior_path.parent/'recovery-claim.json').open('x') as stream:
            json.dump(dict(successor=str(output.relative_to(root)),prior_summary_sha256=base.digest(prior_path.read_bytes()),
                authorization_sha256=base.digest(authorization_file.read_bytes()),policy='one_authorized_continuation_same_ledger'),stream)
    except FileExistsError:
        raise ValueError('prior_run_already_has_successor') from None
    output.mkdir(parents=True)
    (output/'inventory').mkdir()
    record = budget.increase_limit(authorization['new_limit_usd'],expected_current=authorization['old_limit_usd'],
                                  authorization=authorization)
    base.write_json(output/'budget-authorization.json',record)
    base.write_json(output/'inventory/inventory.json',inventory)
    summary = deepcopy(prior)
    summary.update(execution_mode='authorized_single_coverage_continuation',prior_run=str(prior_path.parent.relative_to(root)),
        input_candidate_path=str(candidate.relative_to(root)),input_candidate_sha256=contract.canonical_hash(draft),
        input_audit_path=str((audit_stage/'audit.json').relative_to(root)),input_audit_sha256=base.digest((audit_stage/'audit.json').read_bytes()),
        authorization_sha256=base.digest(authorization_file.read_bytes()),
        budget_path=str(budget_path.relative_to(root)),max_calls=2*max_attempts,max_revisions=1,
        attempts=[deepcopy(inventory_attempt)],stop_reason='continuation_started',self_check_status='prior_needs_revision',
        final_audit_candidate_sha256=None,status='candidate',semantic_acceptance='not_evaluated',
        retry_policy=dict(max_attempts_per_stage=max_attempts,transient_only=True,unknown_cost='retain_full_reservation'))
    try:
        for mode in ('revision','audit_final'):
            stage=output/mode
            attempt=dict(mode=mode,status='failed',path=str(stage.relative_to(root)))
            summary['attempts'].append(attempt)
            native=ClaudeMessagesModel(parent['model'],timeout_seconds=prepared['native'].timeout_seconds,
                reasoning_effort=prepared['native'].reasoning_effort,stream=prepared['native'].stream,
                max_output_tokens_limit=prepared['native'].max_output_tokens_limit,
                thinking_type=prepared['native'].thinking_type)
            manifest={}
            try:
                with observed_run(output=stage,kind='extraction',role='repairer',origin='business_map_continuation_'+mode,
                        observation_root=observation_root,scope={k:parent[k] for k in ('company_id','period_end','task_type')},
                        title='业务图授权单轮 / '+mode) as context:
                    stage.mkdir()
                    attempt['trace_id']=context.run_id
                    try:
                        schema=prepared['schema'] if mode=='revision' else contract.Audit.model_json_schema()
                        payload=dict(frozen_source_packet=packet,source_inventory=inventory,own_candidate=draft)
                        if mode=='revision':payload['own_audit']=audit
                        else:payload.update(candidate_sha256=contract.canonical_hash(draft),
                            inventory_sha256=contract.canonical_hash(inventory),check_targets=contract.check_targets(draft))
                        kwargs=dict(system_instructions=(REVISION_INSTRUCTION if mode=='revision' else run.AUDIT)+
                            run.COMMON.format(skill=prepared['skill'],schema=run._json(schema)),input=run._json(payload),
                            model_settings=ModelSettings(max_tokens=revision_max_tokens if mode=='revision' else audit_max_tokens),
                            tools=[],output_schema=None,handoffs=[])
                        with observed_step(context,1,phase='输入绑定与模型执行') as step:
                            step.guard(); await guard()
                            request=native.request_body(**kwargs)
                            manifest=dict(parent,trace_id=context.run_id,execution_mode='coverage_'+mode,
                                parent_trace_id=revision_attempt['trace_id'] if mode=='revision' else summary['attempts'][-2]['trace_id'],
                                output_contract_version=parent['output_contract_version'] if mode=='revision' else 'business-coverage-audit-v1',
                                source_business_contract_version=parent['output_contract_version'],
                                request_sha256=base.digest(request),request_bytes=len(request),
                                system_prompt_sha256=base.digest(kwargs['system_instructions'].encode()),
                                source_wire_sha256=base.digest(kwargs['input'].encode()),source_wire_bytes=len(kwargs['input'].encode()),
                                source_wire_mode='own_candidate_inventory',output_schema_sha256=base.digest(run._json(schema).encode()),
                                input_candidate_sha256=contract.canonical_hash(draft),inventory_sha256=contract.canonical_hash(inventory),
                                dependencies_sha256=dict(dependencies),calls_max=max_attempts,retries=max_attempts-1,
                                max_request_bytes=600000,independent_evaluation=False,
                                implementation_sha256={
                                    'coverage_continuation.py':base.digest(Path(__file__).read_bytes()),
                                    'evidence_projection.py':base.digest(Path(__file__).with_name('evidence_projection.py').read_bytes()),
                                    'coverage_contract.py':base.digest(Path(contract.__file__).read_bytes()),
                                    'runtime/run_budget.py':base.digest((Path(__file__).parent.parent/'runtime/run_budget.py').read_bytes()),
                                    'runtime/call_costs.py':base.digest((Path(__file__).parent.parent/'runtime/call_costs.py').read_bytes())})
                            manifest.pop('reserved_estimated_usd',None)
                            (stage/'request.json').write_bytes(request)
                            (stage/'source_packet.json').write_bytes(prepared['packet_raw'])
                            (stage/'source_wire.json').write_text(kwargs['input'])
                            (stage/'skill.md').write_text(prepared['skill'])
                            base.write_json(stage/'manifest.json',manifest)
                            base.write_json(stage/'configuration.json',native.request_configuration(**kwargs))
                            base.write_json(stage/'output_schema.json',schema)
                            for f in stage.iterdir():
                                if f.is_file():step.publish(f)
                            meter=MeteredModel(native,stage/'model-calls','business_map_continuation_'+mode,
                                'aihubmix',parent['model'],parent['pricing_snapshot'],budget,max_request_bytes=600000)
                            try:
                                await metered_response(meter.with_observation(step),folder=stage/'transport-attempts',
                                    kwargs=kwargs,max_attempts=max_attempts,before_attempt=guard)
                            finally:
                                if native.response_text is not None:
                                    (stage/'response.txt').write_text(native.response_text);step.publish(stage/'response.txt')
                                base.write_json(stage/'response_metadata.json',native.response_metadata)
                                step.publish(stage/'response_metadata.json')
                            if (native.response_metadata.get('stop_reason')!='end_turn'
                                    or native.response_metadata.get('usage_presence')!='reported'
                                    or budget.summary()['in_flight_requests']):
                                raise ValueError('complete_reported_response_required')
                            await guard()
                            value=parse_json_object(native.response_text)
                            if mode=='revision':
                                projected,projection=project_relationship_evidence(value,packet,expected_version=parent['output_contract_version'])
                                revised=validate_draft(projected,packet,expected_version=parent['output_contract_version'])
                                draft=revised.model_dump()
                                base.write_json(stage/'projection.json',projection)
                                base.write_json(stage/'draft.json',draft)
                                counts=base.materialize(revised,packet,root=root,output=stage,manifest=manifest,trace_id=context.run_id)
                                attempt.update(status='candidate',validation='passed',counts=counts,
                                    artifacts_sha256={n:base.digest((stage/n).read_bytes()) for n in ('business_map.json','evidence.html')})
                                summary.update(candidate_path=str(stage.relative_to(root)),candidate_sha256=contract.canonical_hash(draft),
                                    self_check_status='pending_final_audit',stop_reason='revision_complete')
                            else:
                                final=contract.validate_audit(value,packet,inventory,draft)
                                before={m['mention_id'] for m in initial_audit['mappings'] if m['disposition']=='node'}
                                after={m['mention_id'] for m in final['mappings'] if m['disposition']=='node'}
                                final['regressed_mention_ids']=sorted(before-after)
                                if before-after:
                                    final['computed_status']='needs_revision'
                                    final['gaps'].append(dict(kind='lost_previously_mapped_mentions',mention_ids=sorted(before-after)))
                                base.write_json(stage/'audit.json',final)
                                attempt.update(status='completed',self_check_status=final['computed_status'])
                                summary.update(self_check_status=final['computed_status'],
                                    final_audit_candidate_sha256=contract.canonical_hash(draft),stop_reason='final_self_audit_'+final['computed_status'])
                            for f in stage.iterdir():
                                if f.is_file():step.publish(f)
                    except BaseException as error:
                        attempt.update(status='failed',stop_reason=type(error).__name__)
                        if isinstance(error,ValueError):attempt['validation_error']=str(error)[:2000]
                        summary.update(stop_reason=mode+'_failed_'+type(error).__name__,self_check_status='not_completed')
                        raise
                    finally:
                        base.write_json(stage/'result.json',dict(manifest,**attempt,semantic_acceptance='not_evaluated',
                            budget=budget.summary(),costs=summarize(stage/'model-calls') if (stage/'model-calls').exists() else None))
                        context.publish(stage/'result.json')
                for f in stage.rglob('*'):
                    if f.is_file():dependencies[str(f.relative_to(root))]=base.digest(f.read_bytes())
            finally:
                await native.aclose()
    except Exception as error:
        summary['continuation_error_type']=type(error).__name__
    finally:
        state=budget.summary()
        summary.update(budget=state,estimated_spent_usd=state['estimated_spent_usd'],unknown_requests=state['unknown_requests'],
                       in_flight_requests=state['in_flight_requests'])
        base.write_json(output/'summary.json',summary)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('root','prior-run','output','observation-root','authorization-path'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--revision-max-tokens',type=int,default=48000)
    parser.add_argument('--audit-max-tokens',type=int,default=24000)
    parser.add_argument('--max-attempts',type=int,default=2)
    args=parser.parse_args()
    from ..runtime.local_credentials import load_provider_key
    load_provider_key(args.root,'aihubmix')
    result=asyncio.run(execute(**vars(args)))
    print(json.dumps({k:result[k] for k in ('status','stop_reason','candidate_path','budget')},ensure_ascii=False))


if __name__=='__main__':main()
