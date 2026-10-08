"""Scope is an allowlist; review sufficiency follows question and delivered bodies."""
import asyncio
from copy import deepcopy
import unittest
from tests.unit import test_analysis_evidence_runtime as fixtures
from tests.unit.test_autonomous_source_evidence import source_plan, context_read
from tests.unit.test_bounded_answer_handoff import narrow_assessment
from tests.unit.test_answer_handoff import ScriptedRole
from uteki.agents.data_query.answer_handoff import prepare_review_packet, validate_assessment, review_data_answer, load_reviewed_data, review_prompt, ReviewProtocolError


def response(packet):
    result=narrow_assessment(packet)
    for f in result['facts']:f['relevance']='necessary'
    result['body_checks']=[{'source_snapshot_id':d['source_snapshot_id'],'block_id':b['block_id'],
        'relevance':'necessary','rationale':'Necessary original material for fixture question.'}
        for d in packet['source_documents'] for b in d['blocks']]
    return result


class SourceReviewPolicyTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.AnalysisEvidenceRuntimeTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.fixture.scope=self.fixture.scope.model_copy(update={'source_snapshot_ids':('acme-annual','acme-amended','acme-future')})
        self.fixture.request={'question':'Retrieve original Acme product material from the annual report.',
            'scope':self.fixture.scope.model_dump(mode='json')}
        _,_,self.query=self.fixture.run_actions([source_plan(),context_read(),fixtures.choose('b1'),{'action':'finish'}])
        self.packet=self.prepare()

    def prepare(self, **kwargs):
        return prepare_review_packet(self.query,self.fixture.dataset,expected_scope=self.fixture.scope,
            max_packet_bytes=100000,source_delivery='query_evidence_v1',**kwargs)

    def test_unused_available_and_future_sources_do_not_force_extra_delivery(self):
        p=self.packet
        self.assertEqual(p['source_review_policy'],'delivered-sources-v2')
        self.assertEqual(p['source_check_ids'],['acme-annual'])
        rows={s['source_snapshot_id']:s for s in p['scope_source_availability']}
        self.assertEqual(rows['acme-future']['status'],'not_available_at_cutoff')
        self.assertEqual(rows['acme-amended']['status'],'available_candidate')
        self.assertTrue(all(set(s)=={'source_snapshot_id','company_id','source_period_end','available_at','status'} for s in rows.values()))
        self.assertEqual([d['source_snapshot_id'] for d in p['source_documents']],['acme-annual'])
        self.assertTrue(validate_assessment(p,response(p))[1])
        out=self.fixture.root/'new-review'
        result=asyncio.run(review_data_answer(p,out,reviewer_factory=lambda path:ScriptedRole(response)))
        self.assertTrue(result['analysis_eligible'],result)
        handoff=load_reviewed_data(out,expected_scope=self.fixture.scope,
            expected_review_manifest_sha256=result['review_ref']['manifest_sha256'],allow_fixture=True)
        self.assertEqual(len(handoff['source_documents']),1)

    def test_missing_required_second_version_is_still_ineligible(self):
        p=deepcopy(self.packet)
        p['question']='Compare the original and amended report.'
        p['requirements'].append({**p['requirements'][0],'requirement_id':'second-version','source_id':'acme-amended'})
        # Even a falsely optimistic fixture reviewer cannot override the known
        # source-bound requirement that has no delivered source.
        self.assertFalse(validate_assessment(p,response(p))[1])
        r=response(p);r.update(question_coverage='incomplete',missing_information=['The amended version is missing.'])
        self.assertFalse(validate_assessment(p,r)[1])

    def test_future_body_and_forged_availability_are_rejected(self):
        for change in ('body','metadata'):
            p=deepcopy(self.packet)
            if change=='body':p['source_documents'][0]['source_snapshot_id']='acme-future'
            else: next(s for s in p['scope_source_availability'] if s['source_snapshot_id']=='acme-future')['status']='available_candidate'
            with self.subTest(change=change),self.assertRaises(ValueError):validate_assessment(p,response(p))

    def test_empty_packet_does_not_pass_vacuously(self):
        p=deepcopy(self.packet);p.update(facts=[],requirements=[],source_documents=[],source_check_ids=[],program_gaps=[],query_gaps=[])
        self.assertFalse(validate_assessment(p,response(p))[1])

    def test_legacy_packets_keep_all_scope_checks_and_rebuild_identically(self):
        p=self.prepare(source_review_policy=None)
        self.assertNotIn('source_review_policy',p)
        with self.assertRaisesRegex(ValueError,'source_checks'):validate_assessment(p,response(p))
        r=response(p)
        for sid in ('acme-amended','acme-future'):
            r['source_checks'].append({'source_snapshot_id':sid,'verdict':'requires_more_source_content',
                'rationale':'Legacy protocol requires every scoped source.','citations':[]})
        self.assertFalse(validate_assessment(p,r)[1])
        result=asyncio.run(review_data_answer(p,self.fixture.root/'old-review',reviewer_factory=lambda path:ScriptedRole(lambda packet:r)))
        self.assertEqual(result['status'],'needs_revision',result)
        self.assertFalse(result['failures'])
        self.assertEqual(p,self.prepare(source_review_policy=None))

    def test_unknown_policy_and_incomplete_metadata_rejected(self):
        with self.assertRaises(ValueError):self.prepare(source_review_policy='unknown')
        p=deepcopy(self.packet);p['scope_source_availability'].pop()
        with self.assertRaises(ValueError):validate_assessment(p,response(p))


    def test_v1_packets_rebuild_without_new_ids_and_prompts_are_mutually_exclusive(self):
        p=self.prepare(source_review_policy='delivered-sources-v1')
        self.assertNotIn('source_check_ids',p)
        self.assertTrue(validate_assessment(p,response(p))[1])
        self.assertEqual(p,self.prepare(source_review_policy='delivered-sources-v1'))
        self.assertIn('source_check_ids',review_prompt(self.packet))
        self.assertNotIn('must cover every source_snapshot_id in scope',review_prompt(self.packet))
        self.assertNotIn('source_check_ids',review_prompt(p))
        self.assertIn('cover every source_snapshot_id in scope',review_prompt({}))

    def test_ids_cannot_add_a_future_source_or_omit_a_delivered_source(self):
        for ids in ([],['acme-annual','acme-future']):
            p=deepcopy(self.packet);p['source_check_ids']=ids
            with self.subTest(ids=ids),self.assertRaisesRegex(ValueError,'source_check_ids'):
                validate_assessment(p,response(p))

    def test_contract_failure_records_safe_diagnostic_without_rewriting_response(self):
        r=response(self.packet)
        r['source_checks'].append({'source_snapshot_id':'acme-future','verdict':'text_sufficient',
            'rationale':'Wrong extra row, even if exclusion was understood.','citations':[]})
        before=deepcopy(r)
        with self.assertRaises(ReviewProtocolError) as caught:validate_assessment(self.packet,r)
        self.assertEqual(caught.exception.diagnostic['expected_source_ids'],['acme-annual'])
        self.assertEqual(caught.exception.diagnostic['returned_known_source_ids'],['acme-annual','acme-future'])
        self.assertEqual(r,before)
        result=asyncio.run(review_data_answer(self.packet,self.fixture.root/'bad-review',
            reviewer_factory=lambda path:ScriptedRole(lambda p:r)))
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['failures'][0]['diagnostic']['code'],'source_checks_identity_mismatch')
        r['source_checks'][-1]['source_snapshot_id']='arbitrary-provider-text'
        with self.assertRaises(ReviewProtocolError) as caught:validate_assessment(self.packet,r)
        self.assertNotIn('arbitrary-provider-text',str(caught.exception.diagnostic))
        self.assertEqual(caught.exception.diagnostic['unknown_source_id_count'],1)

    def test_current_body_contract_and_safe_missing_identity_diagnostic(self):
        prompt = review_prompt(self.packet)
        self.assertIn('CURRENT REQUEST CONTRACT', prompt)
        self.assertIn('"block_id":"b1"', prompt)
        self.assertNotIn('CURRENT REQUEST CONTRACT', review_prompt({}))
        r = response(self.packet)
        r['body_checks'] = []
        before = deepcopy(r)
        with self.assertRaises(ReviewProtocolError) as caught:
            validate_assessment(self.packet, r)
        diagnostic = caught.exception.diagnostic
        self.assertEqual(diagnostic['code'], 'body_checks_identity_mismatch')
        self.assertGreater(diagnostic['expected_body_count'], 0)
        self.assertEqual(diagnostic['returned_body_count'], 0)
        self.assertEqual(r, before)
        r['body_checks'] = [{'source_snapshot_id':'untrusted', 'block_id':'provider-text',
                            'relevance':'necessary', 'rationale':'Wrong identity.'}]
        with self.assertRaises(ReviewProtocolError) as caught:
            validate_assessment(self.packet, r)
        self.assertEqual(caught.exception.diagnostic['unknown_body_count'], 1)
        self.assertNotIn('provider-text', str(caught.exception.diagnostic))


if __name__=='__main__':unittest.main()
