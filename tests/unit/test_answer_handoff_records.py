"""Frozen numeric query replay checks with synthetic records; no model calls."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from uteki.agents.data_query.answer_handoff import prepare_review_packet
from uteki.agents.data_query.autonomous import AutonomousDataAgent
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.infrastructure.research_data.run_artifacts import load_evidence_bundle
from tests.unit.test_autonomous_data_agent import ScriptedPlanner
from tests.unit.test_scoped_query_service import make_scoped_dataset, year
from tests.unit.test_task_completion import attach_synthetic_quotes, pin_dataset


class AnswerHandoffRecordTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dataset = self.root / 'dataset'
        self.dataset.mkdir()
        make_scoped_dataset(self.dataset)
        attach_synthetic_quotes(self.dataset)
        self.dataset_manifest_hash = digest((self.dataset / 'manifest.json').read_bytes())
        self.scope = ExecutionScope(snapshot_id='synthetic-scoped-v1', company_ids=('acme',),
            source_snapshot_ids=('acme-annual',), source_policy_id='local-frozen-v1',
            knowledge_cutoff='2032-05-01', include_candidates=True)

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False))

    def query(self, *, name='query', period_year=2031, company='acme', metrics=('revenue',)):
        scope = self.scope.model_copy(update={
            'company_ids': (company,), 'source_snapshot_ids': (company + '-annual',)})
        question = f'Retrieve reported {", ".join(metrics)} for {company} services in calendar year {period_year}.'
        plan = {'records': [{'entity_id': company + '-services', 'metric_id': metric,
                             'period': year(period_year), 'value_kind': 'actual'} for metric in metrics]}
        actions = [
            {'action': 'plan', 'reason': 'Explicit numeric fixture request.', 'requirements': [{
                'kind': 'query', 'requirement_id': 'reported-metrics', 'description': question, 'query': plan}]},
            {'action': 'query', 'requirement_ids': ['reported-metrics'], 'plan': plan},
            {'action': 'finish'},
        ]
        output = self.root / name
        with QueryDataPort(self.dataset) as port:
            result = asyncio.run(AutonomousDataAgent(port, ScriptedPlanner(actions),
                limits={'max_steps': len(actions), 'max_packet_bytes': 64000}).run(
                    {'question': question, 'scope': scope.model_dump(mode='json')}, output=output))
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertEqual(result['coverage'][0]['program_check'], 'satisfied')
        self.assertEqual(result['semantic_completeness'], 'not_evaluated')
        _verify_manifest(output)
        return output, scope

    def prepare(self, output, *, scope=None, dataset=None):
        return prepare_review_packet(output, self.dataset if dataset is None else dataset,
            expected_scope=self.scope if scope is None else scope, max_packet_bytes=1_000_000)

    def reseal_record_change(self, output, changes):
        """Rehash the modified query artifacts, preserving the frozen dataset.

        This deliberately removes ordinary file-integrity failures, so rejection
        must come from comparing the active record with its scoped query replay.
        """
        bundle_path = output / 'evidence-bundle.json'
        bundle = json.loads(bundle_path.read_text())
        item = next(item for item in bundle['items'] if item['kind'] == 'record')
        artifact = item['artifact']
        record_path = output / artifact['path']
        record = json.loads(record_path.read_text())
        record.update(deepcopy(changes))
        self.write(record_path, record)
        artifact.update(sha256=digest(record_path.read_bytes()), size_bytes=record_path.stat().st_size)
        item['sha256'] = digest({'kind': item['kind'], 'value': record, 'scope': item['scope']})
        index_path = output / 'artifact-index.json'
        index = json.loads(index_path.read_text())
        for reference in index:
            if reference['artifact_id'] == artifact['artifact_id']:
                reference.update(artifact)
        self.write(index_path, index)
        bundle['bundle_id'] = 'bundle-' + digest({k: v for k, v in bundle.items() if k != 'bundle_id'})[:24]
        self.write(bundle_path, bundle)
        result_path = output / 'result.json'
        result = json.loads(result_path.read_text())
        result['evidence_bundle']['bundle_id'] = bundle['bundle_id']
        self.write(result_path, result)
        pin_dataset(output)
        _verify_manifest(output)
        restored = load_evidence_bundle(output)
        changed = next(row for row in restored['items'] if row['evidence_id'] == item['evidence_id'])
        self.assertEqual(changed['value'], record)
        self.assertIn(item['evidence_id'], result['coverage'][0]['evidence_ids'])
        self.assertEqual(digest((self.dataset / 'manifest.json').read_bytes()), self.dataset_manifest_hash)

    def test_real_scripted_numeric_query_prepares_original_records_and_citations(self):
        output, _ = self.query(metrics=('revenue', 'operating_income'))
        packet = self.prepare(output)
        self.assertEqual(packet['query_plan_origin'], 'scripted_fixture')
        self.assertEqual(packet['query_status'], 'evidence_ready')
        self.assertEqual(packet['program_gaps'], [])
        self.assertEqual(packet['query_gaps'], [])
        self.assertEqual({fact['kind'] for fact in packet['facts']}, {'record'})
        self.assertEqual({fact['value']['metric_id']: fact['value']['value_decimal']
                          for fact in packet['facts']}, {'revenue': '100', 'operating_income': '15'})
        for fact in packet['facts']:
            self.assertEqual(fact['requirement_ids'], ['reported-metrics'])
            self.assertEqual(fact['value']['entity_id'], 'acme-services')
            self.assertTrue(fact['citations'])
            for citation in fact['citations']:
                self.assertEqual(citation['source_snapshot_id'], 'acme-annual')
                self.assertIn(citation['quote'], citation['original_block']['text'])
        self.assertEqual(packet['dataset_ref']['manifest_sha256'], self.dataset_manifest_hash)

    def test_resealed_active_record_entity_period_value_and_availability_fail_dataset_replay(self):
        cases = {
            'entity': {'entity_id': 'other-services'},
            'period': {'period': year(2030)},
            'value': {'value_decimal': '101'},
            'availability': {'available_at': '2033-02-01'},
            'source': {'source_snapshot_id': 'other-annual'},
        }
        for name, changes in cases.items():
            with self.subTest(field=name):
                output, _ = self.query(name='changed-' + name)
                self.reseal_record_change(output, changes)
                with self.assertRaisesRegex(ValueError, 'record differs from scoped dataset and declared query requirement'):
                    self.prepare(output)

    def test_resealed_query_plan_cannot_relabel_a_record_as_another_period(self):
        output, _ = self.query()
        path = output / 'result.json'
        result = json.loads(path.read_text())
        result['coverage'][0]['query']['records'][0]['period'] = year(2030)
        self.write(path, result)
        pin_dataset(output)
        _verify_manifest(output)
        with self.assertRaisesRegex(ValueError, 'record differs from scoped dataset and declared query requirement'):
            self.prepare(output)

    def test_other_company_source_snapshot_cutoff_and_candidate_access_cannot_replace_query_scope(self):
        output, _ = self.query()
        for change in (
            {'company_ids': ['other'], 'source_snapshot_ids': ['other-annual']},
            {'source_snapshot_ids': ['acme-amended']},
            {'snapshot_id': 'different-snapshot'},
            {'knowledge_cutoff': '2032-04-30'},
            {'include_candidates': False},
        ):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'query scope/version mismatch'):
                self.prepare(output, scope={**self.scope.model_dump(mode='json'), **change})

    def test_replacement_dataset_snapshot_does_not_match_original_query(self):
        output, _ = self.query()
        replacement = self.root / 'replacement-dataset'
        replacement.mkdir()
        make_scoped_dataset(replacement)
        attach_synthetic_quotes(replacement)
        path = replacement / 'manifest.json'
        manifest = json.loads(path.read_text())
        manifest['snapshot_id'] = 'another-explicit-snapshot'
        self.write(path, manifest)
        pin_dataset(replacement)
        with self.assertRaisesRegex(ValueError, 'snapshot mismatch'):
            self.prepare(output, dataset=replacement)

    def test_another_explicit_period_uses_its_own_record_and_original_quote(self):
        for period_year, expected_value in ((2030, '90'), (2031, '100')):
            with self.subTest(period_year=period_year):
                output, _ = self.query(name=f'year-{period_year}', period_year=period_year)
                packet = self.prepare(output)
                self.assertEqual(packet['program_gaps'], [])
                fact, = packet['facts']
                self.assertEqual(fact['value']['period'], year(period_year))
                self.assertEqual(fact['value']['value_decimal'], expected_value)
                self.assertIn(f'{period_year}-12-31: {expected_value} USD.', fact['citations'][0]['quote'])

    def test_another_explicit_company_uses_same_handoff_contract_without_acme_fallback(self):
        output, scope = self.query(company='other')
        packet = self.prepare(output, scope=scope)
        self.assertEqual(packet['program_gaps'], [])
        self.assertEqual(packet['scope']['company_ids'], ['other'])
        fact, = packet['facts']
        self.assertEqual(fact['value']['entity_id'], 'other-services')
        self.assertEqual(fact['value']['value_decimal'], '800')
        self.assertEqual({c['source_snapshot_id'] for c in fact['citations']}, {'other-annual'})
        self.assertEqual({source['company_id'] for source in packet['source_documents']}, {'other'})


if __name__ == '__main__':
    unittest.main()
