"""Verify the original shared ledger against every new sealed request."""
import json,sqlite3,hashlib
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4];E=Path(__file__).resolve().parents[1];O=ROOT/'output/e6-repeatability-20261010-r1'
def read(p):return json.loads(p.read_bytes())
matrix=read(E/'execution-matrix.v1.json')['runs'];progress=read(O/'execution-progress.v3.json')
assert progress['status']=='completed' and len(progress['runs'])==9,'fixed nine slots not fully completed'
assert [r['slot_id'] for r in progress['runs']]==[r['slot_id'] for r in matrix]
sealed_calls=set()
for item in matrix:
    run=ROOT/item['run'];assert (run/'result.json').exists() and (run/'manifest.json').exists()
    manifest=read(run/'manifest.json')['files']
    for relative,expected in manifest.items():
        path=run/relative;assert hashlib.sha256(path.read_bytes()).hexdigest()==expected,str(path)
        if relative.endswith(('-start.json','-end.json')):sealed_calls.add(path.resolve())
actual_calls={p.resolve() for pattern in ['*-start.json','*-end.json'] for p in O.rglob(pattern)}
assert actual_calls==sealed_calls,'cost records must be in verified sealed run manifests'
before=read(O/'ledger-before-execution.json');old_ids=set(before['reservation_ids'])
c=sqlite3.connect(ROOT/'experiments/agent_design/2026-10-09-e2-msft-10q-v1/costs.sqlite');rows={x[0]:x[1:] for x in c.execute('SELECT id,reserved,actual,state FROM reservations')};limit=c.execute('SELECT usd FROM config').fetchone()[0];cap=c.execute('SELECT maximum FROM autonomous_request_limit').fetchone()[0];auth=c.execute('SELECT COUNT(*) FROM limit_authorizations WHERE id=?',('E6-20261010-user-add-10usd-v1',)).fetchone()[0];c.close()
ends=[(p,read(p)) for p in O.rglob('*-end.json')];starts=[read(p) for p in O.rglob('*-start.json')];end_ids=[r['budget_reservation_id'] for p,r in ends]
assert len(set(end_ids))==len(end_ids),'duplicate reservation records';assert old_ids<=set(rows),'original ledger history lost';assert set(rows)-old_ids==set(end_ids),'new ledger rows do not match call ends';assert {r['call_id'] for r in starts}=={r['call_id'] for p,r in ends},'start/end mismatch';assert all(s=='settled' for reserved,actual,s in rows.values()),'unknown or in-flight costs';assert limit=='13' and cap==1000 and auth==1
for p,r in ends:
    reserved,actual,state=rows[r['budget_reservation_id']];assert r['estimated_usd'] is not None and Decimal(actual)==Decimal(r['estimated_usd']),str(p)
    if r.get('dispatch_status')=='not_sent':
        assert Decimal(actual)==0
        continue
    pr=r['pricing_snapshot'];usage=r['usage'];assert usage is not None
    expected=(Decimal(usage['input_tokens'])*Decimal(pr['input_per_million'])+Decimal(usage['output_tokens'])*Decimal(pr['output_per_million']))/Decimal(1000000)
    assert Decimal(actual)==expected,(p,'price mismatch')
known=sum((Decimal(r['estimated_usd']) for p,r in ends),Decimal(0));total=sum((Decimal(a) for r,a,s in rows.values()),Decimal(0));assert total-Decimal(before['known_estimated_usd'])==known
out={'schema_version':'e6-repeatability-ledger-reconciliation-v1','all_nine_planned_slots_completed':True,'all_run_manifest_file_hashes_verified':True,'requests_before':len(old_ids),'estimated_usd_before':before['known_estimated_usd'],'new_calls':len(ends),'new_estimated_usd':str(known),'total_calls':len(rows),'total_estimated_usd':str(total),'unknown':0,'inflight':0,'limit_usd':limit,'request_cap':cap,'all_new_reservations_matched_to_sealed_calls':True,'all_costs_recomputed_using_sealed_price_snapshots':True,'original_authorization_and_history_retained':True,'actual_billed_usd':None,'model_api_calls_for_verification':0}
(E/'evaluation-only/cost-reconciliation.v1.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps(out))
