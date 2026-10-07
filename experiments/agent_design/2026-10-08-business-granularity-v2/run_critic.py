"""Explicit source/candidate-only Opus review of a published system candidate."""
import argparse
import asyncio
import json
from pathlib import Path
import run_stage as stages
from uteki.agents.business_map import semantic_critic as critic

async def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('company',choices=stages.CASES)
    ap.add_argument('--candidate-stage',required=True,choices=('generation-01','protocol-repair-01','revision-01','critic-revision-01','critic-revision-02'))
    ap.add_argument('--generation-stage',required=True,choices=('generation-01','protocol-repair-01'))
    ap.add_argument('--revision-mode',choices=('revision','revision_from_failed_audit'),default='revision')
    ap.add_argument('--execute',action='store_true')
    ap.add_argument('--output-name',choices=('opus-critic-01','opus-critic-02','opus-critic-03','opus-critic-04'),default='opus-critic-01')
    ap.add_argument('--max-tokens',type=int,choices=(8000,16000),default=8000)
    ap.add_argument('--target-format',choices=('full','pointers-v1'),default='full')
    args=ap.parse_args()
    company,document,period=stages.CASES[args.company]
    output=stages.HERE/args.company/args.output_name
    if output.exists():raise ValueError('stage_already_exists_do_not_resubmit')
    prepared=stages.base.prepare(root=stages.ROOT,packet_path=stages.HERE/args.company/'source_packet.json',
        skill_path=stages.HERE/'skill.md',company_id=company,document_id=document,period_end=period,
        model='claude-opus-5-5',effort='high',max_tokens=args.max_tokens,timeout_seconds=600,stream=True,
        contract_version='business-draft-v2',thinking_type='adaptive')
    try:
        deps={str(f.relative_to(stages.ROOT)):stages.base.digest(f.read_bytes()) for f in
            [Path(__file__).resolve(),Path(stages.__file__),Path(critic.__file__),
             stages.HERE/'budget-authorization-5-to-8.json',stages.HERE/args.company/'source_packet.json']}
        path=stages.HERE/args.company/args.candidate_stage
        expected=args.revision_mode if args.candidate_stage=='revision-01' else 'protocol_repair' if args.candidate_stage=='protocol-repair-01' else 'generation'
        if args.candidate_stage in ('critic-revision-01','critic-revision-02'):
            import run_critic_revision as patch_stage
            deps.update(patch_stage.modules())
            candidate=await patch_stage.load_patch_stage(path,prepared,deps)
        else:
            candidate=stages.load_stage(path,'draft.json',prepared,deps,expected_mode=expected,
                generation_path=stages.HERE/args.company/args.generation_stage,revision_mode=args.revision_mode)
        kwargs,schema=critic.request_for(prepared,candidate,target_format=args.target_format)
        budget=critic._existing_budget(stages.ROOT,stages.BUDGET,stages.TASK_LIMIT)
        preflight=critic.preflight(prepared,kwargs,budget)
        preflight.update(company=args.company,model='claude-opus-5-5',candidate_path=str(path.relative_to(stages.ROOT)),
            dependencies=deps,independent_acceptance=False,source_only_review=True)
        stages.base.write_json(output.with_name(output.name+'-preflight.json'),preflight)
        raw=prepared['native'].request_body(**kwargs)
        output.with_name(output.name+'-request.preview.json').write_bytes(raw)
        print(json.dumps({k:preflight[k] for k in ('model','request_bytes','reserved_estimated_usd','remaining_usd','fits')}),flush=True)
        if not args.execute:return
        if not preflight['fits']:raise ValueError('same_task_budget_requires_user_decision_before_dispatch')
        stages.load_provider_key(stages.ROOT,'aihubmix')
        result=await critic.execute_stage(prepared,root=stages.ROOT,output=output,
            observation_root=stages.OBSERVATIONS,budget_path=stages.BUDGET,budget_limit_usd=stages.TASK_LIMIT,
            candidate_path=path/'draft.json',dependencies=deps,max_attempts=2,target_format=args.target_format)
        print(json.dumps({k:result.get(k) for k in ('status','model_review_status','issue_count','reviewed_check_count','trace_id','budget')},ensure_ascii=False))
    finally:await prepared['native'].aclose()

if __name__=='__main__':asyncio.run(main())
