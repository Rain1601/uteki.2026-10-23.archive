"""Independent, zero-API audit. Never imported by the running Data Agent."""
import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT/'output/revenue-stability-20261012'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def audit(version, slot):
    exp = ROOT/'experiments/agent_design'
    old = exp/'2026-10-10-e6-repeatability-v2/evaluation-only/independent_acceptance.py'
    helper = exp/'2026-10-10-e6-repeatability-v3/evaluation-only/projection_visibility.py'
    a = load('old_acceptance', old)
    visibility = load('visibility', helper)
    a.STANDARD = exp/'2026-10-10-e6-repeatability-v3/evaluation-only/content-standard.v1.json'
    run = BASE/version/slot/'run'
    report = a.audit_run(run, slot)
    projection = []
    for draft in report.get('all_drafts', []):
        review = ROOT/draft['review']
        packet = a.read(review/'input.json')
        query = Path(packet['query_ref']['path'])
        inputs, binding = a.sdk_bound_inputs(query.parent)
        projection.append({'review': draft['review'], **visibility.visible_projection(packet, query, inputs, binding, a.relative)})
    final = report.get('final_draft')
    selected = next((p for p in projection if final and p['review'] == final['review']), None)
    report.update(schema_version='fresh-revenue-independent-audit-v1',
        actual_projection_reviews=projection,
        final_projection_matches=bool(selected and selected['verdict']=='pass'),
        combined_delivery_checks=bool(report.get('final_usable_delivery') and selected and selected['verdict']=='pass'),
        manual_content_verdict='pending-Codex-selected-original-reading',
        evaluator_bindings={str(p.relative_to(ROOT)): a.digest(p.read_bytes()) for p in (
            Path(__file__),old,helper,a.STANDARD,BASE/'evaluation-only/original-revenue-audit.v1.json')})
    target=BASE/'evaluation-only'/f'{version}-{slot}-audit.json'
    with target.open('x') as f:
        json.dump(report,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({k:report[k] for k in ('runtime_status','final_usable_delivery',
        'final_projection_matches','combined_delivery_checks','no_recovery_first_pass',
        'api_call_count','known_estimated_usd','unknown_cost_call_ids')},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--slot',required=True,choices=['R1','R2','R3'])
    p.add_argument('--version',default='v1',choices=['v1','v2','v3','v4'])
    args=p.parse_args();audit(args.version,args.slot)
