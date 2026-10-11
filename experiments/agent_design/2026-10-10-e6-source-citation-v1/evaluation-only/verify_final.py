"""Final read-only binding check; no model calls or ledger mutation."""
import hashlib,json
from pathlib import Path
from uteki.agents.data_query import answer_handoff as h, retrieval_cycle as c
from uteki.infrastructure.research_data.financial_records import digest
R=Path.cwd();E=R/'experiments/agent_design/2026-10-10-e6-source-citation-v1';O=R/'output/e6-source-citation-20261010-r1'
read=lambda p:json.loads(p.read_bytes())
f=read(E/'evaluation-only/execution-freeze.v2.json')
for p,expected in f['files'].items():assert digest((R/p).read_bytes())==expected,p
for p,expected in f['sealed_refs'].items():c._verify_manifest(R/p,expected)
progress=read(O/'progress.v2.json');assert progress['status']=='completed'
a=read(E/'evaluation-only/independent-real-audit.v1.json');assert a['real_acceptance_complete'] and not a['missing_steps']
assert a['old_rejected_drafts_unchanged']
b=read(E/'evaluation-only/cost-audit.v1.json');assert b['status']=='passed' and b['all_new_rows_matched_sealed_unique_calls']
checked=[]
for step in progress['steps']:
 ref=step['result'].get('final_review_ref') or step['result']['review_ref']
 loaded=h.load_reviewed_data(ref['path'],expected_scope=read(O/'runtime-config.v1.json')['request']['scope'],expected_review_manifest_sha256=ref['manifest_sha256'])
 assert loaded['execution_origin']=='model';checked.append({'id':step['id'],'load':'passed','model_origin':True,'analysis_called':False})
for review in ['review-01','review-02']:
 p=R/'output/e6-repeatability-20261010-r1/R3/S3/run-r1/attempt-01'/review
 try:h._validate_source_assessment(read(p/'input.json'),read(p/'source-response.json'))
 except h.SourceCitationProtocolError:pass
 else:raise AssertionError('Original failed draft became accepted')
summary={'schema_version':'e6-r1-root-final-verification-v1','status':'passed','frozen_files_checked':len(f['files']),'old_pinned_runs_unchanged':True,'steps':checked,'original_failed_drafts_still_rejected':2,'original_quality_standard_sha256':a['original_standard_sha256'],'cost_report_sha256':digest((E/'evaluation-only/cost-audit.v1.json').read_bytes()),'content_report_sha256':digest((E/'evaluation-only/independent-real-audit.v1.json').read_bytes()),'unknown_reserves_retained_usd':b['new_held_reserved_usd'],'no_new_model_calls':True,'limits':'two failed-draft repairs and one same-question fresh run; independent synthetic checks are offline; no statistical stability claim'}
(E/'evaluation-only/final-verification.v1.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'status':'passed','frozen_files':len(f['files']),'real_deliveries':len(checked),'unknown_preserved':b['new_held_reserved_usd']}))
