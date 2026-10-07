"""One observed, metered Sonnet patch from its own candidate and a bound Opus review."""
import argparse
import asyncio
from contextlib import closing
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import run_stage as stages
import critic_envelope

from uteki.agents.business_map import critic_revision as patcher, semantic_critic as critic
from uteki.agents.business_map import evidence_projection, product_contract, coverage_contract, coverage_contract_v2
from uteki.agents.runtime import bounded_retry, call_costs, observation, run_budget, strict_json

base=stages.base
parse=strict_json.parse_json_object


class ReadOnlyBudget:
    """Preflight may read the existing ledger; it cannot initialize or mutate it."""
    def summary(self):
        path=base.local_file(stages.ROOT,stages.BUDGET)
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            limit=db.execute('SELECT usd FROM config WHERE id=1').fetchone()[0]
            rows=db.execute('SELECT reserved,actual,state FROM reservations').fetchall()
        if Decimal(limit)!=Decimal(stages.TASK_LIMIT):raise ValueError('same_authorized_task_limit_required')
        return dict(limit_usd=limit,estimated_spent_usd=str(sum((Decimal(a) for _,a,s in rows if s=='settled'),Decimal(0))),
            held_usd=str(sum((Decimal(r) for r,_,s in rows if s!='settled'),Decimal(0))),
            unknown_requests=sum(s=='unknown' for _,_,s in rows),in_flight_requests=sum(s=='reserved' for _,_,s in rows),
            requests=len(rows),actual_billed_usd=None,enforcement='enforced')


def modules():
    paths=[Path(__file__).resolve(),*(Path(m.__file__).resolve() for m in
        (stages,patcher,critic,critic_envelope,evidence_projection,product_contract,coverage_contract,coverage_contract_v2,
         bounded_retry,call_costs,observation,run_budget,strict_json))]
    return {str(p.relative_to(stages.ROOT)):base.digest(p.read_bytes()) for p in paths}


def frozen_origin(path,candidate):
    manifest=parse((path/'manifest.json').read_text())
    metadata=parse((path/'response_metadata.json').read_text())
    return dict(candidate_path=str((path/'draft.json').relative_to(stages.ROOT)),
        candidate_file_sha256=base.digest((path/'draft.json').read_bytes()),candidate_sha256=stages.inv.canonical_hash(candidate),
        trace_id=manifest['trace_id'],requested_model=manifest['model'],actual_upstream_model=metadata['actual_upstream_model'],
        manifest_path=str((path/'manifest.json').relative_to(stages.ROOT)),
        response_metadata_path=str((path/'response_metadata.json').relative_to(stages.ROOT)))


def validate_lineage(output_stage,candidate_stage,critic_stage):
    expected={'critic-revision-01':('revision-01','opus-critic-02'),
              'critic-revision-02':('critic-revision-01','opus-critic-03')}
    if expected.get(output_stage)!=(candidate_stage,critic_stage):
        raise ValueError('explicit_forward_patch_lineage_required')


async def load_inputs(prepared,dependencies,critic_stage,critic_recovery=None,*,candidate_stage='revision-01',_visited=()):
    company_path=stages.selected_company_folder(prepared)
    candidate_path=company_path/candidate_stage
    if candidate_stage=='revision-01':
        candidate=stages.load_stage(candidate_path,'draft.json',prepared,dependencies,
            expected_mode='revision_from_failed_audit',generation_path=company_path/'protocol-repair-01',
            revision_mode='revision_from_failed_audit')
    elif candidate_stage=='critic-revision-01':
        candidate=await load_patch_stage(candidate_path,prepared,dependencies,_visited=_visited)
    else:raise ValueError('explicit_own_candidate_stage_required')
    review,origin=await load_critic_review(company_path/critic_stage,prepared,dependencies,
                                          candidate=candidate,candidate_path=candidate_path,recovery_path=critic_recovery)
    return candidate,review,dict(candidate=frozen_origin(candidate_path,candidate),critic=origin)


async def load_critic_review(path,prepared,dependencies,*,candidate,candidate_path,recovery_path=None):
    path=base.local_file(stages.ROOT,Path(path)/'result.json').parent
    if path.parent!=stages.selected_company_folder(prepared) or path.name not in ('opus-critic-01','opus-critic-02','opus-critic-03'):
        raise ValueError('explicit_own_opus_critic_stage_required')
    result=parse((path/'result.json').read_text()); manifest=parse((path/'manifest.json').read_text())
    names=['result.json','manifest.json','response.txt','response_metadata.json','request.json',
           'source_packet.json','skill.md','candidate.json','candidate_origin.json','check_targets.json',
           'configuration.json','output_schema.json']
    if recovery_path is None:
        names.append('review.json')
        if 'check_target_format' in result:names.append('syntax-envelope.json')
    dependencies.update(stages.verify_published_artifacts(root=stages.ROOT,observation_root=stages.OBSERVATIONS,
        stage=path,trace_id=result['trace_id'],relative_paths=names))
    recovering=recovery_path is not None
    if (result.get('execution_mode')!='business_semantic_critic' or
            (not recovering and result.get('status')!='completed') or
            (recovering and (result.get('status')!='failed' or
                             result.get('validation_error')!='JSON output rejected: invalid_json'))):
        raise ValueError('completed_critic_required')
    for key in ('company_id','document_id','period_end','source_packet_sha256','skill_sha256'):
        if result.get(key)!=prepared['manifest'][key] or manifest.get(key)!=result[key]:
            raise ValueError('critic_scope_mismatch')
    for key in ('request_sha256','execution_mode','model','trace_id','candidate_origin'):
        if manifest.get(key)!=result.get(key):raise ValueError('critic_receipt_manifest_mismatch')
    for name,key in [('source_packet.json','source_packet_sha256'),('skill.md','skill_sha256'),('request.json','request_sha256')]:
        if base.digest((path/name).read_bytes())!=result[key]:raise ValueError('critic_frozen_bytes_changed')
    request=parse((path/'request.json').read_text())
    metadata=parse((path/'response_metadata.json').read_text())
    stages.settled_model_response(result,metadata,allow_unknown_retries=True)
    if request.get('model')!='claude-opus-5-5' or result['model']!='claude-opus-5-5':
        raise ValueError('selected_opus_model_required')
    origin=frozen_origin(candidate_path,candidate)
    if (manifest['candidate_origin']!=origin or parse((path/'candidate_origin.json').read_text())!=origin or
            (path/'candidate.json').read_bytes()!=(candidate_path/'draft.json').read_bytes()):
        raise ValueError('critic_candidate_producer_mismatch')
    if parse((path/'candidate.json').read_text())!=candidate:
        raise ValueError('critic_candidate_mismatch')
    # Recreate the complete source-only Opus request, including its system/Skill.
    # Creating/closing this adapter performs no HTTP request.
    original=base.prepare(root=stages.ROOT,packet_path=stages.HERE/company_path_name(prepared)/'source_packet.json',
        skill_path=stages.HERE/'skill.md',**{k:prepared['manifest'][k] for k in ('company_id','document_id','period_end')},
        model='claude-opus-5-5',effort='high',max_tokens=request['max_tokens'],timeout_seconds=600,
        stream=True,contract_version='business-draft-v2',thinking_type='adaptive')
    try:
        kwargs,schema=critic.request_for(original,candidate,target_format=result.get('check_target_format','full'))
        if original['native'].request_body(**kwargs)!=(path/'request.json').read_bytes():
            raise ValueError('critic_actual_request_not_source_candidate_only')
        if schema!=parse((path/'output_schema.json').read_text()):raise ValueError('critic_schema_mismatch')
    finally:await original['native'].aclose()
    if json.loads((path/'check_targets.json').read_text())!=stages.inv.check_targets(candidate):
        raise ValueError('critic_targets_mismatch')
    recovery_origin={}
    if recovering:
        recovery_path=base.local_file(stages.ROOT,recovery_path)
        if recovery_path.parent!=path.parent:raise ValueError('recovery_must_belong_to_selected_company')
        receipt=parse(recovery_path.read_text())
        expected_names={'response.txt','response_metadata.json','result.json','request.json','source_packet.json','candidate.json','manifest.json'}
        if (receipt.get('schema_version')!='business-critic-envelope-recovery-v1' or
                receipt.get('method')!='remove_single_complete_json_code_fence' or
                receipt.get('original_stage')!=str(path.relative_to(stages.ROOT)) or
                set(receipt.get('original_artifact_sha256',{}))!=expected_names or
                receipt.get('recovery_implementation_sha256')!=base.digest(Path(critic_envelope.__file__).read_bytes())):
            raise ValueError('explicit_lossless_recovery_receipt_required')
        for name,expected in receipt['original_artifact_sha256'].items():
            if base.digest((path/name).read_bytes())!=expected:raise ValueError('recovery_original_hash_mismatch')
        review=critic.validate_review(critic_envelope.unwrap_json_fence((path/'response.txt').read_text()),prepared['packet'],candidate)
        if (review!=receipt.get('review') or receipt.get('original_stage_status')!='failed' or
                receipt.get('recovered_contract_status')!='passed' or receipt.get('model_review_status')!=review['status'] or
                receipt.get('independent_acceptance') is not False or receipt.get('semantic_acceptance')!='not_evaluated'):
            raise ValueError('recovered_review_not_exact_original_content')
        receipt_hash=base.digest(recovery_path.read_bytes())
        dependencies[str(recovery_path.relative_to(stages.ROOT))]=receipt_hash
        dependencies[str(Path(critic_envelope.__file__).resolve().relative_to(stages.ROOT))]=base.digest(Path(critic_envelope.__file__).read_bytes())
        recovery_origin=dict(recovery_path=str(recovery_path.relative_to(stages.ROOT)),recovery_sha256=receipt_hash,
                             original_stage_status='failed',materialization_mode='single_json_fence_removal')
    else:
        value,envelope=critic.parse_review_response((path/'response.txt').read_text())
        if 'check_target_format' in result:
            if envelope!=parse((path/'syntax-envelope.json').read_text()):raise ValueError('critic_syntax_envelope_changed')
        elif envelope['method']!='strict_json':raise ValueError('explicit_lossless_recovery_receipt_required')
        review=critic.validate_review(value,prepared['packet'],candidate)
        if (review!=parse((path/'review.json').read_text()) or
                result.get('artifact_sha256')!=base.digest((path/'review.json').read_bytes())):
            raise ValueError('critic_review_not_original_response')
        recovery_origin=dict(review_file_sha256=base.digest((path/'review.json').read_bytes()))
    return review,dict(stage=str(path.relative_to(stages.ROOT)),trace_id=result['trace_id'],model=result['model'],
        review_sha256=stages.inv.canonical_hash(review),response_sha256=base.digest((path/'response.txt').read_bytes()),**recovery_origin)


def company_path_name(prepared):return stages.selected_company_folder(prepared).name


def patch_response(text):
    method='strict_json'
    try:value=parse(text)
    except ValueError as strict_error:
        try:value=critic_envelope.unwrap_json_fence(text)
        except ValueError:raise strict_error
        method='remove_single_complete_json_code_fence'
    return value,dict(schema_version='business-patch-syntax-envelope-v1',method=method,
                       raw_response_sha256=base.digest(text.encode()),semantic_changes=False)


def verify(prepared,dependencies,kwargs,raw):
    base.verify_prepared(prepared)
    base.verify_packet(prepared['packet'],stages.ROOT,
        **{k:prepared['manifest'][k] for k in ('company_id','document_id','period_end')},contract_version='business-draft-v2')
    for key,expected in dependencies.items():
        if base.digest(base.local_file(stages.ROOT,key).read_bytes())!=expected:raise ValueError('frozen_dependency_changed')
    if prepared['native'].request_body(**kwargs)!=raw:raise ValueError('patch_request_changed')


async def execute(prepared,*,output,candidate,review,origins,dependencies,kwargs,schema):
    if output.exists() or output.parent!=stages.selected_company_folder(prepared):
        raise ValueError('new_single_critic_revision_stage_required')
    validate_lineage(output.name,Path(origins['candidate']['candidate_path']).parent.name,Path(origins['critic']['stage']).name)
    candidate,review,origins,dependencies=deepcopy((candidate,review,origins,dependencies))
    actual_kwargs,actual_schema=patcher.request_for(prepared,candidate=candidate,critic=review)
    raw=prepared['native'].request_body(**actual_kwargs)
    if raw!=prepared['native'].request_body(**kwargs) or actual_schema!=schema:
        raise ValueError('patch_request_must_match_verified_inputs')
    kwargs,schema=actual_kwargs,actual_schema
    verify(prepared,dependencies,kwargs,raw)
    budget=critic._existing_budget(stages.ROOT,stages.BUDGET,stages.TASK_LIMIT)
    if not critic.preflight(prepared,kwargs,budget)['fits']:raise ValueError('same_task_budget_requires_user_decision_before_dispatch')
    native=prepared['native']; manifest=deepcopy(prepared['manifest'])
    manifest.pop('reserved_estimated_usd',None)
    manifest.update(execution_mode='business_critic_revision',output_contract_version='business-critic-revision-patch-v1',
        candidate_output_contract_version='business-draft-v2',request_sha256=base.digest(raw),request_bytes=len(raw),
        output_schema_sha256=base.digest(json.dumps(schema,ensure_ascii=False).encode()),
        source_wire_sha256=base.digest(kwargs['input'].encode()),source_wire_mode='frozen_source_own_candidate_opus_critic',
        source_wire_bytes=len(kwargs['input'].encode()),input_scope='frozen_source_and_bound_candidate_critic',
        origins=origins,dependencies=dependencies,calls_max=2,retries=1,semantic_revisions_max=1,
        semantic_acceptance='not_evaluated',independent_acceptance=False,requires_fresh_review=True)
    result=dict(manifest,status='failed',budget_path=str(stages.BUDGET.relative_to(stages.ROOT)))
    with observation.observed_run(output=output,kind='extraction',role='extractor',origin='business_critic_revision',
            observation_root=stages.OBSERVATIONS,scope={k:manifest[k] for k in ('company_id','period_end','task_type')},
            title='根据独立批评逐对象修订') as context, critic._receipt(output,result,budget,context):
        output.mkdir(parents=True,exist_ok=False)
        manifest['trace_id']=result['trace_id']=context.run_id
        with observation.observed_step(context,1,phase='核对原候选与独立批评') as step:
            verify(prepared,dependencies,kwargs,raw);step.guard()
            (output/'source_packet.json').write_bytes(prepared['packet_raw'])
            (output/'skill.md').write_text(prepared['skill']);(output/'request.json').write_bytes(raw)
            for name,value in {'manifest.json':manifest,'output_schema.json':schema,'candidate.json':candidate,
                    'critic.json':review,'origins.json':origins,'configuration.json':native.request_configuration(**kwargs)}.items():
                base.write_json(output/name,value)
            for path in output.iterdir():
                if path.is_file():step.publish(path)
        meter=call_costs.MeteredModel(native,output/'model-calls','business_critic_revision','aihubmix',
            manifest['model'],manifest['pricing_snapshot'],budget,max_request_bytes=600000)
        async def before_attempt():verify(prepared,dependencies,kwargs,raw)
        with observation.observed_step(context,2,phase='系统模型生成对象补丁') as step:
            try:
                await bounded_retry.metered_response(meter.with_observation(step),folder=output/'transport-attempts',
                    kwargs=kwargs,max_attempts=2,before_attempt=before_attempt)
            finally:
                if native.response_text is not None:
                    (output/'response.txt').write_text(native.response_text);step.publish(output/'response.txt')
                base.write_json(output/'response_metadata.json',native.response_metadata);step.publish(output/'response_metadata.json')
        verify(prepared,dependencies,kwargs,raw)
        if (not native.response_metadata or native.response_metadata.get('stop_reason')!='end_turn'
                or native.response_metadata.get('usage_presence')!='reported' or budget.summary()['in_flight_requests']):
            raise ValueError('complete_response_and_settled_cost_required')
        with observation.observed_step(context,3,phase='重放补丁并校验新候选') as step:
            value,envelope=patch_response(native.response_text)
            base.write_json(output/'syntax-envelope.json',envelope);step.publish(output/'syntax-envelope.json')
            base.write_json(output/'patch.json',value);step.publish(output/'patch.json')
            revised,receipt=patcher.apply_patch(value,prepared['packet'],candidate,review)
            draft=stages.validate_draft(revised,prepared['packet'],expected_version='business-draft-v2')
            verify(prepared,dependencies,kwargs,raw);step.guard()
            counts=base.materialize(draft,prepared['packet'],root=stages.ROOT,output=output,manifest=manifest,trace_id=context.run_id)
            base.write_json(output/'draft.json',revised);base.write_json(output/'diff.json',receipt)
            verify(prepared,dependencies,kwargs,raw)
            for name in ('draft.json','diff.json','business_map.json','evidence.html'):step.publish(output/name)
            result.update(status='candidate',stop_reason='end_turn',contract_validation='passed',counts=counts,
                artifact='draft.json',artifact_sha256=base.digest((output/'draft.json').read_bytes()),
                self_check_status='pending_fresh_critic',issue_resolution='not_evaluated')
    return result


async def load_patch_stage(path,prepared,deps,*,_visited=()):
    """For a fresh critic: bind the whole lineage and replay original raw patch."""
    path=base.local_file(stages.ROOT,Path(path)/'result.json').parent
    if path.parent!=stages.selected_company_folder(prepared) or path.name not in ('critic-revision-01','critic-revision-02'):
        raise ValueError('own_patch_stage_required')
    if path in _visited:raise ValueError('patch_lineage_cycle')
    _visited=(*_visited,path)
    result=parse((path/'result.json').read_text());manifest=parse((path/'manifest.json').read_text())
    names=['result.json','manifest.json','source_packet.json','skill.md','request.json','response.txt','response_metadata.json',
           'candidate.json','critic.json','origins.json','patch.json','diff.json','draft.json','business_map.json','evidence.html',
           'output_schema.json','configuration.json','syntax-envelope.json']
    deps.update(stages.verify_published_artifacts(root=stages.ROOT,observation_root=stages.OBSERVATIONS,
        stage=path,trace_id=result['trace_id'],relative_paths=names))
    if result.get('status')!='candidate' or result.get('execution_mode')!='business_critic_revision':raise ValueError('complete_patch_stage_required')
    for key in ('company_id','document_id','period_end','source_packet_sha256','skill_sha256'):
        if result.get(key)!=prepared['manifest'][key] or manifest.get(key)!=result[key]:raise ValueError('patch_stage_scope_mismatch')
    for key in ('origins','request_sha256','execution_mode','model','trace_id'):
        if result.get(key)!=manifest.get(key):raise ValueError('patch_stage_receipt_manifest_mismatch')
    stages.settled_model_response(result,parse((path/'response_metadata.json').read_text()),allow_unknown_retries=True)
    candidate_path=base.local_file(stages.ROOT,manifest['origins']['candidate']['candidate_path'])
    critic_path=base.local_file(stages.ROOT,Path(manifest['origins']['critic']['stage'])/'result.json').parent
    if candidate_path.parent.parent!=path.parent or candidate_path.name!='draft.json' or critic_path.parent!=path.parent:
        raise ValueError('patch_lineage_scope_mismatch')
    validate_lineage(path.name,candidate_path.parent.name,critic_path.name)
    candidate,review,origins=await load_inputs(prepared,deps,critic_path.name,
        manifest['origins']['critic'].get('recovery_path'),candidate_stage=candidate_path.parent.name,_visited=_visited)
    if origins!=manifest['origins'] or origins!=parse((path/'origins.json').read_text()):raise ValueError('patch_origins_changed')
    if candidate!=parse((path/'candidate.json').read_text()) or review!=parse((path/'critic.json').read_text()):raise ValueError('patch_original_inputs_changed')
    kwargs,schema=patcher.request_for(prepared,candidate=candidate,critic=review)
    request=parse((path/'request.json').read_text())
    if (stages.request_payload(request)!=parse(kwargs['input']) or request.get('system')!=kwargs['system_instructions']
            or base.digest((path/'request.json').read_bytes())!=result['request_sha256']
            or request.get('model')!=result['model'] or result['model']!='claude-sonnet-5-5'):
        raise ValueError('patch_actual_request_mismatch')
    value,envelope=patch_response((path/'response.txt').read_text())
    if envelope!=parse((path/'syntax-envelope.json').read_text()):raise ValueError('patch_syntax_envelope_changed')
    if value!=parse((path/'patch.json').read_text()):raise ValueError('patch_not_raw_model_response')
    revised,receipt=patcher.apply_patch(value,prepared['packet'],candidate,review)
    if (revised!=parse((path/'draft.json').read_text()) or
            stages.inv.canonical_hash(receipt)!=stages.inv.canonical_hash(parse((path/'diff.json').read_text()))
            or result['artifact_sha256']!=base.digest((path/'draft.json').read_bytes())):
        raise ValueError('patched_candidate_or_receipt_not_replayed')
    return revised


async def main():
    ap=argparse.ArgumentParser();ap.add_argument('company',choices=('microsoft',))
    ap.add_argument('--critic-stage',required=True,choices=('opus-critic-02','opus-critic-03'))
    ap.add_argument('--candidate-stage',choices=('revision-01','critic-revision-01'),default='revision-01')
    ap.add_argument('--output-stage',choices=('critic-revision-01','critic-revision-02'),default='critic-revision-01')
    ap.add_argument('--max-tokens',type=int,choices=(16000,32000),default=32000)
    ap.add_argument('--critic-recovery',help='Explicit lossless single-fence recovery receipt; failed stages are otherwise rejected.')
    ap.add_argument('--execute',action='store_true');args=ap.parse_args()
    validate_lineage(args.output_stage,args.candidate_stage,args.critic_stage)
    company,document,period=stages.CASES[args.company];output=stages.HERE/args.company/args.output_stage
    if output.exists():raise ValueError('stage_already_exists_do_not_resubmit')
    prepared=base.prepare(root=stages.ROOT,packet_path=stages.HERE/args.company/'source_packet.json',
        skill_path=stages.HERE/'skill.md',company_id=company,document_id=document,period_end=period,
        model='claude-sonnet-5-5',effort='high',max_tokens=args.max_tokens,timeout_seconds=600,stream=True,
        contract_version='business-draft-v2',thinking_type='between_tools')
    try:
        deps=modules()
        for path in (stages.HERE/args.company/'source_packet.json',stages.HERE/'skill.md',stages.HERE/'budget-authorization-5-to-8.json'):
            deps[str(path.relative_to(stages.ROOT))]=base.digest(path.read_bytes())
        candidate,review,origins=await load_inputs(prepared,deps,args.critic_stage,args.critic_recovery,candidate_stage=args.candidate_stage)
        kwargs,schema=patcher.request_for(prepared,candidate=candidate,critic=review)
        raw=prepared['native'].request_body(**kwargs);verify(prepared,deps,kwargs,raw)
        preflight=critic.preflight(prepared,kwargs,ReadOnlyBudget())
        preflight.update(company=args.company,model='claude-sonnet-5-5',origins=origins,dependencies=deps,
                         output_max_tokens=args.max_tokens,semantic_acceptance='not_evaluated',requires_fresh_review=True)
        base.write_json(output.with_name(output.name+'-preflight.json'),preflight)
        output.with_name(output.name+'-request.preview.json').write_bytes(raw)
        print(json.dumps({k:preflight[k] for k in ('model','request_bytes','reserved_estimated_usd','remaining_usd','fits')}),flush=True)
        if not args.execute:return
        if not preflight['fits']:raise ValueError('same_task_budget_requires_user_decision_before_dispatch')
        stages.load_provider_key(stages.ROOT,'aihubmix')
        result=await execute(prepared,output=output,candidate=candidate,review=review,origins=origins,
                             dependencies=deps,kwargs=kwargs,schema=schema)
        print(json.dumps({k:result.get(k) for k in ('status','trace_id','counts','budget')},ensure_ascii=False))
    finally:await prepared['native'].aclose()


if __name__=='__main__':asyncio.run(main())
