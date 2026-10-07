"""Launcher provenance and syntax guards; no live model request."""
from copy import deepcopy
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import run_critic_revision as launcher


class LauncherTests(unittest.IsolatedAsyncioTestCase):
    def test_syntax_recovery_is_whole_envelope_only_and_keeps_original_hash(self):
        plain='{"schema_version":"example","value":1}'
        a,ea=launcher.patch_response(plain)
        fenced='```json\n'+plain+'\n```'
        b,eb=launcher.patch_response(fenced)
        self.assertEqual(a,b)
        self.assertEqual(ea['method'],'strict_json')
        self.assertEqual(eb['method'],'remove_single_complete_json_code_fence')
        self.assertEqual(eb['raw_response_sha256'],launcher.base.digest(fenced.encode()))
        self.assertFalse(eb['semantic_changes'])
        for text in ('extra\n'+fenced,fenced+'\nextra','```json\n'+plain,'```json\n{"x":"```"}\n```'):
            with self.subTest(text=text),self.assertRaises(ValueError):launcher.patch_response(text)

    def test_readonly_budget_retains_unknown_reservation_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'existing.sqlite'
            db=sqlite3.connect(path)
            db.execute('CREATE TABLE config (id INTEGER,usd TEXT)');db.execute('INSERT INTO config VALUES (1,"8")')
            db.execute('CREATE TABLE reservations (reserved TEXT,actual TEXT,state TEXT)')
            db.execute('INSERT INTO reservations VALUES ("0.7",NULL,"unknown")')
            db.execute('INSERT INTO reservations VALUES ("1","0.5","settled")');db.commit();db.close()
            before=path.read_bytes()
            with patch.object(launcher.stages,'ROOT',root),patch.object(launcher.stages,'BUDGET',path):
                state=launcher.ReadOnlyBudget().summary()
            self.assertEqual((state['estimated_spent_usd'],state['held_usd'],state['unknown_requests']),('0.5','0.7',1))
            self.assertEqual(before,path.read_bytes())

    def test_only_two_explicit_forward_lineages_are_allowed(self):
        launcher.validate_lineage('critic-revision-01','revision-01','opus-critic-02')
        launcher.validate_lineage('critic-revision-02','critic-revision-01','opus-critic-03')
        for output,parent,critic in (
            ('critic-revision-02','revision-01','opus-critic-03'),
            ('critic-revision-02','critic-revision-01','opus-critic-02'),
            ('critic-revision-01','critic-revision-01','opus-critic-03'),
            ('critic-revision-01','critic-revision-02','opus-critic-03')):
            with self.subTest(output=output,parent=parent,critic=critic),self.assertRaisesRegex(ValueError,'forward_patch_lineage'):
                launcher.validate_lineage(output,parent,critic)

    async def test_real_patch01_replays_and_opus03_binds_pointer_request(self):
        stages=launcher.stages
        prepared=launcher.base.prepare(root=stages.ROOT,packet_path=stages.HERE/'microsoft/source_packet.json',
            skill_path=stages.HERE/'skill.md',company_id=stages.CASES['microsoft'][0],document_id=stages.CASES['microsoft'][1],
            period_end=stages.CASES['microsoft'][2],model='claude-sonnet-5-5',effort='high',max_tokens=16000,
            timeout_seconds=600,stream=True,contract_version='business-draft-v2',thinking_type='between_tools')
        try:
            company=stages.HERE/'microsoft'
            candidate=await launcher.load_patch_stage(company/'critic-revision-01',prepared,{})
            self.assertEqual(candidate,json.loads((company/'critic-revision-01/draft.json').read_text()))
            candidate2,review,origins=await launcher.load_inputs(prepared,{},'opus-critic-03',candidate_stage='critic-revision-01')
            self.assertEqual(candidate2,candidate)
            self.assertEqual((review['status'],len(review['issues']),len(review['reviewed_check_keys'])),('needs_revision',9,138))
            self.assertEqual(Path(origins['candidate']['candidate_path']).parent.name,'critic-revision-01')
            with self.assertRaisesRegex(ValueError,'patch_lineage_cycle'):
                await launcher.load_patch_stage(company/'critic-revision-01',prepared,{},_visited=(company/'critic-revision-01',))
        finally:await prepared['native'].aclose()

    async def test_real_fenced_critic_requires_explicit_exact_recovery_and_producer(self):
        stages=launcher.stages
        prepared=launcher.base.prepare(root=stages.ROOT,packet_path=stages.HERE/'microsoft/source_packet.json',
            skill_path=stages.HERE/'skill.md',company_id=stages.CASES['microsoft'][0],document_id=stages.CASES['microsoft'][1],
            period_end=stages.CASES['microsoft'][2],model='claude-sonnet-5-5',effort='high',max_tokens=32000,
            timeout_seconds=600,stream=True,contract_version='business-draft-v2',thinking_type='between_tools')
        try:
            company=stages.HERE/'microsoft';receipt=company/'opus-critic-02-envelope-recovery.json'
            candidate,review,origins=await launcher.load_inputs(prepared,{},'opus-critic-02',receipt)
            self.assertEqual((review['status'],len(review['issues']),len(review['reviewed_check_keys'])),('needs_revision',16,153))
            self.assertEqual(origins['critic']['original_stage_status'],'failed')
            with self.assertRaises((ValueError,FileNotFoundError)):
                await launcher.load_inputs(prepared,{},'opus-critic-02')
            different=deepcopy(candidate);different['summary']+=' Unrelated candidate.'
            with self.assertRaisesRegex(ValueError,'producer_mismatch'):
                await launcher.load_critic_review(company/'opus-critic-02',prepared,{},candidate=different,
                    candidate_path=company/'revision-01',recovery_path=receipt)
        finally:await prepared['native'].aclose()


if __name__=='__main__':unittest.main()
