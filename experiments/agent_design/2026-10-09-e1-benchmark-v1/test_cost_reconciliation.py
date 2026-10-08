"""Check per-reservation reconciliation without touching the real API ledger."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from reconcile_costs import reconcile


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.ledger=self.root/'ledger.sqlite';self.calls=self.root/'runs/r1/calls'
        self.calls.mkdir(parents=True)
        with closing(sqlite3.connect(self.ledger)) as db,db:
            db.execute('CREATE TABLE config(id INTEGER PRIMARY KEY,usd TEXT)')
            db.execute("INSERT INTO config VALUES(1,'40')")
            db.execute('CREATE TABLE autonomous_request_limit(id INTEGER PRIMARY KEY,maximum INTEGER)')
            db.execute('INSERT INTO autonomous_request_limit VALUES(1,500)')
            db.execute('CREATE TABLE reservations(id TEXT PRIMARY KEY,reserved TEXT,actual TEXT,state TEXT)')
            db.executemany('INSERT INTO reservations VALUES(?,?,?,?)',[
                ('r1','1','0.2','settled'),('r2','1','0.3','settled'),('r3','0.4',None,'unknown')])
        for rid,actual in [('r1','0.2'),('r2','0.3'),('r3',None)]:
            value={'call_id':rid+'-call','budget_reservation_id':rid,'reserved_usd':'0.4' if rid=='r3' else '1',
                   'provider':'synthetic','requested_model':'synthetic','stage':'review','started_at':'2030-01-01T00:00:00Z'}
            (self.calls/(rid+'-start.json')).write_text(json.dumps(value))
            (self.calls/(rid+'-end.json')).write_text(json.dumps({**value,'estimated_usd':actual,
                'status':'failed' if actual is None else 'succeeded'}))

    def test_read_only_match_preserves_unknown_hold(self):
        before=self.ledger.read_bytes()
        value=reconcile(self.ledger,self.root/'runs')
        self.assertEqual(value['status'],'matched_quiescent')
        self.assertEqual(value['known_estimated_usd'],'0.5')
        self.assertEqual(value['unknown_reserved_usd'],'0.4')
        self.assertEqual(value['committed_upper_bound_usd'],'0.9')
        self.assertEqual(value['unknown_requests'],1)
        self.assertEqual(value['mismatched_reservations'],0)
        self.assertEqual(before,self.ledger.read_bytes())

    def test_equal_total_but_swapped_receipt_amounts_fails_each_reservation(self):
        for rid,actual in [('r1','0.3'),('r2','0.2')]:
            path=self.calls/(rid+'-end.json');value=json.loads(path.read_text())
            value['estimated_usd']=actual;path.write_text(json.dumps(value))
        value=reconcile(self.ledger,self.root/'runs')
        self.assertEqual(value['known_estimated_usd'],'0.5')
        self.assertEqual(value['mismatched_reservations'],2)
        self.assertNotEqual(value['status'],'matched_quiescent')

    def test_pending_missing_and_duplicate_receipts_cannot_be_final(self):
        with closing(sqlite3.connect(self.ledger)) as db,db:
            db.execute("UPDATE reservations SET state='reserved' WHERE id='r3'")
        (self.calls/'r3-end.json').unlink()
        value=reconcile(self.ledger,self.root/'runs')
        self.assertEqual(value['inflight_requests'],1)
        self.assertEqual(value['inflight_reserved_usd'],'0.4')
        self.assertFalse(value['quiescent'])
        self.assertEqual(value['mismatched_reservations'],0)
        (self.calls/'r1-start.json').unlink()
        self.assertEqual(reconcile(self.ledger,self.root/'runs')['mismatched_reservations'],1)
        (self.calls/'duplicate-end.json').write_bytes((self.calls/'r2-end.json').read_bytes())
        self.assertEqual(reconcile(self.ledger,self.root/'runs')['mismatched_reservations'],2)


if __name__=='__main__':unittest.main()
