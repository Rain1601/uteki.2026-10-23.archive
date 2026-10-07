"""Explicit same-ledger two-company regression; source-only independent generation."""
import argparse
import asyncio
from contextlib import closing
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT/'src'), str(ROOT)]
from uteki.agents.business_map import product_run as base, granularity_run as run
from uteki.agents.business_map import coverage_contract as inv, coverage_contract_v2 as audit_v2
from uteki.agents.business_map.coverage_run import verify_published_artifacts
from uteki.agents.business_map.product_contract import validate_draft
from uteki.agents.business_map.evidence_projection import project_business_evidence_indexes
from uteki.agents.runtime.run_budget import RunBudget
from uteki.agents.runtime.local_credentials import load_provider_key
from uteki.agents.runtime.strict_json import parse_json_object

CASES = {'microsoft':('sec-0000789019','msft-2025-10k','2025-06-30'),
         'google':('sec-0001652044','googl-2025-10k','2025-12-31')}
BUDGET = ROOT/'experiments/agent_design/2026-10-07-business-coverage-v1/run-06/budget.sqlite'
TASK_LIMIT = '8'  # User approved 2026-10-08; same ledger and all old reservations retained.
OBSERVATIONS = ROOT/'data/agent_observability/local'
MODES = {'protocol_repair':('protocol-repair-01',24000),'generation':('generation-01',24000),'inventory':('inventory-01',32000),
         'audit':('audit-01',24000),'revision':('revision-01',32000),
         'revision_from_failed_audit':('revision-01',32000),'audit_final':('audit-final-01',24000)}
# Prior 233/244-check + 148-mapping audits completed within 24k (14,550/15,498
# actual tokens). This candidate has 130 checks + 148 mappings; input is unchanged.


def selected_company_folder(prepared):
    scope=tuple(prepared['manifest'][k] for k in ('company_id','document_id','period_end'))
    matches=[name for name,value in CASES.items() if value==scope]
    if len(matches)!=1: raise ValueError('explicit_supported_case_required')
    return (HERE/matches[0]).resolve()


def request_payload(request):
    messages=request.get('messages')
    if (not isinstance(messages,list) or len(messages)!=1 or
            messages[0].get('role')!='user' or not isinstance(messages[0].get('content'),str)
            or request.get('tools') or request.get('tool_choice')):
        raise ValueError('single_own_input_without_tools_required')
    return parse_json_object(messages[0]['content'])


def settled_model_response(result, metadata, *, allow_unknown_retries=False):
    if (metadata.get('stop_reason')!='end_turn' or metadata.get('usage_presence')!='reported'
            or metadata.get('stream_complete') is not True
            or metadata.get('request_sha256')!=result['request_sha256']):
        raise ValueError('only_complete_settled_output_can_be_repaired')
    if result.get('budget_path')!=str(BUDGET.relative_to(ROOT)):
        raise ValueError('stage_must_use_same_task_ledger')
    costs=result.get('costs') or {}
    records=costs.get('records') or []
    unknown=[r for r in records if r.get('estimated_usd') is None]
    if (not records or costs.get('unknown_cost_requests')!=len(unknown)
            or (unknown and not allow_unknown_retries)):
        raise ValueError('stage_model_cost_must_be_known')
    with closing(sqlite3.connect(base.local_file(ROOT,BUDGET).as_uri()+'?mode=ro',uri=True)) as db:
        if Decimal(db.execute('SELECT usd FROM config WHERE id=1').fetchone()[0])!=Decimal(TASK_LIMIT):
            raise ValueError('same_authorized_task_ledger_required')
        rows={key:(reserved,actual,state) for key,reserved,actual,state in
              db.execute('SELECT id,reserved,actual,state FROM reservations')}
    successful=[]
    reservation_ids=[r.get('budget_reservation_id') for r in records]
    if any(not isinstance(i,str) or not i for i in reservation_ids) or len(set(reservation_ids))!=len(records):
        raise ValueError('stage_call_reservation_identity_invalid')
    for record in records:
        reserved,actual,state=rows.get(record.get('budget_reservation_id'),(None,None,None))
        if record.get('request_sha256')!=result['request_sha256']:
            raise ValueError('stage_retry_request_changed')
        if record.get('estimated_usd') is None:
            original_reserved=record.get('reserved_usd')
            if (state!='unknown' or actual is not None or reserved is None or original_reserved is None
                    or not Decimal(reserved).is_finite() or Decimal(reserved)<=0
                    or Decimal(reserved)!=Decimal(original_reserved) or record.get('status')!='failed'):
                raise ValueError('stage_unknown_retry_reservation_not_preserved')
        elif (state!='settled' or actual is None or Decimal(actual)!=Decimal(record['estimated_usd'])):
            raise ValueError('stage_model_charge_not_settled')
        if record.get('status')=='succeeded':successful.append(record)
    if (len(successful)!=1 or successful[0].get('stop_reason')!='end_turn' or
            successful[0].get('estimated_usd') is None or
            successful[0].get('response_id')!=metadata.get('response_id')):
        raise ValueError('stage_successful_response_not_bound')
    if unknown:
        try:
            final_start=datetime.fromisoformat(successful[0]['started_at'])
            for record in unknown:
                start,end=[datetime.fromisoformat(record[k]) for k in ('started_at','ended_at')]
                if not all(t.tzinfo is not None for t in (start,end,final_start)) or not start<=end<=final_start:
                    raise ValueError('stage_unknown_retry_not_before_success')
        except (KeyError,TypeError) as error:
            raise ValueError('stage_retry_timestamps_required') from error


def load_stage(path, artifact, prepared, dependencies, *, source_only=False, expected_mode=None, generation_path=None,
               revision_mode='revision'):
    path = base.local_file(ROOT,Path(path)/'result.json').parent
    result = parse_json_object((path/'result.json').read_text())
    if result['source_packet_sha256'] != prepared['manifest']['source_packet_sha256']:
        raise ValueError('prior_stage_source_mismatch')
    if base.digest((path/'source_packet.json').read_bytes()) != result['source_packet_sha256']:
        raise ValueError('prior_stage_packet_file_changed')
    if source_only:
        if result['status'] != 'completed' or result.get('execution_mode') not in ('coverage_inventory','business_products_inventory'):
            raise ValueError('source_inventory_stage_required')
    elif (path.parent != selected_company_folder(prepared) or result['skill_sha256'] != prepared['manifest']['skill_sha256']
          or expected_mode not in ('generation','protocol_repair','revision','revision_from_failed_audit','audit','audit_final')
          or result.get('execution_mode') != 'business_products_'+expected_mode
          or result['status'] not in ('completed','candidate')):
        raise ValueError('own_current_skill_stage_required')
    names = ['request.json','response.txt','source_packet.json','manifest.json',artifact]
    if not source_only or result.get('execution_mode') == 'business_products_inventory':
        names.extend(['result.json','skill.md','response_metadata.json','configuration.json','output_schema.json'])
    if (path/'projection.json').is_file(): names.append('projection.json')
    dependencies.update(verify_published_artifacts(root=ROOT,observation_root=OBSERVATIONS,
        stage=path,trace_id=result['trace_id'],relative_paths=names))
    for name in ['result.json',*names]:
        f=path/name; dependencies[str(f.relative_to(ROOT))]=base.digest(f.read_bytes())
    request = parse_json_object((path/'request.json').read_text())
    manifest = parse_json_object((path/'manifest.json').read_text())
    for key in ('source_packet_sha256','skill_sha256','execution_mode','request_sha256'):
        if result.get(key) != manifest.get(key):
            raise ValueError('stage_receipt_manifest_mismatch')
    if result['request_sha256'] != base.digest((path/'request.json').read_bytes()):
        raise ValueError('prior_stage_request_changed')
    payload = request_payload(request)
    if (not source_only or result.get('execution_mode')=='business_products_inventory') and result.get('model_calls_in_this_trace')!=0:
        settled_model_response(result,parse_json_object((path/'response_metadata.json').read_text()),allow_unknown_retries=True)
    if not source_only and base.digest((path/'skill.md').read_bytes())!=result['skill_sha256']:
        raise ValueError('stage_skill_bytes_mismatch')
    if source_only and set(payload) != {'frozen_source_packet','source_packet_sha256'}:
        raise ValueError('inventory_must_not_read_candidate_or_feedback')
    if source_only and (payload['frozen_source_packet'] != prepared['packet']
                        or payload['source_packet_sha256'] != inv.canonical_hash(prepared['packet'])):
        raise ValueError('inventory_request_source_mismatch')
    if not source_only:
        if expected_mode == 'protocol_repair':
            failed, error = load_failed(path.parent/'generation-01',prepared,dependencies)
            expected = dict(frozen_source_packet=prepared['packet'],own_failed_response=failed,
                protocol_error=error,failed_response_sha256=inv.canonical_hash(failed))
            if payload != expected: raise ValueError('repair_input_not_own_failed_output')
            expected_kwargs,_=run.request_for(prepared,'protocol_repair',own_failed_response=failed,protocol_error=error)
            if request.get('system')!=expected_kwargs['system_instructions']:
                raise ValueError('repair_system_prompt_changed')
        elif expected_mode == 'generation':
            if (payload != parse_json_object(prepared['kwargs']['input']) or
                    request.get('system')!=prepared['kwargs']['system_instructions']):
                raise ValueError('generation_request_not_source_only')
        else:
            keys={'frozen_source_packet','source_inventory','own_candidate','candidate_sha256','inventory_sha256'}
            if expected_mode=='revision_from_failed_audit':keys.update(('own_failed_audit','audit_protocol_error'))
            else:keys.add('own_audit' if expected_mode=='revision' else 'check_targets')
            if set(payload) != keys or payload['frozen_source_packet'] != prepared['packet']:
                raise ValueError('stage_request_scope_or_feedback_mismatch')
            if generation_path is None: raise ValueError('explicit_generation_path_required')
            if expected_mode=='audit_final':
                if revision_mode not in ('revision','revision_from_failed_audit'):
                    raise ValueError('explicit_supported_revision_mode_required')
                prior=load_stage(path.parent/'revision-01','draft.json',prepared,dependencies,
                                 expected_mode=revision_mode,generation_path=generation_path,revision_mode=revision_mode)
            else:
                prior = load_stage(generation_path,'draft.json',prepared,dependencies,expected_mode='protocol_repair' if generation_path.name=='protocol-repair-01' else 'generation')
            inventory = inv.validate_inventory(payload['source_inventory'],prepared['packet'])
            inventory_path=(ROOT/'experiments/agent_design/2026-10-07-business-coverage-v1/run-06/inventory'
                            if path.parent.name=='microsoft' else HERE/'google/inventory-01')
            published_inventory=load_stage(inventory_path,'inventory.json',prepared,dependencies,source_only=True)
            if inventory!=published_inventory:raise ValueError('stage_inventory_not_own_published_output')
            if (payload['own_candidate'] != prior or payload['candidate_sha256'] != inv.canonical_hash(prior)
                    or payload['inventory_sha256'] != inv.canonical_hash(inventory)):
                raise ValueError('stage_request_own_output_mismatch')
            if expected_mode in ('audit','audit_final') and payload['check_targets'] != inv.check_targets(prior):
                raise ValueError('audit_targets_mismatch')
            if expected_mode=='revision':
                prior_audit=load_stage(path.parent/'audit-01','audit.json',prepared,dependencies,
                                      expected_mode='audit',generation_path=generation_path)
                if payload['own_audit']!=prior_audit:raise ValueError('revision_audit_not_own_published_output')
            if expected_mode=='revision_from_failed_audit':
                failed_audit,error=load_failed_audit(path.parent/'audit-01',prepared,dependencies,
                                                     inventory=inventory,candidate=prior)
                if payload['own_failed_audit']!=failed_audit or payload['audit_protocol_error']!=error:
                    raise ValueError('revision_failed_audit_not_own_raw_and_machine_error')
                expected_kwargs,_=run.request_for(prepared,'revision_from_failed_audit',
                    inventory=inventory,candidate=prior,own_failed_audit=failed_audit,audit_protocol_error=error)
                if request.get('system')!=expected_kwargs['system_instructions']:
                    raise ValueError('revision_failed_audit_system_changed')
    value = parse_json_object((path/artifact).read_text())
    if artifact == 'inventory.json':
        return inv.validate_inventory(value,prepared['packet'])
    if artifact == 'audit.json':
        raw=parse_json_object((path/'response.txt').read_text())
        checked=audit_v2.validate_audit(raw,prepared['packet'],inventory,prior)
        if checked!=value:raise ValueError('audit_must_equal_verified_model_output')
    if artifact == 'draft.json':
        raw = parse_json_object((path/'response.txt').read_text())
        if (path/'projection.json').is_file():
            projected, projection = project_business_evidence_indexes(raw,prepared['packet'],expected_version='business-draft-v2')
            if projection != parse_json_object((path/'projection.json').read_text()):
                raise ValueError('projection_receipt_changed')
            raw = projected
        raw = validate_draft(raw,prepared['packet'],expected_version='business-draft-v2').model_dump()
        if raw != value: raise ValueError('candidate_must_equal_verified_model_output')
    return value


def load_failed(path, prepared, dependencies):
    path = base.local_file(ROOT,Path(path)/'result.json').parent
    if path != selected_company_folder(prepared)/'generation-01': raise ValueError('own_new_generation_required')
    result = parse_json_object((path/'result.json').read_text())
    manifest = parse_json_object((path/'manifest.json').read_text())
    names=['result.json','manifest.json','source_packet.json','skill.md','request.json','response.txt',
           'response_metadata.json','configuration.json','output_schema.json']
    dependencies.update(verify_published_artifacts(root=ROOT,observation_root=OBSERVATIONS,
        stage=path,trace_id=result['trace_id'],relative_paths=names))
    if result['status']!='failed' or result['execution_mode']!='business_products_generation':
        raise ValueError('failed_generation_required')
    if manifest.get('execution_mode')!=result['execution_mode']:
        raise ValueError('failed_generation_mode_mismatch')
    for key in ('source_packet_sha256','skill_sha256'):
        if result[key]!=prepared['manifest'][key] or manifest[key]!=result[key]:
            raise ValueError('failed_generation_scope_mismatch')
    if base.digest((path/'source_packet.json').read_bytes())!=result['source_packet_sha256']:
        raise ValueError('failed_packet_changed')
    if base.digest((path/'skill.md').read_bytes())!=result['skill_sha256']:
        raise ValueError('failed_skill_changed')
    request_raw=(path/'request.json').read_bytes()
    if base.digest(request_raw)!=result['request_sha256'] or result['request_sha256']!=manifest['request_sha256']:
        raise ValueError('failed_request_changed')
    request=parse_json_object(request_raw.decode())
    if (request_payload(request)!=parse_json_object(prepared['kwargs']['input']) or
            request.get('system')!=prepared['kwargs']['system_instructions']):
        raise ValueError('failed_generation_not_source_only')
    metadata=parse_json_object((path/'response_metadata.json').read_text())
    settled_model_response(result,metadata)
    value=parse_json_object((path/'response.txt').read_text())
    try: validate_draft(value,prepared['packet'],expected_version='business-draft-v2')
    except ValueError as error:
        if result.get('stop_reason')!='ValueError' or result.get('validation_error')!=str(error)[:2400]:
            raise ValueError('failed_receipt_not_actual_contract_error') from error
    else: raise ValueError('already_valid_response_needs_no_protocol_repair')
    try: project_business_evidence_indexes(value,prepared['packet'],expected_version='business-draft-v2')
    except ValueError as error: return value,str(error)
    raise ValueError('already_valid_response_needs_no_protocol_repair')


def load_failed_audit(path, prepared, dependencies, *, inventory, candidate):
    """Bind a failed review as untrusted model feedback, never as a valid audit."""
    path=base.local_file(ROOT,Path(path)/'result.json').parent
    if path!=selected_company_folder(prepared)/'audit-01':
        raise ValueError('own_new_initial_audit_required')
    result=parse_json_object((path/'result.json').read_text())
    manifest=parse_json_object((path/'manifest.json').read_text())
    names=['result.json','manifest.json','source_packet.json','skill.md','request.json','response.txt',
           'response_metadata.json','configuration.json','output_schema.json']
    dependencies.update(verify_published_artifacts(root=ROOT,observation_root=OBSERVATIONS,
        stage=path,trace_id=result['trace_id'],relative_paths=names))
    if result.get('status')!='failed' or result.get('execution_mode')!='business_products_audit':
        raise ValueError('failed_initial_audit_required')
    for key in ('company_id','document_id','period_end','source_packet_sha256','skill_sha256'):
        if result.get(key)!=prepared['manifest'][key] or manifest.get(key)!=result[key]:
            raise ValueError('failed_audit_scope_mismatch')
    for key in ('execution_mode','request_sha256'):
        if manifest.get(key)!=result[key]:raise ValueError('failed_audit_receipt_manifest_mismatch')
    for name,key in [('source_packet.json','source_packet_sha256'),('skill.md','skill_sha256'),('request.json','request_sha256')]:
        if base.digest((path/name).read_bytes())!=result[key]:raise ValueError('failed_audit_bytes_changed')
    request=parse_json_object((path/'request.json').read_text())
    expected_kwargs,_=run.request_for(prepared,'audit',inventory=inventory,candidate=candidate)
    if (request_payload(request)!=parse_json_object(expected_kwargs['input']) or
            request.get('system')!=expected_kwargs['system_instructions']):
        raise ValueError('failed_audit_request_not_own_source_inventory_candidate')
    settled_model_response(result,parse_json_object((path/'response_metadata.json').read_text()))
    raw=parse_json_object((path/'response.txt').read_text())
    # Require complete structural output before exposing semantic validator feedback.
    shaped=audit_v2.Audit.model_validate(raw)
    mapping_ids=[m.mention_id for m in shaped.mappings]
    check_keys=[c.check_key for c in shaped.checks]
    if (shaped.candidate_sha256!=inv.canonical_hash(candidate) or
            shaped.inventory_sha256!=inv.canonical_hash(inventory) or
            len(mapping_ids)!=len(set(mapping_ids)) or set(mapping_ids)!={m['id'] for m in inventory['mentions']} or
            len(check_keys)!=len(set(check_keys)) or set(check_keys)!={t['check_key'] for t in inv.check_targets(candidate)}):
        raise ValueError('failed_audit_complete_bound_ledger_required')
    try: audit_v2.validate_audit(raw,prepared['packet'],inventory,candidate)
    except ValueError as error:
        if result.get('stop_reason')!='ValueError' or result.get('validation_error')!=str(error)[:2400]:
            raise ValueError('failed_audit_receipt_not_actual_machine_error') from error
        return raw,str(error)
    raise ValueError('valid_audit_must_use_regular_revision')


async def main():
    ap=argparse.ArgumentParser(); ap.add_argument('company',choices=CASES)
    ap.add_argument('mode',choices=MODES); ap.add_argument('--execute',action='store_true')
    ap.add_argument('--generation-stage',choices=('generation-01','generation-01-indexed','protocol-repair-01'),default='generation-01')
    ap.add_argument('--revision-mode',choices=('revision','revision_from_failed_audit'),default='revision',
                    help='Exact revision provenance expected when consuming revision-01 for audit_final.')
    args=ap.parse_args()
    generation_path = HERE/args.company/args.generation_stage
    folder,tokens = MODES[args.mode]
    company,document,period = CASES[args.company]
    output = HERE/args.company/folder
    if output.exists(): raise ValueError('stage_already_exists_do_not_resubmit')
    prepared = base.prepare(root=ROOT,packet_path=HERE/args.company/'source_packet.json',
        skill_path=HERE/'skill.md',company_id=company,document_id=document,period_end=period,
        model='claude-sonnet-5-5',effort='high',max_tokens=tokens,timeout_seconds=600,
        stream=True,contract_version='business-draft-v2',thinking_type='between_tools')
    try:
        dependencies = {str(f.relative_to(ROOT)):base.digest(f.read_bytes()) for f in
            [HERE/args.company/'source_packet.json',HERE/'skill.md',HERE/'budget-authorization-5-to-8.json',Path(__file__),Path(run.__file__),Path(audit_v2.__file__)]}
        inventory=candidate=audit=None
        own_failed_response=protocol_error=None
        own_failed_audit=audit_protocol_error=None
        if args.mode == 'protocol_repair':
            own_failed_response,protocol_error = load_failed(HERE/args.company/'generation-01',prepared,dependencies)
        if args.mode in {'audit','revision','revision_from_failed_audit','audit_final'}:
            ipath = (ROOT/'experiments/agent_design/2026-10-07-business-coverage-v1/run-06/inventory'
                     if args.company=='microsoft' else HERE/'google/inventory-01')
            inventory = load_stage(ipath,'inventory.json',prepared,dependencies,source_only=True)
            candidate = load_stage((HERE/args.company/'revision-01' if args.mode=='audit_final' else generation_path),
                                   'draft.json',prepared,dependencies,expected_mode=args.revision_mode if args.mode=='audit_final' else ('protocol_repair' if args.generation_stage=='protocol-repair-01' else 'generation'),generation_path=generation_path,revision_mode=args.revision_mode)
        if args.mode=='revision':
            audit = load_stage(HERE/args.company/'audit-01','audit.json',prepared,dependencies,expected_mode='audit',generation_path=generation_path)
        if args.mode=='revision_from_failed_audit':
            own_failed_audit,audit_protocol_error=load_failed_audit(HERE/args.company/'audit-01',prepared,
                dependencies,inventory=inventory,candidate=candidate)
        kwargs,schema = run.request_for(prepared,args.mode,inventory=inventory,candidate=candidate,audit=audit,own_failed_response=own_failed_response,protocol_error=protocol_error,
            own_failed_audit=own_failed_audit,audit_protocol_error=audit_protocol_error)
        budget = RunBudget(base.local_file(ROOT,BUDGET),TASK_LIMIT,allow_unknown_reservations=True)
        preflight = run.preflight(prepared,kwargs,budget)
        preflight.update(mode=args.mode,company=args.company,source_packet_sha256=prepared['manifest']['source_packet_sha256'],
            skill_sha256=prepared['manifest']['skill_sha256'],budget_path=str(BUDGET.relative_to(ROOT)),
            task_limit_changed=True,authorization_record='budget-authorization-5-to-8.json',semantic_revisions_max_per_company=1,dependencies=dependencies,
            generation_stage=args.generation_stage,revision_mode=args.revision_mode)
        base.write_json(HERE/args.company/(folder+'-preflight.json'),preflight)
        print(json.dumps({k:preflight[k] for k in ('company','mode','request_bytes','reserved_estimated_usd','remaining_usd','fits')},ensure_ascii=False),flush=True)
        if not args.execute: return
        if not preflight['fits']: raise ValueError('same_task_budget_requires_user_decision_before_dispatch')
        load_provider_key(ROOT,'aihubmix')
        result = await run.execute_stage(prepared,root=ROOT,output=output,observation_root=OBSERVATIONS,
            budget_path=BUDGET,budget_limit_usd=TASK_LIMIT,mode=args.mode,dependencies=dependencies,
            inventory=inventory,candidate=candidate,audit=audit,own_failed_response=own_failed_response,protocol_error=protocol_error,
            own_failed_audit=own_failed_audit,audit_protocol_error=audit_protocol_error,max_attempts=2)
        print(json.dumps({k:result.get(k) for k in ('status','trace_id','self_check_status','counts','budget')},ensure_ascii=False))
    finally:
        await prepared['native'].aclose()

if __name__=='__main__': asyncio.run(main())
