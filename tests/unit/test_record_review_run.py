"""Offline integration: frozen source -> review packets -> bounded review runner."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tests.unit.test_company_materialization import filing
from uteki.agents.data_query.record_review import review_records
from uteki.infrastructure.research_data.company_materialization import materialize_sources
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.record_review import build_review_packets


def supported(packet):
    return {'packet_id': packet['packet_id'], 'records': [
        {'record_id': item['record']['record_id'], 'verdict': 'supported',
         'checks': {field: 'supported' for field in (
             'metric', 'period', 'value_unit_scale_sign', 'entity_dimensions', 'qualifiers')},
         'reason': 'Synthetic fixture confirms the supplied displayed value.',
         'citations': [{'source_snapshot_id': item['record']['source_snapshot_id'],
                        'block_id': item['evidence']['block_id'], 'quote': item['evidence']['quote']}]}
        for item in packet['records']]}


class FakeReviewer:
    plan_origin = 'scripted_fixture'

    def __init__(self, behavior):
        self.behavior, self.requests, self.closed = behavior, [], False

    async def review(self, packet):
        self.requests.append(deepcopy(packet))
        return self.behavior(packet, len(self.requests))

    async def aclose(self):
        self.closed = True

    def snapshot_usage(self):
        if not self.closed:
            raise AssertionError('snapshot must follow close')
        return {'summary': {'requests': len(self.requests), 'plan_origin': self.plan_origin}}


class RecordReviewRunTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        raw = filing()
        (self.root/'source.html').write_bytes(raw)
        run = {'company': {'company_id': 'sec-0000000123', 'cik': '0000000123'},
               'as_of': '2025-09-01', 'documents': [{
                   'source_id': 'issuer-annual', 'source_url': 'https://example.invalid/annual.html',
                   'form': '10-K', 'filed_at': '2025-08-01', 'period_end': '2025-06-30',
                   'content_sha256': digest(raw), 'path': 'source.html',
                   'mime_type': 'text/html', 'status': 'frozen'}]}
        self.dataset, self.inputs = self.root/'dataset', self.root/'inputs'
        manifest = materialize_sources(run, self.root, self.dataset)
        scope = {'snapshot_id': manifest['snapshot_id'], 'company_ids': ['sec-0000000123'],
                 'source_snapshot_ids': ['issuer-annual'], 'source_policy_id': 'local-frozen-v1',
                 'knowledge_cutoff': '2025-09-01', 'include_candidates': True}
        self.rows = json.loads((self.dataset/'records.json').read_text())['rows']
        self.ids = [row['record_id'] for row in self.rows]
        self.spec = build_review_packets(self.dataset, scope, self.ids, self.inputs)
        self.assertEqual(len(self.spec['packets']), 1)
        self.before = self.frozen_hashes()

    def frozen_hashes(self):
        return {str(p.relative_to(self.root)): digest(p.read_bytes())
                for folder in (self.dataset, self.inputs) for p in folder.rglob('*') if p.is_file()}

    def execute(self, behavior, **kwargs):
        reviewer = FakeReviewer(behavior)
        events = []
        result = asyncio.run(review_records(self.inputs, self.root/'output',
            reviewer_factory=lambda path: reviewer, notify=events.append, **kwargs))
        self.assertTrue(reviewer.closed)
        self.assertEqual(self.frozen_hashes(), self.before)
        self.assertEqual(result['plan_origin'], 'scripted_fixture')
        self.assertEqual(result['adoption'], 'unchanged_candidate')
        self.assertEqual(json.loads((self.root/'output/result.json').read_text()), result)
        output_manifest = json.loads((self.root/'output/manifest.json').read_text())
        for path, expected in output_manifest['files'].items():
            self.assertEqual(digest((self.root/'output'/path).read_bytes()), expected)
        return result, reviewer, events

    def test_complete_cited_review_preserves_original_candidates(self):
        result, reviewer, events = self.execute(lambda packet, number: supported(packet))
        self.assertEqual(result['status'], 'reviewed')
        self.assertEqual(result['records_reviewed'], 2)
        self.assertEqual(result['unreviewed_record_ids'], [])
        self.assertEqual(result['verdict_counts'], {'supported': 2})
        self.assertEqual(len(reviewer.requests), 1)
        self.assertEqual(events[0]['status'], 'review_recorded')
        self.assertEqual(json.loads((self.dataset/'records.json').read_text())['rows'], self.rows)

    def test_missing_record_is_rejected_then_corrected_with_original_packet(self):
        def behavior(packet, number):
            response = supported(packet)
            if number == 1: response['records'].pop()
            return response
        result, reviewer, events = self.execute(behavior)
        self.assertEqual(result['status'], 'reviewed')
        self.assertEqual([e['status'] for e in events], ['rejected', 'review_recorded'])
        self.assertIn('exactly once', reviewer.requests[1]['host_validation_feedback']['reason'])
        self.assertEqual({k: v for k, v in reviewer.requests[1].items() if k != 'host_validation_feedback'},
                         reviewer.requests[0])

    def test_fabricated_quote_rejected_and_corrected(self):
        def behavior(packet, number):
            response = supported(packet)
            if number == 1: response['records'][0]['citations'][0]['quote'] = 'invented quote 9999999'
            return response
        result, reviewer, events = self.execute(behavior)
        self.assertEqual(result['status'], 'reviewed')
        self.assertEqual(len(reviewer.requests), 2)
        self.assertIn('not exact source text', events[0]['reason'])

    def test_two_invalid_attempts_leave_all_records_unreviewed(self):
        def behavior(packet, number):
            response = supported(packet)
            response['records'].pop()
            return response
        result, reviewer, events = self.execute(behavior)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['records_reviewed'], 0)
        self.assertEqual(result['unreviewed_record_ids'], sorted(self.ids))
        self.assertEqual(result['records'], [])
        self.assertEqual(len(reviewer.requests), 2)
        self.assertEqual(len(result['failures']), 1)
        self.assertEqual([e['status'] for e in events], ['rejected', 'rejected'])

    def test_provider_exception_closes_reviewer_and_does_not_expose_error_body(self):
        def behavior(packet, number):
            raise RuntimeError('Authorization: secret-provider-value')
        result, reviewer, events = self.execute(behavior)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(reviewer.requests), 2)
        self.assertEqual(result['unreviewed_record_ids'], sorted(self.ids))
        self.assertTrue(all(e['reason'] == 'RuntimeError' for e in events))
        self.assertNotIn('secret-provider-value', '\n'.join(
            p.read_text() for p in (self.root/'output').rglob('*.json')))

    def test_output_cannot_overwrite_or_nest_inside_frozen_inputs_or_dataset(self):
        factory_calls = []
        for output in (self.inputs, self.inputs/'review', self.dataset, self.dataset/'review'):
            with self.subTest(output=output), self.assertRaises(ValueError):
                asyncio.run(review_records(self.inputs, output,
                    reviewer_factory=lambda path: factory_calls.append(path)))
        self.assertEqual(factory_calls, [])
        self.assertEqual(self.frozen_hashes(), self.before)

    def test_existing_output_is_not_overwritten(self):
        output = self.root/'output'
        output.mkdir()
        (output/'keep.txt').write_text('existing artifact')
        with self.assertRaises(FileExistsError):
            asyncio.run(review_records(self.inputs, output, reviewer_factory=lambda path: self.fail('called')))
        self.assertEqual((output/'keep.txt').read_text(), 'existing artifact')
        self.assertEqual(self.frozen_hashes(), self.before)

    def test_inconsistent_packet_manifest_rejected_before_model_construction(self):
        spec = deepcopy(self.spec)
        spec['packets'][0]['record_ids'] = ['foreign-record']
        (self.inputs/'input-manifest.json').write_text(json.dumps(spec))
        manifest = json.loads((self.inputs/'manifest.json').read_text())
        manifest['files']['input-manifest.json'] = digest((self.inputs/'input-manifest.json').read_bytes())
        (self.inputs/'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'reference identity'):
            asyncio.run(review_records(self.inputs, self.root/'output',
                reviewer_factory=lambda path: self.fail('model must not be constructed')))
        self.assertFalse((self.root/'output').exists())


if __name__ == '__main__':
    unittest.main()
