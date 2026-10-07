"""Recover a known complete model answer by redundant evidence indexing only.

No model/network adapter and no budget writer are constructed. The failed source
stage is immutable; only a new explicitly labelled materialization is published.
"""
import argparse
from contextlib import closing
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT/'src'))
from uteki.agents.business_map import product_run as base
from uteki.agents.business_map import evidence_projection
from uteki.agents.business_map.coverage_run import verify_published_artifacts
from uteki.agents.business_map.product_contract import validate_draft
from uteki.agents.runtime.observation import observed_run, observed_step
from uteki.agents.runtime.strict_json import parse_json_object

PARENT = HERE/'microsoft/generation-01'
OUTPUT = HERE/'microsoft/generation-01-indexed'
OBSERVATIONS = ROOT/'data/agent_observability/local'
LEDGER = ROOT/'experiments/agent_design/2026-10-07-business-coverage-v1/run-06/budget.sqlite'
COPIES = ('request.json','response.txt','source_packet.json','skill.md',
          'configuration.json','response_metadata.json','output_schema.json')


def load(path):
    return parse_json_object(path.read_text())


def budget_readonly(parent):
    """Preserve prior unknown fees; verify this model call actually settled."""
    if parent.get('budget_path') != str(LEDGER.relative_to(ROOT)) or not LEDGER.is_file():
        raise ValueError('same_existing_task_ledger_required')
    with closing(sqlite3.connect(LEDGER.resolve().as_uri()+'?mode=ro', uri=True)) as db:
        limit = db.execute('SELECT usd FROM config WHERE id=1').fetchone()[0]
        rows = db.execute('SELECT id,reserved,actual,state FROM reservations').fetchall()
    if Decimal(limit) != Decimal('5'):
        raise ValueError('unchanged_five_dollar_limit_required')
    by_id = {row[0]: row for row in rows}
    costs = parent.get('costs') or {}
    records = costs.get('records') or []
    if not records or costs.get('unknown_cost_requests') != 0:
        raise ValueError('parent_call_known_cost_required')
    for record in records:
        row = by_id.get(record.get('budget_reservation_id'))
        if (not row or row[3] != 'settled' or row[2] is None or
                Decimal(row[2]) != Decimal(record['estimated_usd']) or
                record.get('status') != 'succeeded' or record.get('stop_reason') != 'end_turn'):
            raise ValueError('parent_call_not_settled_complete')
    return dict(limit_usd=limit,
        estimated_spent_usd=str(sum((Decimal(a) for _,_,a,s in rows if s=='settled'),Decimal(0))),
        held_usd=str(sum((Decimal(r) for _,r,_,s in rows if s!='settled'),Decimal(0))),
        unknown_requests=sum(s=='unknown' for *_,s in rows),
        in_flight_requests=sum(s=='reserved' for *_,s in rows), requests=len(rows),
        actual_billed_usd=None, enforcement='enforced', access='sqlite_mode_ro')


def prepare():
    if OUTPUT.exists():
        raise ValueError('recovery_output_exists_do_not_overwrite')
    parent = load(PARENT/'result.json')
    if (parent.get('status') != 'failed' or parent.get('execution_mode') != 'business_products_generation'
            or parent.get('validation_error') != 'business_claim_not_in_node_evidence'):
        raise ValueError('specific_complete_generation_index_failure_required')
    names = [*COPIES,'manifest.json','result.json']
    hashes = verify_published_artifacts(root=ROOT, observation_root=OBSERVATIONS,
        stage=PARENT, trace_id=parent['trace_id'], relative_paths=names)
    manifest = load(PARENT/'manifest.json')
    metadata = load(PARENT/'response_metadata.json')
    packet = load(PARENT/'source_packet.json')
    request = load(PARENT/'request.json')
    for key in ('company_id','document_id','period_end','source_packet_sha256',
                'source_sha256','skill_sha256','request_sha256','execution_mode'):
        if parent[key] != manifest[key]:
            raise ValueError('parent_manifest_receipt_mismatch')
    if (metadata.get('stop_reason') != 'end_turn' or metadata.get('usage_presence') != 'reported'
            or metadata.get('stream_complete') is not True):
        raise ValueError('complete_known_usage_response_required')
    for name,key in [('request.json','request_sha256'),('skill.md','skill_sha256'),
                     ('source_packet.json','source_packet_sha256')]:
        if base.digest((PARENT/name).read_bytes()) != parent[key]:
            raise ValueError('parent_frozen_bytes_mismatch')
    if metadata['request_sha256'] != parent['request_sha256']:
        raise ValueError('parent_response_request_mismatch')
    if (len(request.get('messages',[])) != 1 or request['messages'][0].get('role') != 'user'
            or parse_json_object(request['messages'][0]['content']) != packet):
        raise ValueError('parent_generation_not_source_only')
    base.verify_packet(packet, ROOT,
        **{k:parent[k] for k in ('company_id','document_id','period_end')},contract_version='business-draft-v2')
    budget = budget_readonly(parent)
    raw = load(PARENT/'response.txt')
    # This generic helper validates the complete result. A second semantic or
    # protocol defect aborts before directory creation/trace/materialization.
    projected, projection = evidence_projection.project_business_evidence_indexes(
        raw, packet, expected_version='business-draft-v2')
    if not projection['changes']:
        raise ValueError('expected_missing_indexes_not_found')
    draft = validate_draft(projected,packet,expected_version='business-draft-v2')
    return parent, manifest, packet, draft, projection, hashes, budget


def recover(*, execute=False):
    parent, manifest, packet, draft, projection, hashes, budget = prepare()
    summary = dict(status='projection_full_contract_passed', changes=len(projection['changes']),
                   nodes=len(draft.businesses), relationships=len(draft.relationships),
                   model_calls_in_this_trace=0, parent_trace_id=parent['trace_id'])
    if not execute:
        return summary
    # Recheck frozen parent bytes immediately before publishing the derivative.
    if any(base.digest((ROOT/name).read_bytes()) != digest for name,digest in hashes.items()):
        raise ValueError('parent_changed_after_projection')
    result = None
    with observed_run(output=OUTPUT, kind='extraction', role='extractor',
            origin='business_evidence_index_projection', observation_root=OBSERVATIONS,
            scope={k:parent[k] for k in ('company_id','period_end','task_type')},
            title='证据索引确定性恢复 / no model call') as context:
        OUTPUT.mkdir(parents=True, exist_ok=False)
        manifest = deepcopy(manifest)
        manifest.update(trace_id=context.run_id, execution_mode='business_products_generation',
            materialization_mode='evidence_index_projection', model_calls_in_this_trace=0,
            model_execution_trace_id=parent['trace_id'], parent_trace_id=parent['trace_id'],
            parent_stage=str(PARENT.relative_to(ROOT)),
            parent_raw_response_sha256=base.digest((PARENT/'response.txt').read_bytes()),
            parent_result_sha256=base.digest((PARENT/'result.json').read_bytes()),
            parent_artifacts_sha256=hashes,
            materialization_implementation_sha256={
                'recover_indexes.py':base.digest(Path(__file__).read_bytes()),
                'evidence_projection.py':base.digest(Path(evidence_projection.__file__).read_bytes()),
                'product_run.py':base.digest(Path(base.__file__).read_bytes())},
            source_execution_mode=parent['execution_mode'], model_request_reused=True,
            new_network_requests=0, calls_max=0, retries=0,
            semantic_acceptance='not_evaluated', adoption='candidate')
        result = dict(manifest, status='failed', budget_path=parent['budget_path'], budget=budget,
            parent_model_costs=parent['costs'],
            costs=dict(requests=0,unknown_cost_requests=0,known_estimated_usd='0',
                       actual_billed_usd=None,records=[]))
        try:
            with observed_step(context,1,phase='验证原响应并生成冗余证据索引') as step:
                for name in COPIES:
                    (OUTPUT/name).write_bytes((PARENT/name).read_bytes())
                for name in ('manifest.json','result.json'):
                    (OUTPUT/('parent-'+name)).write_bytes((PARENT/name).read_bytes())
                base.write_json(OUTPUT/'manifest.json',manifest)
                base.write_json(OUTPUT/'draft.json',draft.model_dump())
                base.write_json(OUTPUT/'projection.json',projection)
                counts=base.materialize(draft,packet,root=ROOT,output=OUTPUT,
                                        manifest=manifest,trace_id=context.run_id)
                result.update(status='candidate',validation='passed',counts=counts,
                    stop_reason='deterministic_projection_completed',
                    artifact='draft.json',artifact_sha256=base.digest((OUTPUT/'draft.json').read_bytes()),
                    artifacts_sha256={name:base.digest((OUTPUT/name).read_bytes()) for name in
                                      ('business_map.json','evidence.html','projection.json','manifest.json')})
                for path in OUTPUT.iterdir():
                    if path.is_file():step.publish(path)
        except BaseException as error:
            result.update(status='failed',stop_reason=type(error).__name__)
            raise
        finally:
            # The final receipt is published while this trace remains open.
            base.write_json(OUTPUT/'result.json',result)
            context.publish(OUTPUT/'result.json')
    published=verify_published_artifacts(root=ROOT,observation_root=OBSERVATIONS,
        stage=OUTPUT,trace_id=result['trace_id'],relative_paths=[*COPIES,'manifest.json','result.json',
                   'projection.json','draft.json','business_map.json','evidence.html'])
    return dict(summary, status=result['status'], trace_id=result['trace_id'],
                output=str(OUTPUT.relative_to(ROOT)), published_files_verified=len(published),counts=result['counts'])


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    print(json.dumps(recover(execute=args.execute),ensure_ascii=False))
