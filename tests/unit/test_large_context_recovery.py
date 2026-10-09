"""Synthetic lossless source recovery and actual role body-delivery checks; no API."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from uteki.agents.data_query.autonomous import AutonomousDataAgent
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_dataset import save
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.infrastructure.research_data.run_artifacts import load_evidence_bundle
from tests.unit.test_scoped_query_service import make_scoped_dataset
from tests.unit.test_autonomous_data_agent import ScriptedPlanner


def large_dataset(root, *, count=1000, body_length=13000):
    root.mkdir(parents=True, exist_ok=True)
    make_scoped_dataset(root)
    folder = root / 'indexes/acme-annual'
    blocks = [json.loads(line) for line in (folder / 'blocks.jsonl').read_text().splitlines()]
    cells = [{'text': str(i) if i % 3 else '', 'row': i // 10, 'column': i % 10,
              'rowspan': 1, 'colspan': 1, 'is_header': i < 10} for i in range(count)]
    blocks[8]['table'] = {'row_count': count // 10, 'column_count': 10, 'cells': cells}
    blocks[8]['text'] = ('Original source table body. ' * (body_length // 28 + 1))[:body_length]
    (folder / 'blocks.jsonl').write_text(''.join(json.dumps(b) + '\n' for b in blocks))
    save(folder / 'manifest.json', {'status': 'candidate', 'artifacts': {
        name: {'sha256': digest((folder / name).read_bytes())} for name in ('index.json', 'blocks.jsonl')}})
    manifest = json.loads((root / 'manifest.json').read_text())
    manifest['files'] = {name: digest((root / name).read_bytes()) for name in manifest['files']}
    save(root / 'manifest.json', manifest)
    return blocks, cells


PLAN = {'action': 'plan', 'reason': 'Independent synthetic complete source table requirement',
        'requirements': [{'kind': 'source_evidence', 'requirement_id': 'source-table',
                          'source_id': 'acme-annual', 'description': 'Deliver complete original table body.'}]}
READ = {'action': 'read_context', 'requirement_ids': ['source-table'],
        'context': {'source_snapshot_id': 'acme-annual', 'block_id': 'b8'}}
COMPACT = {**READ, 'context': {**READ['context'], 'representation': 'compact'}}


class LargeContextRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.dataset = self.root / 'dataset'
        self.original_blocks, self.cells = large_dataset(self.dataset)
        self.owner = QueryDataPort(self.dataset); self.addCleanup(self.owner.close)
        self.scope = {'snapshot_id': self.owner.snapshot_id, 'company_ids': ['acme'],
            'source_snapshot_ids': ['acme-annual'], 'source_policy_id': 'local-frozen-v1',
            'knowledge_cutoff': '2032-06-01', 'include_candidates': True}
        self.request = {'question': 'Deliver the original source table for acme.', 'scope': self.scope}

    def run_planner(self, planner, steps):
        return asyncio.run(AutonomousDataAgent(self.owner, planner, purpose='analysis_evidence',
            limits={'max_steps': steps, 'observation_bytes': 4000}).run(self.request, output=self.root / 'run'))

    def test_failed_atomic_read_supplies_no_evidence_and_cannot_finish(self):
        planner = ScriptedPlanner([PLAN, READ, {'action': 'finish'}])
        result = self.run_planner(planner, 3)
        refusal = json.loads((self.root / 'run/turn-002/feedback.json').read_text())
        self.assertEqual(refusal['evidence_ids'], [])
        self.assertEqual(refusal['result']['status'], 'context_too_large')
        self.assertEqual(refusal['result']['blocks'], [])
        self.assertEqual(load_evidence_bundle(self.root / 'run')['items'], [])
        self.assertNotEqual(result['status'], 'evidence_ready')
        self.assertTrue(result['gaps'])

    def test_compact_artifact_storage_without_body_delivery_cannot_finish(self):
        planner = ScriptedPlanner([PLAN, COMPACT, {'action': 'finish'}])
        result = self.run_planner(planner, 3)
        self.assertTrue(planner.packets[2]['pending_body_reads'])
        self.assertNotEqual(result['status'], 'evidence_ready')
        bundle = load_evidence_bundle(self.root / 'run')
        context = next(x for x in bundle['items'] if x['kind'] == 'context')
        self.assertNotIn('b8', bundle.get('delivered_body', {}).get(context['evidence_id'], []))

    def test_explicit_compact_retry_and_artifact_pages_deliver_exact_full_body(self):
        test = self
        class Planner:
            plan_origin = 'scripted_fixture'
            def __init__(self):
                self.packets = []; self.phase = 0; self.context_id = None; self.pages = 0
            async def decide(self, packet):
                self.packets.append(deepcopy(packet))
                self.phase += 1
                if self.phase == 1: return PLAN
                if self.phase == 2: return READ
                if self.phase == 3:
                    result = packet['observation']['result']
                    test.assertEqual(result['status'], 'context_too_large')
                    test.assertEqual(packet['observation']['evidence_ids'], [])
                    test.assertLessEqual(result['representation_bytes']['compact'], result['max_bytes'])
                    return COMPACT
                if self.phase == 4:
                    self.context_id = packet['observation']['evidence_ids'][0]
                    test.assertTrue(packet['pending_body_reads'])
                if packet['pending_body_reads']:
                    self.pages += 1
                    return {'action': 'read_artifact', 'requirement_ids': ['source-table'],
                            'artifact_read': packet['pending_body_reads'][0]['read_request']}
                if self.phase > 4 and packet['observation'].get('result', {}).get('pointer', '').endswith('/text'):
                    self.delivered_complete = True
                if packet['completion']['unmet']:
                    return {'action': 'select_evidence', 'reason': 'Complete original table body now delivered.',
                            'requirement_ids': ['source-table'],
                            'delivery': {'blocks': [{'context_id': self.context_id, 'block_id': 'b8'}]}}
                return {'action': 'finish'}
        planner = Planner()
        result = self.run_planner(planner, 30)
        self.assertEqual(result['status'], 'evidence_ready', result['trace'])
        self.assertGreater(planner.pages, 1)
        self.assertEqual(result['pending_body_reads'], [])
        self.assertFalse(any(g.get('reason') == 'tool_gap' for g in result['gaps']))
        bundle = load_evidence_bundle(self.root / 'run')
        context = next(x for x in bundle['items'] if x['kind'] == 'context')
        table_block = next(x for x in context['value']['blocks'] if x['block_id'] == 'b8')
        self.assertEqual(table_block['text'], self.original_blocks[8]['text'])
        table = table_block['table']
        self.assertEqual([dict(zip(table['cell_fields'], c, strict=True)) for c in table['cells']], self.cells)
        self.assertIn('b8', bundle['delivered_body'][context['evidence_id']])
        # Refusal survives in immutable tool output even after task recovery.
        failed = json.loads((self.root / 'run/turn-002/feedback.json').read_text())
        full = json.loads((self.root / 'run' / failed['full_output']['path']).read_text())
        self.assertEqual(full['result']['status'], 'context_too_large')
        self.assertEqual(full['result']['blocks'], [])

    def test_neither_encoding_fits_reports_capacity_without_truncation(self):
        # A deliberately larger independent source remains unsupported at 80k.
        too_large = self.root / 'too-large'
        large_dataset(too_large, count=5000, body_length=500)
        with QueryDataPort(too_large) as owner:
            port = owner.scoped(self.scope)
            for representation in ('full', 'compact'):
                result = port.read_context(source_snapshot_id='acme-annual', block_id='b8',
                                           representation=representation)
                self.assertEqual(result['status'], 'context_too_large')
                self.assertGreater(result['representation_bytes']['compact'], result['max_bytes'])
                self.assertIsNone(result['retry_request'])
                self.assertEqual(result['blocks'], [])
                self.assertIsNone(result['next_cursor'])
                self.assertFalse(result['node_complete'])
