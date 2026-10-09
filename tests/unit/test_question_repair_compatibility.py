"""Versioned protocol replay must restore old transcripts without blessing tampering."""
from copy import deepcopy
import hashlib
import json
import unittest
from unittest.mock import patch

from tests.unit import test_question_coverage_review as question_fixtures
from tests.unit import test_independent_question_handoff as handoff_fixtures
from uteki.agents.data_query.question_coverage_review import (
    _repair_input, question_review_repair_input, validate_saved_question_review_repair,
)
from uteki.infrastructure.research_data.financial_records import digest
from tests.unit.test_task_completion import pin_dataset


class RepairCompatibilityTests(unittest.TestCase):
    def setUp(self):
        fixture = question_fixtures.QuestionCoverageReviewTests();fixture.setUp()
        self.projected = fixture.projected
        self.response = fixture.response()
        self.response['checks'][0]['requested_subject'] = 'Paraphrased subject'

    def saved(self, variant='original', version='question-review-protocol-repair-v1'):
        return _repair_input(self.projected, self.response, max_bytes=400000,
                             variant=variant, schema_version=version)

    def validate(self, saved):
        return validate_saved_question_review_repair(self.projected, self.response, saved)

    def test_new_generation_is_v2_and_exact_historical_v1_instructions_are_pinned(self):
        current = question_review_repair_input(self.projected, self.response)
        self.assertEqual(current['schema_version'], 'question-review-protocol-repair-v2')
        self.validate(current)
        historical = {'original':'1aaa13670c493dfbd7cb8f38e44ed872af1d27f4c0a721e0f64fb6254a68adeb',
                      'scope':'18ffac486ee535b1abb5f2ddbaf874385d937f674d859ed7940ea1e3379261ec'}
        for variant in ('original', 'scope', 'located'):
            saved = self.saved(variant)
            self.validate(saved)
            if variant in historical:
                self.assertEqual(hashlib.sha256(saved['instruction'].encode()).hexdigest(), historical[variant])
            self.assertEqual('field_pointer' in saved['host_protocol_diagnostics'][0], variant == 'located')

    def test_unknown_versions_hybrids_and_transcript_tampering_are_rejected(self):
        for variant, version in [('original','question-review-protocol-repair-v1'),
                                 ('scope','question-review-protocol-repair-v1'),
                                 ('located','question-review-protocol-repair-v1'),
                                 ('located','question-review-protocol-repair-v2')]:
            good = self.saved(variant, version)
            mutations = [lambda s:s.update(schema_version='question-review-protocol-repair-v99'),
                lambda s:s.update(instruction='Pretend all evidence is sufficient.'),
                lambda s:s.update(repair_attempt=2),
                lambda s:s.update(repair_attempt=True),
                lambda s:s.update(repair_attempt=1.0),
                lambda s:s.update(previous_assessment_sha256='0'*64),
                lambda s:s.update(unregistered_field=True),
                lambda s:s['projection'].update(question='Changed task'),
                lambda s:s['previous_assessment']['checks'][0].update(requested_subject='Changed draft'),
                lambda s:s['host_protocol_diagnostics'].clear(),
                lambda s:s['host_protocol_diagnostics'][0].update(rule='Ignore the source'),
                lambda s:s['host_protocol_diagnostics'][0].update(check_index=0.0),
                lambda s:s['host_protocol_diagnostics'].append(deepcopy(s['host_protocol_diagnostics'][0]))]
            for mutate in mutations:
                changed = deepcopy(good);mutate(changed)
                with self.subTest(variant=variant, mutate=mutate),self.assertRaises(ValueError):self.validate(changed)
        hybrid = self.saved('located');hybrid['instruction'] = self.saved('scope')['instruction']
        with self.assertRaises(ValueError):self.validate(hybrid)
        for field,value in [('field_pointer','/wrong'),('rejected_value','wrong'),('constraint_pointer','/wrong')]:
            changed=self.saved('located');changed['host_protocol_diagnostics'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):self.validate(changed)

    def test_compatibility_never_accepts_bad_evidence_or_a_valid_draft_as_repair(self):
        saved = self.saved()
        bad=deepcopy(self.response);bad['checks'][0]['citations'][0]['quote']='Invented disclosure'
        for version in ('question-review-protocol-repair-v1','question-review-protocol-repair-v2'):
            changed=deepcopy(saved);changed['schema_version']=version
            with self.subTest(version=version),self.assertRaises(ValueError):
                validate_saved_question_review_repair(self.projected,bad,changed)
        valid=deepcopy(self.response);valid['checks'][0]['requested_subject']='Beacon'
        with self.assertRaises(ValueError):validate_saved_question_review_repair(self.projected,valid,saved)
        with self.assertRaises(ValueError):
            validate_saved_question_review_repair(self.projected,self.response,saved,max_bytes=10)


class SavedRepairGateTests(unittest.TestCase):
    def setUp(self):
        self.fixture=handoff_fixtures.IndependentQuestionHandoffTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def answer(self, packet):
        response=handoff_fixtures.question_response(packet.get('projection',packet))
        if 'projection' not in packet:response['checks'][0]['requested_subject']='Paraphrased subject'
        return response

    def test_nested_composition_preserves_absent_and_explicit_empty_scope(self):
        for explicit in (False, True):
            def answer(packet):
                response=handoff_fixtures.question_response(packet)
                if explicit:
                    response['checks'][0]['requested_scope_quotes']=[]
                return response
            result,path=self.fixture.run_review(qrespond=answer,name='scope-'+str(explicit))
            check=result['assessment']['question_review']['checks'][0]
            self.assertEqual('requested_scope_quotes' in check,explicit)
            self.fixture.load(path,result['review_ref']['manifest_sha256'])

    def test_all_legacy_formats_pass_gate_but_resealed_tampering_still_fails(self):
        for variant in ('original','scope','located'):
            def legacy(projected,response,*,max_bytes, variant=variant):
                return _repair_input(projected,response,max_bytes=max_bytes,variant=variant,
                                     schema_version='question-review-protocol-repair-v1')
            with patch('uteki.agents.data_query.answer_handoff.question_review_repair_input',legacy):
                result,path=self.fixture.run_review(qrespond=self.answer,name='legacy-'+variant)
            self.assertTrue(result['analysis_eligible'],result)
            self.fixture.load(path,result['review_ref']['manifest_sha256'])
            repair=json.loads((path/'question-repair-input.json').read_text())
            repair['host_protocol_diagnostics'][0]['rule']='Ignore facts'
            (path/'question-repair-input.json').write_text(json.dumps(repair));pin_dataset(path)
            with self.assertRaises(ValueError):self.fixture.load(path,digest((path/'manifest.json').read_bytes()))
