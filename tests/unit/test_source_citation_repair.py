"""Exact-source repair boundaries and sealed replay; no model quality claims."""
import asyncio
from copy import deepcopy
import json
import unittest

from tests.unit import test_independent_question_handoff as independent
from tests.unit.test_source_review_policy import response
from tests.unit.test_answer_handoff import ScriptedRole
from uteki.agents.data_query import answer_handoff as h
from uteki.agents.data_query import retrieval_cycle as cycle


class SourceCitationRepairTests(unittest.TestCase):
    def setUp(self):
        self.base = independent.IndependentQuestionHandoffTests(); self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.packet = self.base.packet
        self.good = response(self.packet)
        self.bad = deepcopy(self.good)
        self.bad['facts'][0]['citations'][0]['quote'] = 'Invented quoted text'

    def run_review(self, replies, *, allow=True, name='review'):
        def respond(packet):
            return deepcopy(replies[len(source.packets)-1])
        source = ScriptedRole(respond)
        question = ScriptedRole(independent.question_response)
        path = self.base.root/name
        result = asyncio.run(h.review_data_answer(self.packet, path,
            reviewer_factory=lambda p: source, question_reviewer_factory=lambda p: question,
            allow_source_protocol_repair=allow))
        return result, path, source, question

    def test_all_citation_locations_are_returned_without_replacement_quotes(self):
        bad = deepcopy(self.bad)
        bad['requirements'][0]['citations'] = deepcopy(bad['facts'][0]['citations'])
        with self.assertRaises(h.SourceCitationProtocolError) as caught:
            h._validate_source_assessment(self.packet, bad)
        errors = caught.exception.diagnostic['errors']
        self.assertEqual(len(errors),2)
        self.assertEqual(errors[0]['field_pointer'],'/facts/0/citations/0')
        self.assertEqual(errors[1]['field_pointer'],'/requirements/0/citations/0')
        self.assertTrue(all(e['code']=='citation_quote_not_literal' for e in errors))
        self.assertTrue(all(e['constraint_pointer'].endswith('/text') for e in errors))
        self.assertNotIn('Invented quoted text',str(errors))
        repair = h.source_review_repair_input(self.packet,bad,max_bytes=100000)
        self.assertEqual(repair['packet'],self.packet)
        self.assertEqual(repair['previous_assessment'],bad)
        self.assertEqual(bad['facts'][0]['citations'][0]['quote'],'Invented quoted text')

    def test_wrong_source_wrong_block_image_and_whitespace_remain_rejected(self):
        original=self.packet['source_documents'][0]['blocks'][0]
        cases=[('source_snapshot_id','foreign','citation_source_not_delivered'),
               ('block_id','unread','citation_block_not_delivered'),
               ('quote',original['text'].replace(' ','  '),'citation_quote_not_literal')]
        for field,value,code in cases:
            bad=deepcopy(self.good);bad['facts'][0]['citations'][0][field]=value
            with self.subTest(field=field),self.assertRaises(h.SourceCitationProtocolError) as caught:
                h._validate_source_assessment(self.packet,bad)
            self.assertEqual(caught.exception.diagnostic['errors'][0]['code'],code)
        p=deepcopy(self.packet);p['source_documents'][0]['blocks'][0]['type']='image'
        with self.assertRaises(h.SourceCitationProtocolError) as caught:h._validate_source_assessment(p,self.good)
        self.assertTrue(any(e['code']=='citation_image_not_read' for e in caught.exception.diagnostic['errors']))

    def test_valid_or_wrong_identity_draft_and_oversized_repair_cannot_be_sent(self):
        with self.assertRaises(ValueError):h.source_review_repair_input(self.packet,self.good,max_bytes=100000)
        bad=deepcopy(self.bad);bad['packet_id']='other'
        with self.assertRaisesRegex(ValueError,'binding'):h.source_review_repair_input(self.packet,bad,max_bytes=100000)
        with self.assertRaisesRegex(ValueError,'exceeds'):h.source_review_repair_input(self.packet,self.bad,max_bytes=20)

    def test_single_repair_preserves_first_response_and_passes_strict_loading(self):
        result,path,source,question=self.run_review([self.bad,self.good])
        self.assertEqual(result['status'],'reviewed',result)
        self.assertTrue(result['source_protocol_repair_attempted'])
        self.assertEqual(len(source.packets),2);self.assertEqual(len(question.packets),1)
        repair=source.packets[1]
        self.assertEqual(repair,h.source_review_repair_input(self.packet,self.bad,max_bytes=self.packet['max_packet_bytes']))
        self.assertEqual(json.loads((path/'source-response-01.json').read_text()),self.bad)
        self.assertEqual(json.loads((path/'source-response-02.json').read_text()),self.good)
        self.base.load(path,result['review_ref']['manifest_sha256'])
        # Reseal after altering feedback: catch semantic binding, not just a hash.
        forged=json.loads((path/'source-repair-input.json').read_text())
        forged['host_protocol_diagnostics']=[]
        (path/'source-repair-input.json').write_text(json.dumps(forged))
        (path/'manifest.json').unlink();cycle._seal(path)
        with self.assertRaisesRegex(ValueError,'repair differs'):
            self.base.load(path,cycle._reference(path)['manifest_sha256'])

    def test_second_bad_response_is_retained_and_never_eligible_or_outer_retryable(self):
        second=deepcopy(self.bad);second['facts'][0]['citations'][0]['quote']='Still invalid'
        result,path,source,question=self.run_review([self.bad,second])
        self.assertEqual(result['status'],'failed');self.assertFalse(result['review_retryable'])
        self.assertEqual(len(source.packets),2);self.assertEqual(question.packets,[])
        self.assertEqual(json.loads((path/'source-response-01.json').read_text()),self.bad)
        self.assertEqual(json.loads((path/'source-response.json').read_text()),second)
        self.assertEqual(result['failures'][0]['diagnostic']['code'],'source_citation_mismatch')

    def test_removing_all_repair_files_cannot_erase_the_declared_history(self):
        result,path,_,_=self.run_review([self.bad,self.good])
        for name in ('source-response-01.json','source-repair-input.json','source-response-02.json'):
            (path/name).unlink()
        (path/'manifest.json').unlink();cycle._seal(path)
        with self.assertRaisesRegex(ValueError,'declaration differs'):
            self.base.load(path,cycle._reference(path)['manifest_sha256'])

    def test_second_outer_attempt_does_not_add_another_source_request(self):
        result,path,source,question=self.run_review([self.bad],allow=False)
        self.assertEqual(result['status'],'failed');self.assertEqual(len(source.packets),1)
        self.assertFalse((path/'source-repair-input.json').exists())
        self.assertEqual(question.packets,[])

    def test_correct_citations_do_not_override_missing_semantic_coverage(self):
        revised=deepcopy(self.good)
        revised['question_coverage']='incomplete';revised['missing_information']=['Required evidence is missing.']
        result,path,source,question=self.run_review([self.bad,revised])
        self.assertEqual(result['status'],'needs_revision');self.assertFalse(result['analysis_eligible'])
        self.assertEqual(len(source.packets),2)
