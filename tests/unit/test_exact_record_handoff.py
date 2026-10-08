"""Precise numeric citations in versioned handoff; local originals, no model calls."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb

from uteki.agents.data_query.answer_handoff import _record_quote, prepare_review_packet
from uteki.agents.data_query.autonomous import AutonomousDataAgent
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort
from tests.unit import test_record_locator as locator_fixture
from tests.unit.test_autonomous_data_agent import ScriptedPlanner
from tests.unit.test_task_completion import pin_dataset


def pin_originals_for_synthetic_records(dataset):
    """Upgrade the legacy invented dataset with explicit invented raw bytes and identities."""
    sources = json.loads((dataset/'sources.json').read_text())
    with duckdb.connect(str(dataset/'research.duckdb')) as db:
        for source in sources:
            sid = source['source_snapshot_id']; folder = dataset/source['index_folder']
            blocks = list(map(json.loads, (folder/'blocks.jsonl').read_text().splitlines()))
            for block in blocks:
                block.update(text_hash=digest(block['text'].encode()), source_snapshot_id=sid)
            raw = '\n'.join(block['text'] for block in blocks).encode()
            source.update(source_sha256=digest(raw), raw_file=f'{sid}.txt', parsed_mime_type='text/plain')
            (dataset/source['raw_file']).write_bytes(raw)
            (folder/'blocks.jsonl').write_text(''.join(json.dumps(b)+'\n' for b in blocks))
            index = json.loads((folder/'index.json').read_text())
            index.update(source_snapshot_id=sid, source_sha256=source['source_sha256'])
            (folder/'index.json').write_text(json.dumps(index))
            manifest = json.loads((folder/'manifest.json').read_text())
            manifest.update(source_snapshot_id=sid, source_sha256=source['source_sha256'])
            for name in ('blocks.jsonl', 'index.json'):
                manifest['artifacts'][name]['sha256'] = digest((folder/name).read_bytes())
            (folder/'manifest.json').write_text(json.dumps(manifest))
            db.execute('UPDATE sources SET payload=? WHERE source_snapshot_id=?', [json.dumps(source), sid])
            for eid, payload in db.execute('SELECT evidence_id,payload FROM evidence WHERE source_snapshot_id=?', [sid]).fetchall():
                evidence = json.loads(payload)
                block = next(b for b in blocks if b['block_id'] == evidence['block_id'])
                evidence.update(source_sha256=source['source_sha256'], index_id=source['index_id'], text_hash=block['text_hash'])
                db.execute('UPDATE evidence SET payload=? WHERE evidence_id=?', [json.dumps(evidence), eid])
    (dataset/'sources.json').write_text(json.dumps(sources))
    pin_dataset(dataset)


class ExactRecordQuoteTests(unittest.TestCase):
    def setUp(self):
        self.fixture = locator_fixture.RecordLocatorTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        source = self.fixture.source
        self.packet = {'purpose':'analysis_evidence', 'delivery_schema_version':'selected-originals-v1',
            'source_documents':[{**source, 'blocks':[self.fixture.block]}]}

    def test_second_equal_fact_has_exact_coordinates_without_repeating_full_table(self):
        quote = _record_quote(self.packet, self.fixture.root, self.fixture.evidence)
        self.assertEqual(quote['cell'], {'row':3,'column':1})
        self.assertEqual(quote['quote'], '42')
        self.assertGreater(quote['char_start'], self.fixture.block['text'].find('42'))
        self.assertEqual(self.fixture.block['text'][quote['char_start']:quote['char_end']], '42')
        self.assertEqual(quote['text_hash'], self.fixture.block['text_hash'])
        self.assertNotIn('original_block', quote)
        self.assertNotIn('table', quote)
        self.assertNotIn('text', quote)

    def test_unknown_repeated_location_rejects_and_legacy_does_not_change(self):
        evidence = {k:v for k,v in self.fixture.evidence.items() if k!='fact_dom_path'}
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            _record_quote(self.packet, self.fixture.root, evidence)
        for key in ('purpose', 'delivery_schema_version'):
            packet = {k:v for k,v in self.packet.items() if k!=key}
            with patch('uteki.agents.data_query.answer_handoff.resolve_record_locator', side_effect=AssertionError('legacy must not resolve')):
                quote = _record_quote(packet, self.fixture.root, evidence)
            self.assertNotIn('char_start', quote)
            self.assertNotIn('cell', quote)


class RealRecordHandoffTests(unittest.TestCase):
    def test_frozen_msft_numeric_query_reaches_precise_handoff(self):
        dataset = Path(__file__).resolve().parents[2]/'experiments/agent_design/2026-10-09-data-agent-completion-v1/datasets/msft'
        if not (dataset/'records.json').exists(): self.skipTest('Explicit frozen MSFT fixture unavailable')
        manifest = json.loads((dataset/'manifest.json').read_text())
        source = json.loads((dataset/'sources.json').read_text())[0]
        records = json.loads((dataset/'records.json').read_text())
        record = records['rows'][0]
        scope = {'snapshot_id':manifest['snapshot_id'], 'company_ids':[source['company_id']],
            'source_snapshot_ids':[source['source_snapshot_id']], 'source_policy_id':manifest['source_policy_id'],
            'knowledge_cutoff':source['available_at'], 'include_candidates':True}
        query = {'records':[{k:record[k] for k in ('entity_id','metric_id','period','value_kind')}]}
        actions = [{'action':'plan','reason':'Retrieve explicit numeric record in this frozen fixture.',
            'requirements':[{'kind':'query','requirement_id':'number','description':f"Retrieve the reported numeric evidence for FY{record['period']['end'][:4]}.",'query':query}]},
            {'action':'query','requirement_ids':['number'],'plan':query},
            lambda packet: {'action':'select_records','requirement_ids':['number'],
                'record_selection':{'record_ids':packet['observation']['evidence_ids']},
                'reason':'Retain queried original records for exact citation checks.'}, {'action':'finish'}]
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'run'
            with QueryDataPort(dataset) as port:
                result = asyncio.run(AutonomousDataAgent(port, ScriptedPlanner(actions), purpose='analysis_evidence',
                    limits={'max_steps':4, 'max_packet_bytes':100000}).run(
                    {'question':f"Retrieve the reported metric for FY{record['period']['end'][:4]} with exact original support.", 'scope':scope},output=output))
            self.assertEqual(result['status'],'evidence_ready',(output/'turn-001/feedback.json').read_text())
            packet = prepare_review_packet(output,dataset,expected_scope=scope,max_packet_bytes=200000,source_delivery='query_evidence_v1')
            self.assertEqual(packet['program_gaps'],[])
            for fact in packet['facts']:
                for citation in fact['citations']:
                    block = next(b for d in packet['source_documents'] for b in d['blocks'] if b['block_id']==citation['block_id'])
                    self.assertEqual(block['text'][citation['char_start']:citation['char_end']],citation['quote'])
                    self.assertIn('cell',citation)
                    self.assertNotIn('original_block',citation)
