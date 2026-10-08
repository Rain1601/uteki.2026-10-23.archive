"""Large-table Data delivery -> bounded review regression, using offline source fixtures."""
import asyncio
from copy import deepcopy
import json
import unittest

from uteki.agents.data_query.answer_handoff import prepare_review_packet
from uteki.agents.data_query.autonomous import AutonomousDataAgent
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort, MAX_DOCUMENT_BYTES
from tests.unit import test_answer_handoff as handoff_fixtures
from tests.unit.test_autonomous_data_agent import ScriptedPlanner
from tests.unit.test_autonomous_source_evidence import source_plan
from tests.unit.test_task_completion import pin_dataset


class CompactAnswerHandoffTests(unittest.TestCase):
    def setUp(self):
        handoff_fixtures.AnswerHandoffTests.setUp(self)
        folder = self.dataset / 'indexes/acme-annual'
        path = folder / 'blocks.jsonl'
        blocks = [json.loads(line) for line in path.read_text().splitlines()]
        # Many complete cells make dictionary representation exceed the reader's
        # actual boundary, while identical tuple representation remains small.
        self.original_cells = [{'row': row, 'column': column, 'text': str(row * 4 + column),
                                'rowspan': 1, 'colspan': 1}
                               for row in range(300) for column in range(4)]
        blocks[8]['table'] = {'cells': deepcopy(self.original_cells)}
        path.write_text(''.join(json.dumps(block) + '\n' for block in blocks))
        manifest_path = folder / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['artifacts']['blocks.jsonl']['sha256'] = digest(path.read_bytes())
        manifest_path.write_text(json.dumps(manifest))
        pin_dataset(self.dataset)

    def query(self, *, representation='compact', oversized=True):
        output = self.root / 'compact-query'
        action = {'action': 'read_source', 'requirement_ids': ['business'], 'read': {
            'source_snapshot_id': 'acme-annual', 'node_id': 'notes',
            'start_block_id': 'b8', 'count': 1, 'representation': representation}}
        actions = [source_plan(), action, {'action': 'finish'}]
        with QueryDataPort(self.dataset) as owner:
            scoped = owner.scoped(self.scope)
            full = scoped.read_context(source_snapshot_id='acme-annual', block_id='b8')
            compact = scoped.read_context(source_snapshot_id='acme-annual', block_id='b8', representation='compact')
            self.assertEqual(full['status'], 'context_too_large' if oversized else 'read')
            if oversized:
                self.assertEqual(full['blocks'], [])
            self.assertEqual(compact['status'], 'read')
            self.assertLess(len(json.dumps(compact, ensure_ascii=False).encode()), MAX_DOCUMENT_BYTES)
            result = asyncio.run(AutonomousDataAgent(owner, ScriptedPlanner(actions),
                limits={'max_steps': 3, 'max_packet_bytes': 500_000, 'observation_bytes': 100_000}).run(
                    {'question': 'Return the original numeric table with its units and qualifier.',
                     'scope': self.scope.model_dump(mode='json')}, output=output))
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        return output

    def prepare(self, output):
        return prepare_review_packet(output, self.dataset, expected_scope=self.scope,
            max_packet_bytes=500_000, source_delivery='query_evidence_v1')

    def reseal_context(self, output, change):
        """Bypass incidental file-integrity checks to exercise canonical source validation."""
        bundle_path = output / 'evidence-bundle.json'
        bundle = json.loads(bundle_path.read_text())
        item = next(item for item in bundle['items'] if item['kind'] == 'context')
        path = output / item['artifact']['path']
        context = json.loads(path.read_text())
        change(context)
        path.write_text(json.dumps(context))
        item['artifact'].update(sha256=digest(path.read_bytes()), size_bytes=path.stat().st_size)
        item['sha256'] = digest({'kind': item['kind'], 'value': context, 'scope': item['scope']})
        index_path = output / 'artifact-index.json'
        index = json.loads(index_path.read_text())
        for ref in index:
            if ref['artifact_id'] == item['artifact']['artifact_id']:
                ref.update(item['artifact'])
        index_path.write_text(json.dumps(index))
        bundle['bundle_id'] = 'bundle-' + digest({k: v for k, v in bundle.items() if k != 'bundle_id'})[:24]
        bundle_path.write_text(json.dumps(bundle))
        result_path = output / 'result.json'
        result = json.loads(result_path.read_text())
        result['evidence_bundle']['bundle_id'] = bundle['bundle_id']
        result_path.write_text(json.dumps(result))
        pin_dataset(output)

    def test_over_cap_full_table_compact_delivery_reaches_review_without_cell_loss(self):
        packet = self.prepare(self.query())
        self.assertEqual(packet['program_gaps'], [])
        document, = packet['source_documents']
        self.assertEqual(document['representation'], 'compact')
        self.assertEqual({b['block_id'] for b in document['blocks']}, {'b7', 'b8', 'b9'})
        table = next(b['table'] for b in document['blocks'] if b['block_id'] == 'b8')
        decoded = [dict(zip(table['cell_fields'], cell)) for cell in table['cells']]
        self.assertEqual(decoded, self.original_cells)
        self.assertIn('Numbers in millions', document['blocks'][0]['text'])
        self.assertIn('exclude discontinued', document['blocks'][-1]['text'])

    def test_full_cell_dictionary_context_is_compared_in_compact_canonical_form(self):
        folder = self.dataset / 'indexes/acme-annual'
        path = folder / 'blocks.jsonl'
        blocks = [json.loads(line) for line in path.read_text().splitlines()]
        blocks[8]['table']['cells'] = blocks[8]['table']['cells'][:16]
        path.write_text(''.join(json.dumps(block) + '\n' for block in blocks))
        manifest_path = folder / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['artifacts']['blocks.jsonl']['sha256'] = digest(path.read_bytes())
        manifest_path.write_text(json.dumps(manifest))
        pin_dataset(self.dataset)
        packet = self.prepare(self.query(representation='full', oversized=False))
        self.assertEqual(packet['program_gaps'], [])
        table = next(b['table'] for b in packet['source_documents'][0]['blocks'] if b['block_id'] == 'b8')
        self.assertEqual([dict(zip(table['cell_fields'], cell)) for cell in table['cells']], self.original_cells[:16])

    def test_resealed_compact_cell_tamper_is_rejected_even_when_block_text_unchanged(self):
        output = self.query()
        def tamper(context):
            table = next(b['table'] for b in context['blocks'] if b['block_id'] == 'b8')
            table['cells'][1][table['cell_fields'].index('text')] = 'forged-cell-value'
        self.reseal_context(output, tamper)
        with self.assertRaisesRegex(ValueError, 'differs from original source block'):
            self.prepare(output)

    def test_unknown_or_other_company_context_source_cannot_use_compact_to_bypass_scope(self):
        output = self.query()
        for source in ('unknown-source', 'other-annual'):
            with self.subTest(source=source):
                self.reseal_context(output, lambda context: context.update(source_snapshot_id=source))
                with self.assertRaisesRegex(ValueError, 'outside execution scope'):
                    self.prepare(output)


if __name__ == '__main__':
    unittest.main()
