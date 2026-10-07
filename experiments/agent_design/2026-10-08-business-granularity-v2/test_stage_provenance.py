"""Offline launcher boundaries; no model dispatch or historical artifact edits."""
from copy import deepcopy
import asyncio
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('stage_launcher',HERE/'run_stage.py')
stage=importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)


class StageProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.parent=HERE/'microsoft/generation-01'
        load=lambda name:json.loads((self.parent/name).read_text())
        self.result,self.metadata,self.packet,self.request=[load(n) for n in
            ('result.json','response_metadata.json','source_packet.json','request.json')]
        self.prepared=dict(manifest=self.result,packet=self.packet,kwargs=dict(
            input=self.request['messages'][0]['content'],system_instructions=self.request['system']))

    def test_actual_failed_output_bound_to_nine_original_publications_and_machine_error(self):
        dependencies={}
        value,error=stage.load_failed(self.parent,self.prepared,dependencies)
        self.assertEqual(error,'monetization_claim_evidence_mismatch')
        self.assertEqual(value,json.loads((self.parent/'response.txt').read_text()))
        self.assertEqual(len(dependencies),9)
        self.assertTrue(any(p.endswith('/result.json') for p in dependencies))

    def test_selected_company_and_system_prompt_cannot_be_substituted(self):
        prepared=deepcopy(self.prepared)
        prepared['manifest'].update(zip(('company_id','document_id','period_end'),stage.CASES['google']))
        with self.assertRaisesRegex(ValueError,'own_new_generation_required'):
            stage.load_failed(self.parent,prepared,{})
        prepared=deepcopy(self.prepared)
        prepared['kwargs']['system_instructions']+=' Extra human answer.'
        with self.assertRaisesRegex(ValueError,'source_only'):
            stage.load_failed(self.parent,prepared,{})

    def test_extra_chat_message_or_tool_input_rejected(self):
        for mutation in ('message','tool'):
            request=deepcopy(self.request)
            if mutation=='message':request['messages'].append(dict(role='assistant',content='prior answer'))
            else:request['tools']=[dict(name='external_lookup')]
            with self.assertRaisesRegex(ValueError,'without_tools'):
                stage.request_payload(request)

    def test_failed_audit_is_complete_bound_raw_feedback_and_shares_one_revision_slot(self):
        prepared=stage.base.prepare(root=stage.ROOT,packet_path=HERE/'microsoft/source_packet.json',
            skill_path=HERE/'skill.md',company_id=stage.CASES['microsoft'][0],document_id=stage.CASES['microsoft'][1],
            period_end=stage.CASES['microsoft'][2],model='claude-sonnet-5-5',effort='high',max_tokens=32000,
            timeout_seconds=600,stream=True,contract_version='business-draft-v2',thinking_type='between_tools')
        try:
            audit_path=HERE/'microsoft/audit-01'
            candidate=json.loads((HERE/'microsoft/protocol-repair-01/draft.json').read_text())
            inventory=json.loads((stage.ROOT/'experiments/agent_design/2026-10-07-business-coverage-v1/run-06/inventory/inventory.json').read_text())
            dependencies={}
            raw,error=stage.load_failed_audit(audit_path,prepared,dependencies,inventory=inventory,candidate=candidate)
            self.assertEqual(error,'attribute_excerpt_does_not_locate_mention')
            self.assertEqual((len(raw['mappings']),len(raw['checks'])),(148,130))
            self.assertEqual(raw,json.loads((audit_path/'response.txt').read_text()))
            self.assertEqual(len(dependencies),9)
            kwargs,_=stage.run.request_for(prepared,'revision_from_failed_audit',inventory=inventory,
                candidate=candidate,own_failed_audit=raw,audit_protocol_error=error)
            payload=json.loads(kwargs['input'])
            self.assertEqual(set(payload),{'frozen_source_packet','source_inventory','own_candidate',
                'candidate_sha256','inventory_sha256','own_failed_audit','audit_protocol_error'})
            self.assertNotIn('computed_status',payload['own_failed_audit'])
            different=deepcopy(candidate);different['summary']+=' Different candidate scope.'
            with self.assertRaisesRegex(ValueError,'not_own_source_inventory_candidate'):
                stage.load_failed_audit(audit_path,prepared,{},inventory=inventory,candidate=different)
            self.assertEqual(stage.MODES['revision'][0],stage.MODES['revision_from_failed_audit'][0])
            self.assertEqual(stage.MODES['revision_from_failed_audit'][1],32000)
        finally:
            asyncio.run(prepared['native'].aclose())

    def test_end_turn_usage_does_not_substitute_for_settled_same_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);ledger=root/'budget.sqlite'
            result=deepcopy(self.result);result['budget_path']='budget.sqlite'
            record=result['costs']['records'][0]
            db=sqlite3.connect(ledger)
            db.execute('CREATE TABLE config (id INTEGER,usd TEXT)')
            db.execute('INSERT INTO config VALUES (1,?)',(stage.TASK_LIMIT,))
            db.execute('CREATE TABLE reservations (id TEXT,reserved TEXT,actual TEXT,state TEXT)')
            db.execute('INSERT INTO reservations VALUES (?,?,NULL,"reserved")',(record['budget_reservation_id'],record['reserved_usd']))
            db.commit()
            with patch.object(stage,'ROOT',root),patch.object(stage,'BUDGET',ledger):
                with self.assertRaisesRegex(ValueError,'charge_not_settled'):
                    stage.settled_model_response(result,self.metadata)
                db.execute('UPDATE reservations SET actual=?,state="settled"',(record['estimated_usd'],))
                db.commit()
                stage.settled_model_response(result,self.metadata)
                bad=deepcopy(self.metadata);bad['response_id']='different-response'
                with self.assertRaisesRegex(ValueError,'response_not_bound'):
                    stage.settled_model_response(result,bad)
                bad=deepcopy(result);bad['budget_path']='another-task.sqlite'
                with self.assertRaisesRegex(ValueError,'same_task_ledger'):
                    stage.settled_model_response(bad,self.metadata)
            db.close()

    def test_success_with_earlier_unknown_requires_exact_retained_reservation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);ledger=root/'budget.sqlite'
            result=deepcopy(self.result);result['budget_path']='budget.sqlite';result['status']='candidate'
            success=result['costs']['records'][0]
            failed=dict(success,call_id='earlier',budget_reservation_id='unknown-attempt',status='failed',
                estimated_usd=None,reserved_usd='0.7',response_id=None,stop_reason=None,
                started_at='2026-10-07T17:30:00+00:00',ended_at='2026-10-07T17:30:30+00:00')
            # UUID-sorted call records need not be chronological.
            result['costs'].update(records=[success,failed],requests=2,unknown_cost_requests=1)
            db=sqlite3.connect(ledger)
            self.addCleanup(db.close)
            db.execute('CREATE TABLE config (id INTEGER,usd TEXT)')
            db.execute('INSERT INTO config VALUES (1,?)',(stage.TASK_LIMIT,))
            db.execute('CREATE TABLE reservations (id TEXT,reserved TEXT,actual TEXT,state TEXT)')
            db.execute('INSERT INTO reservations VALUES (?,?,?,"settled")',
                       (success['budget_reservation_id'],success['reserved_usd'],success['estimated_usd']))
            db.execute('INSERT INTO reservations VALUES ("unknown-attempt","0.7",NULL,"unknown")')
            db.commit()
            with patch.object(stage,'ROOT',root),patch.object(stage,'BUDGET',ledger):
                before=db.execute('SELECT * FROM reservations ORDER BY id').fetchall()
                stage.settled_model_response(result,self.metadata,allow_unknown_retries=True)
                self.assertEqual(before,db.execute('SELECT * FROM reservations ORDER BY id').fetchall())
                with self.assertRaisesRegex(ValueError,'cost_must_be_known'):
                    stage.settled_model_response(result,self.metadata)
                for reserved,actual,state_value in [('0.6',None,'unknown'),('0.7','0','unknown'),
                                                     ('0.7',None,'reserved'),('0.7','0','settled')]:
                    db.execute('UPDATE reservations SET reserved=?,actual=?,state=? WHERE id="unknown-attempt"',
                               (reserved,actual,state_value));db.commit()
                    with self.subTest(reserved=reserved,actual=actual,state=state_value),self.assertRaisesRegex(ValueError,'not_preserved'):
                        stage.settled_model_response(result,self.metadata,allow_unknown_retries=True)
                db.execute('UPDATE reservations SET reserved="0.7",actual=NULL,state="unknown" WHERE id="unknown-attempt"');db.commit()
                wrong=deepcopy(result);wrong['costs']['records'][1]['request_sha256']='different-request'
                with self.assertRaisesRegex(ValueError,'retry_request_changed'):
                    stage.settled_model_response(wrong,self.metadata,allow_unknown_retries=True)
                late=deepcopy(result);late['costs']['records'][1]['ended_at']='2026-10-07T18:00:00+00:00'
                with self.assertRaisesRegex(ValueError,'not_before_success'):
                    stage.settled_model_response(late,self.metadata,allow_unknown_retries=True)
                db.execute('DELETE FROM reservations WHERE id="unknown-attempt"');db.commit()
                with self.assertRaisesRegex(ValueError,'not_preserved'):
                    stage.settled_model_response(result,self.metadata,allow_unknown_retries=True)


if __name__=='__main__':unittest.main()
