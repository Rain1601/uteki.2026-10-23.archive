"""Read-only independent provenance and shared-budget verification after a run.

Explicit historical baseline belongs to this experiment, not production defaults.
No model/network calls; never repairs or changes old model output or ledger rows.
"""
import argparse
from collections import Counter
from contextlib import closing
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
from uteki.agents.business_map import coverage_contract as contract, coverage_run as run
from uteki.agents.business_map import coverage_continuation as continuation
from uteki.agents.business_map.evidence_projection import project_relationship_evidence
from uteki.agents.business_map.product_contract import validate_draft


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text())


def rows(path):
    assert path.is_file() and not path.is_symlink()
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        return {row[0]:list(row[1:]) for row in db.execute('SELECT id,reserved,actual,state FROM reservations')}


def state(values,limit):
    return dict(limit_usd=limit,
        estimated_spent_usd=str(sum((Decimal(v[1]) for v in values.values() if v[2]=='settled'),Decimal(0))),
        held_usd=str(sum((Decimal(v[0]) for v in values.values() if v[2]!='settled'),Decimal(0))),
        unknown_requests=sum(v[2]=='unknown' for v in values.values()),
        in_flight_requests=sum(v[2]=='reserved' for v in values.values()),requests=len(values),
        actual_billed_usd=None,enforcement='enforced')


def verify(run_path, baseline_budget, historical_calls):
    run_path=(ROOT/run_path).resolve()
    summary=read(run_path/'summary.json')
    assert summary['execution_mode']=='authorized_single_coverage_continuation'
    assert not summary['in_flight_requests']
    prior_path=ROOT/summary['prior_run'];prior=read(prior_path/'summary.json')
    proof={}

    def published(stage,trace,names):
        proof.update(run.verify_published_artifacts(root=ROOT,observation_root=ROOT/'data/agent_observability/local',
            stage=stage,trace_id=trace,relative_paths=names))

    inventory_attempt=next(a for a in summary['attempts'] if a['mode']=='inventory')
    inventory_stage=ROOT/inventory_attempt['path']
    published(inventory_stage,inventory_attempt['trace_id'],['inventory.json'])
    inventory=read(inventory_stage/'inventory.json')
    assert read(run_path/'inventory/inventory.json')==inventory
    previous=ROOT/summary['input_candidate_path']
    initial=read(previous/'draft.json')
    assert contract.canonical_hash(initial)==summary['input_candidate_sha256']==prior['candidate_sha256']
    prior_audit_file=ROOT/summary['input_audit_path']
    assert sha(prior_audit_file)==summary['input_audit_sha256']
    prior_audit=read(prior_audit_file)
    assert prior_audit['candidate_sha256']==contract.canonical_hash(initial)
    published(previous,read(previous/'result.json')['trace_id'],['draft.json','response.txt','source_packet.json','skill.md'])
    published(prior_audit_file.parent,read(prior_audit_file.parent/'result.json')['trace_id'],['audit.json','response.txt','request.json'])
    packet=read(previous/'source_packet.json')
    contract.validate_inventory(inventory,packet)
    skill=(previous/'skill.md').read_text()
    draft=initial
    stages=[]
    for attempt in summary['attempts']:
        if attempt['mode']=='inventory':continue
        stage=ROOT/attempt['path'];manifest=read(stage/'manifest.json');request=read(stage/'request.json')
        assert sha(stage/'request.json')==manifest['request_sha256']
        assert sha(stage/'source_packet.json')==summary['source_packet_sha256']
        assert sha(stage/'skill.md')==summary['skill_sha256']
        names=['manifest.json','result.json','request.json','configuration.json','source_packet.json','skill.md',
               'source_wire.json','output_schema.json','response_metadata.json']
        if (stage/'response.txt').exists():names.append('response.txt')
        payload=json.loads(request['messages'][0]['content'])
        assert payload==read(stage/'source_wire.json')
        assert payload['frozen_source_packet']==packet
        assert payload['source_inventory']==inventory
        assert payload['own_candidate']==draft
        assert manifest['input_candidate_sha256']==contract.canonical_hash(draft)
        assert manifest['inventory_sha256']==contract.canonical_hash(inventory)
        assert manifest['system_prompt_sha256']==hashlib.sha256(request['system'].encode()).hexdigest()
        schema=read(stage/'output_schema.json')
        expected_instruction=continuation.REVISION_INSTRUCTION if attempt['mode']=='revision' else run.AUDIT
        assert request['system']==expected_instruction+run.COMMON.format(skill=skill,schema=run._json(schema))
        if attempt['mode']=='revision':
            assert set(payload)=={'frozen_source_packet','source_inventory','own_candidate','own_audit'}
            assert payload['own_audit']==prior_audit
            if attempt['status']=='candidate':
                value,projection=project_relationship_evidence(read(stage/'response.txt'),packet,
                    expected_version=manifest['source_business_contract_version'])
                assert projection==read(stage/'projection.json')
                draft=validate_draft(value,packet,expected_version=manifest['source_business_contract_version']).model_dump()
                assert draft==read(stage/'draft.json')
                names+=['projection.json','draft.json','business_map.json','evidence.html']
        else:
            assert set(payload)=={'frozen_source_packet','source_inventory','own_candidate','candidate_sha256','inventory_sha256','check_targets'}
            assert payload['check_targets']==contract.check_targets(draft)
            if attempt['status']=='completed':
                audit=contract.validate_audit(read(stage/'response.txt'),packet,inventory,draft)
                saved=read(stage/'audit.json')
                assert all(audit[k]==saved[k] for k in ('mappings','checks','candidate_sha256','inventory_sha256'))
                before={m['mention_id'] for m in prior_audit['mappings'] if m['disposition']=='node'}
                after={m['mention_id'] for m in audit['mappings'] if m['disposition']=='node'}
                assert saved['regressed_mention_ids']==sorted(before-after)
                assert summary['self_check_status']==saved['computed_status']
                names+=['audit.json']
        names += [f.relative_to(stage).as_posix() for f in (stage/'model-calls').glob('*-end.json')]
        published(stage,attempt['trace_id'],names)
        stages.append(dict(mode=attempt['mode'],status=attempt['status'],trace_id=attempt['trace_id'],
            request_sha256=sha(stage/'request.json'),request_bytes=(stage/'request.json').stat().st_size,
            actual_max_tokens=request['max_tokens'],source_candidate_binding='passed'))
    assert contract.canonical_hash(draft)==summary['candidate_sha256']

    baseline_path=ROOT/baseline_budget
    expected=rows(baseline_path)
    baseline_record=dict(path=str(baseline_path.relative_to(ROOT)),sha256=sha(baseline_path),reservations=len(expected))
    for folder in historical_calls:
        folder=ROOT/folder;trace=read(folder/'result.json')['trace_id']
        for file in (folder/'model-calls').glob('*-end.json'):
            published(folder,trace,[file.relative_to(folder)])
            record=read(file)
            reservation=record['budget_reservation_id']
            assert reservation not in expected
            assert record['estimated_usd'] is not None
            expected[reservation]=[record['reserved_usd'],record['estimated_usd'],'settled']
    assert state(expected,prior['budget']['limit_usd'])==prior['budget']
    ledger=ROOT/summary['budget_path'];current=rows(ledger)
    assert all(current.get(key)==value for key,value in expected.items())
    prior_ids=set(expected)
    for attempt in summary['attempts']:
        if attempt['mode']=='inventory':continue
        for file in (ROOT/attempt['path']/'model-calls').glob('*-end.json'):
            record=read(file);reservation=record['budget_reservation_id']
            assert reservation not in expected
            expected[reservation]=[record['reserved_usd'],record['estimated_usd'],
                                   'settled' if record['estimated_usd'] is not None else 'unknown']
    assert current==expected
    assert state(current,summary['budget']['limit_usd'])==summary['budget']
    with closing(sqlite3.connect(ledger.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        auth_records=[json.loads(row[0]) for row in db.execute('SELECT record FROM limit_authorizations')]
        triggers={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    applied=read(run_path/'budget-authorization.json')
    assert applied in auth_records
    assert {'limit_auth_no_update','limit_auth_no_delete'}<=triggers
    auth=applied['authorization']
    assert auth['old_limit_usd']==prior['budget']['limit_usd'] and auth['new_limit_usd']==summary['budget']['limit_usd']
    assert auth['prior_summary_sha256']==sha(prior_path/'summary.json')
    canonical=json.dumps(auth,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
    assert hashlib.sha256(canonical.encode()).hexdigest()==applied['authorization_sha256']
    claim=read(prior_path/'recovery-claim.json')
    assert claim['successor']==str(run_path.relative_to(ROOT))
    assert claim['prior_summary_sha256']==sha(prior_path/'summary.json')
    assert summary['semantic_acceptance']=='not_evaluated'
    return dict(schema_version='coverage-continuation-provenance-verification-v1',status='passed',
        verification_kind='offline_post_execution',new_model_calls=0,semantic_acceptance='not_evaluated',
        stages=stages,verified_published_files=proof,
        budget=dict(path=summary['budget_path'],historical_baseline=baseline_record,
            prior_reservations_checked_unchanged=len(prior_ids),new_reservations=len(current)-len(prior_ids),
            authorization_old_limit=auth['old_limit_usd'],authorization_new_limit=auth['new_limit_usd'],
            immutable_authorization_triggers_present=True,summary=summary['budget']),
        notes=['Original publication hashes establish local provenance, not remote attestation.',
               'Exact source and protocol checks do not prove semantic completeness.'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--baseline-budget',type=Path,required=True)
    parser.add_argument('--historical-call-stage',type=Path,action='append',required=True)
    args=parser.parse_args()
    value=verify(args.run,args.baseline_budget,args.historical_call_stage)
    with (ROOT/args.run/'provenance-verification.json').open('x') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n')
    print(json.dumps({'status':value['status'],'published_files':len(value['verified_published_files']),
        'prior_reservations':value['budget']['prior_reservations_checked_unchanged'],
        'new_reservations':value['budget']['new_reservations']},ensure_ascii=False))


if __name__=='__main__':main()
