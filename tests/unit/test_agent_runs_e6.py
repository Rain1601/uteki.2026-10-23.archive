"""Selection, immutable-byte and assessment binding checks without model calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from apps.review_workbench.data import agent_runs, agent_run_results, agent_runs_e6 as e6

ROOT = Path(__file__).resolve().parents[2]


def encode(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode()


class SealedFixture:
    def __init__(self, root):
        self.root = root
        self.entries = []

    def write(self, relative, value):
        p = self.root / relative; p.parent.mkdir(parents=True, exist_ok=True)
        raw = encode(value); p.write_bytes(raw)
        return {'path': relative, 'sha256': hashlib.sha256(raw).hexdigest()}

    def add(self, identity, *, company='cedar', failed=False):
        base = 'output/fixture/' + identity
        scope = {'execution_schema_version': 'research-execution-v1', 'snapshot_id': identity + '-snapshot',
                 'company_ids': [company], 'source_snapshot_ids': [company + '-source'],
                 'knowledge_cutoff': '2032-10-01', 'source_policy_id': 'local-frozen-v1', 'include_candidates': True}
        packet = {'schema_version': 'data-answer-review-input-v1', 'scope': scope, 'question': 'What is reported?',
                  'source_documents': [{'company_id': company, 'source_snapshot_id': company + '-source',
                                        'blocks': [{'block_id': 'b1', 'text': 'Income 12', 'type': 'table'}]}],
                  'facts': [{'fact_id': 'f1', 'kind': 'record', 'value': {'entity_id': company, 'source_snapshot_id': company + '-source',
                            'metric_id': 'income', 'value_decimal': '12', 'unit': 'EUR',
                            'period': {'start': '2031-01-01', 'end': '2031-12-31'}},
                            'citations': [{'block_id': 'b1', 'quote': '12', 'cell': {'row': 0, 'column': 1}}]}]}
        paths = {'input.json': self.write(base + '/input.json', packet)['sha256'],
                 'result.json': self.write(base + '/result.json', {'schema_version': 'data-answer-review-result-v1',
                    'scope': scope, 'status': 'failed' if failed else 'reviewed', 'assessment': None if failed else {'facts': [{'verdict': 'supported'}]}})['sha256']}
        manifest = self.write(base + '/manifest.json', {'files': paths})
        standard = self.write('experiments/fixture/standard.json', {'schema_version': 'fixture-standard-v1', 'mandatory': ['income']})
        assessment = self.write('experiments/fixture/' + identity + '.json', {'overall_verdict': 'fail' if failed else 'pass',
                'evidence_refs': {'run': base, 'run_manifest_sha256': manifest['sha256'], 'standard_sha256': standard['sha256']}})
        entry = {'id': identity, 'title': identity, 'adapter': e6.ADAPTER, 'kind': 'source_repair', 'path': base,
                 'manifest_sha256': manifest['sha256'], 'scope': scope,
                 'evaluation': {'standard': standard, 'independent_assessment': assessment}, 'limitations': ['Fixture only']}
        self.entries.append(entry); self.register()
        return entry

    def register(self):
        self.write(e6.REGISTRATION, {'schema_version': 'e6-runs-registration-v1', 'runs': self.entries})


class SealedEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.fixture = SealedFixture(self.root)
        self.a = self.fixture.add('cedar-a', failed=True)
        self.b = self.fixture.add('maple-b', company='maple')

    def test_actual_packet_candidates_remain_distinct_from_failed_acceptance(self):
        v = agent_run_results.load_result(self.root, 'cedar-a')
        self.assertEqual(v['state']['quality'], 'fail')
        self.assertEqual(v['state']['execution'], 'failed')
        fact = v['result_view']['facts'][0]
        self.assertEqual((fact['company'], fact['value'], fact['unit']), ('cedar', '12', 'EUR'))
        self.assertEqual(fact['period'], '2031-01-01 → 2031-12-31')
        self.assertEqual(v['result_view']['documents'][0]['text'], 'Income 12')
        self.assertIn('steps', v); self.assertIn('evaluation', v)
        self.assertIsNone(v['evaluation']['model_reviews'][0]['assessment'])

    def test_cross_run_refs_and_revision_are_rejected(self):
        a, b = e6.load_run(self.root, 'cedar-a'), e6.load_run(self.root, 'maple-b')
        with self.assertRaisesRegex(ValueError, 'Unknown artifact'):
            agent_runs.read_artifact(self.root, 'cedar-a', b['artifacts'][0]['id'])
        with self.assertRaisesRegex(ValueError, 'revision'):
            agent_runs.load_run(self.root, 'cedar-a', revision=b['revision'])
        page = agent_runs.read_artifact(self.root, 'cedar-a', a['inputs'][0]['id'])
        self.assertEqual(page['content']['scope']['company_ids'], ['cedar'])

    def test_tampering_after_cache_read_is_not_hidden(self):
        e6.load_run(self.root, 'cedar-a')
        p = self.root / self.a['path'] / 'input.json'
        value = json.loads(p.read_text()); value['facts'][0]['value']['value_decimal'] = '99'
        p.write_bytes(encode(value))
        with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
            e6.load_run(self.root, 'cedar-a')

    def test_forged_success_assessment_cannot_bind_failed_run(self):
        self.a['evaluation']['independent_assessment'] = self.b['evaluation']['independent_assessment']
        self.fixture.register()
        with self.assertRaisesRegex(ValueError, 'assessment run binding'):
            e6.load_run(self.root, 'cedar-a')

    def test_registration_scope_and_path_escape_are_rejected(self):
        self.a['scope']['company_ids'] = ['maple']; self.fixture.register()
        with self.assertRaisesRegex(ValueError, 'scope mismatch'):
            e6.load_run(self.root, 'cedar-a')
        self.a['path'] = '../outside'; self.fixture.register()
        with self.assertRaisesRegex(ValueError, 'outside registered root'):
            e6.load_run(self.root, 'cedar-a')

    def test_list_is_light_and_does_not_return_other_detail(self):
        rows = agent_run_results.list_results(self.root)['results']
        self.assertEqual(len(rows), 2)
        self.assertNotIn('steps', rows[0]); self.assertNotIn('facts', rows[0]['result_view'])
        self.assertEqual({r['scope']['company_ids'][0] for r in rows}, {'cedar', 'maple'})

    def test_unknown_identity_and_steps_are_rejected(self):
        with self.assertRaises(KeyError): agent_runs.load_run(self.root, 'unregistered')
        with self.assertRaisesRegex(ValueError, 'Unknown step'): e6.load_step(self.root, 'cedar-a', 'other-step')


class E6ActualHistoryTests(unittest.TestCase):
    def test_frozen_failure_recovery_and_cost_denominators(self):
        # Original private output histories may be absent on a clean checkout.
        if not (ROOT / 'output/e6-source-citation-20261010-r1/repair-01/manifest.json').exists():
            self.skipTest('Private E6 histories are absent')
        rows = e6.list_runs(ROOT)
        self.assertEqual(len(rows), 16)
        self.assertEqual(sum(r['usage']['requests'] for r in rows), 279)
        from decimal import Decimal
        self.assertEqual(sum((Decimal(r['usage']['known_estimated_usd']) for r in rows), Decimal(0)), Decimal('3.5565693'))
        failed = e6.load_run(ROOT, 'e6-v1-r3-s3')
        self.assertEqual(failed['state']['quality'], 'fail')
        self.assertEqual(len(failed['result_view']['facts']), 4)
        repair = e6.load_run(ROOT, 'e6-r1-repair-01')
        self.assertEqual(repair['usage']['unknown_cost_requests'], 2)
        self.assertEqual(repair['usage']['unknown_reserved_usd'], '0.1004304')
        self.assertEqual(repair['evaluation']['independent_assessment']['path'], 'output/e6-source-citation-20261010-r1/repair-01')
        recovered = e6.load_run(ROOT, 'e6-v1-r2-s1')
        history = recovered['evaluation']['independent_assessment']['attempt_history']
        self.assertTrue(history)
        phases = [(s['attempt'], s['phase']) for s in recovered['steps']]
        self.assertLess(phases.index(('attempt-01', 'review')), phases.index(('attempt-02', 'query')))
