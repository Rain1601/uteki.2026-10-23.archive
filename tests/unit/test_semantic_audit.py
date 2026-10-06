"""Critic protocol authenticity is checked independently of critic semantic truth."""
from copy import deepcopy
import unittest

from tests.unit import test_semantic_review_v2 as birch_fixture
from tests.unit.test_semantic_review_loop import audit_reply
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.semantic_audit import build_semantic_audit_input, validate_semantic_audit


class SemanticAuditContractTests(unittest.TestCase):
    def setUp(self):
        self.fixture = birch_fixture.SemanticReviewV2Tests()
        self.packet = self.fixture.packet()
        self.packet['schema_version'] = 'semantic-review-input-v3'; self.fixture.seal(self.packet)
        self.assessment = self.fixture.response(self.packet)
        self.request = build_semantic_audit_input(self.packet, self.assessment)

    def test_input_binds_normalized_assessment_and_isolates_source_objects(self):
        self.assertEqual(self.request['assessment_sha256'], digest(self.request['assessment']))
        self.assertEqual(self.request['packet'], self.packet)
        self.request['packet']['source_blocks'][0]['text'] = 'changed copy'
        self.assertNotEqual(self.request['packet']['source_blocks'][0]['text'], self.packet['source_blocks'][0]['text'])
        self.assertNotIn('expected', self.request)

    def test_empty_issues_pass_is_a_bound_opinion_not_semantic_truth(self):
        result = validate_semantic_audit(self.packet, self.assessment, audit_reply(self.request))
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['issues'], [])

    def test_revision_can_describe_absence_of_support_without_inventing_citation(self):
        response = audit_reply(self.request, 'revise')
        response['issues'][0]['location'] = 'checks.0.constraints'
        result = validate_semantic_audit(self.packet, self.assessment, response)
        self.assertEqual(result['issues'][0]['citations'], [])

    def test_suggestion_only_can_pass_but_cannot_require_revision(self):
        response = audit_reply(self.request, 'revise')
        response['issues'][0]['severity'] = 'suggestion'
        response['status'] = 'pass'
        result = validate_semantic_audit(self.packet, self.assessment, response)
        self.assertEqual(result['status'], 'pass')
        self.assertEqual(result['issues'][0]['severity'], 'suggestion')
        response['status'] = 'revise'
        with self.assertRaises(ValueError): validate_semantic_audit(self.packet, self.assessment, response)

    def test_error_default_or_explicit_blocks_pass_and_mixed_issues_require_revision(self):
        response = audit_reply(self.request, 'revise')
        default = validate_semantic_audit(self.packet, self.assessment, response)
        self.assertEqual(default['issues'][0]['severity'], 'error')
        response['issues'][0]['severity'] = 'error'
        suggestion = deepcopy(response['issues'][0]); suggestion.update(issue_id='suggestion-1', severity='suggestion')
        response['issues'].append(suggestion)
        self.assertEqual(validate_semantic_audit(self.packet, self.assessment, response)['status'], 'revise')
        response['status'] = 'pass'
        with self.assertRaises(ValueError): validate_semantic_audit(self.packet, self.assessment, response)

    def test_packet_hash_and_changed_assessment_cannot_reuse_old_audit(self):
        for mode in ('packet', 'hash', 'changed-assessment'):
            response = audit_reply(self.request)
            assessment = deepcopy(self.assessment)
            if mode == 'packet': response['packet_id'] = 'semantic-other'
            elif mode == 'hash': response['assessment_sha256'] = '0'*64
            else: assessment['checks'][0]['reason'] = 'A materially different assessment version.'
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                validate_semantic_audit(self.packet, assessment, response)

    def test_nonexistent_and_executable_or_noncanonical_paths_are_rejected(self):
        for location in ('checks.99.reason', 'checks.0.missing', 'checks.-1.reason', 'checks.00.reason',
                         '__import__("os")', 'checks[0].reason'):
            response = audit_reply(self.request, 'revise'); response['issues'][0]['location'] = location
            with self.subTest(location=location), self.assertRaises(ValueError):
                validate_semantic_audit(self.packet, self.assessment, response)

    def test_issue_record_scope_duplicates_and_pass_revise_consistency(self):
        for mode in ('foreign-record', 'duplicate-record', 'duplicate-issue', 'pass-with-issue', 'revise-empty'):
            response = audit_reply(self.request, 'revise')
            if mode == 'foreign-record': response['issues'][0]['record_ids'] = ['other-source-record']
            elif mode == 'duplicate-record': response['issues'][0]['record_ids'] = [next(iter(self.packet['record_anchors']))]*2
            elif mode == 'duplicate-issue': response['issues'] *= 2
            elif mode == 'pass-with-issue': response['status'] = 'pass'
            else: response['issues'] = []
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                validate_semantic_audit(self.packet, self.assessment, response)

    def test_unique_citation_offset_is_canonicalized_without_mutating_raw_reply(self):
        response = audit_reply(self.request, 'revise')
        citation = self.fixture.citation(self.packet, 'Operating income 20 20')
        expected_offset = citation.pop('source_start')
        response['issues'][0]['citations'] = [citation]
        original = deepcopy(response)
        result = validate_semantic_audit(self.packet, self.assessment, response)
        self.assertEqual(result['issues'][0]['citations'][0]['source_start'], expected_offset)
        self.assertEqual(response, original)

    def test_foreign_false_wrong_offset_and_ambiguous_quote_are_rejected(self):
        for mode in ('foreign', 'false', 'offset', 'ambiguous'):
            response = audit_reply(self.request, 'revise')
            citation = self.fixture.citation(self.packet, 'Revenue 20 20')
            if mode == 'foreign': citation['source_snapshot_id'] = 'other-source'
            elif mode == 'false': citation['quote'] = 'invented evidence'
            elif mode == 'offset': citation['source_start'] += 1
            else: citation.pop('source_start')
            response['issues'][0]['citations'] = [citation]
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                validate_semantic_audit(self.packet, self.assessment, response)


if __name__ == '__main__': unittest.main()
