"""Zero API, read-only originals and SDK bindings. Gold never enters production.

Controlled first query/role outputs are historical fixtures, not a fresh autonomous
baseline. Final query and dual review must prove real SDK invocation independently.
"""
import argparse
import importlib.util
import json
from pathlib import Path
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[4]
EXP = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'output/e6-delivery-boundary-20261010-r1'
OLD = ROOT / 'experiments/agent_design/2026-10-10-e6-repeatability-v2/evaluation-only/independent_acceptance.py'
spec = importlib.util.spec_from_file_location('old_acceptance', OLD)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)
a.STANDARD = EXP / 'evaluation-only/content-standard.v1.json'
read, checked, digest = a.read, a.checked, a.digest


def blocks(packet):
    rows = []
    for document in packet['source_documents']:
        sid = document['source_snapshot_id']
        source = next(s for s in read(Path(packet['dataset_ref']['path']) / 'sources.json') if s['source_snapshot_id'] == sid)
        original = {b['block_id']: b for b in (json.loads(line) for line in
            (Path(packet['dataset_ref']['path']) / source['index_folder'] / 'blocks.jsonl').read_text().splitlines())}
        for b in document['blocks']:
            full = original[b['block_id']]
            rows.append({'source_snapshot_id': sid, 'block_id': b['block_id'], 'type': b['type'],
                'layout_role': b.get('layout_role'), 'text': b['text'], 'characters': len(b['text']),
                'exact_original_text': b['text'] == full['text'], 'text_hash': full['text_hash'],
                'dom_path': full.get('dom_path'), 'dom_locator': full.get('dom_locator')})
    return rows


PROJECTION_HELPER = ROOT / 'experiments/agent_design/2026-10-10-e6-repeatability-v3/evaluation-only/projection_visibility.py'
projection_spec = importlib.util.spec_from_file_location('projection_visibility', PROJECTION_HELPER)
projection_helper = importlib.util.module_from_spec(projection_spec)
projection_spec.loader.exec_module(projection_helper)


def visible_projection(packet, query):
    inputs, binding = a.sdk_bound_inputs(query.parent)
    return projection_helper.visible_projection(packet, query, inputs, binding, a.relative)


def audit(case):
    run = OUTPUT / case / 'run-r1'
    result = a.audit_run(run, case)
    controlled = case == 'replay-original-R3-S1'
    all_rows = []
    for draft in result['all_drafts']:
        review = ROOT / draft['review']
        packet = read(review / 'input.json')
        source_rows = blocks(packet)
        historical = controlled and review.parent.name == 'attempt-01'
        projection = {'verdict': 'not_applicable', 'reason': 'Original v3 historical query replay; no V4 preview was dispatched.'} if historical else visible_projection(packet, Path(packet['query_ref']['path']))
        partial = checked(a.handoff.validate_source_revision_feedback, review, packet) if read(review/'result.json')['status'] == 'failed' else None
        all_rows.append({'review': draft['review'], 'execution_kind': 'historical-query-and-scripted-role-replay' if historical else 'fresh-model-query-and-dual-review',
            'full_original_blocks_for_independent_reading': source_rows,
            'exact_all_original_blocks': all(r['exact_original_text'] for r in source_rows),
            'visible_final_body_projection': projection, 'validated_partial_negative_feedback': partial})
    receipt = read(run.parent / 'execution-receipt.v1.json')
    final_ref = read(run/'result.json').get('final_review_ref')
    final = next((r for r in all_rows if final_ref and str(ROOT / r['review']) == final_ref['path']), None)
    result.update(schema_version='e6-r3-independent-real-acceptance-v2',
        supersedes_evaluator_schema_version='e6-r3-independent-real-acceptance-v1',
        historical_projection_claims='unverified-until-reassessed-with-sdk-projection-visibility-v2',
        projection_helper={'path': a.relative(PROJECTION_HELPER), 'sha256': digest(PROJECTION_HELPER.read_bytes())},
        operation='controlled-original-failure-then-autonomous-retrieval' if controlled else 'fresh-autonomous',
        controlled_first_draft_is_not_fresh_baseline=controlled,
        full_block_reviews=all_rows, final_projection_matches=bool(final and final['visible_final_body_projection']['verdict']=='pass'),
        receipt_sha256=digest((run.parent/'execution-receipt.v1.json').read_bytes()),
        occupied_cost_increment=str(Decimal(receipt['ledger_after']['occupied_usd'])-Decimal(receipt['ledger_before']['occupied_usd'])),
        evaluator_sha256=digest(Path(__file__).read_bytes()),
        reused_zero_api_helper={'path': a.relative(OLD), 'sha256': digest(OLD.read_bytes())},
        statistical_stability_claim=False,
        manual_content_verdict='pending-independent-full-block-reading')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--case', required=True, choices=['replay-original-R3-S1','fresh-S1','fresh-S3'])
    p.add_argument('--report', required=True, type=Path)
    args = p.parse_args()
    value = audit(args.case)
    with args.report.open('x') as file:
        json.dump(value, file, ensure_ascii=False, indent=2); file.write('\n')
    print(json.dumps({k: value[k] for k in ['slot_id','runtime_status','final_usable_delivery','final_projection_matches','api_call_count','known_estimated_usd','manual_content_verdict']},ensure_ascii=False))
