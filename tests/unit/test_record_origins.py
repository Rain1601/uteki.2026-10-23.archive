"""Origin-aware occurrence selection; offline actual agent protocol and scoped data."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest

import duckdb

from uteki.agents.data_query.autonomous import AutonomousDataAgent, runtime_prompt
from uteki.infrastructure.research_data.query_service import QueryDataPort
from uteki.infrastructure.research_data.financial_records import digest
from tests.unit import test_analysis_record_selection as fixtures
from tests.unit.test_autonomous_data_agent import ScriptedPlanner
from tests.unit.test_autonomous_source_evidence import context_read
from tests.unit.test_task_completion import pin_dataset


class RecordOriginsTests(unittest.TestCase):
    setUp = fixtures.AnalysisRecordSelectionTests.setUp

    def run_actions(self, actions, *, page_items=1):
        planner = ScriptedPlanner(actions)
        with QueryDataPort(self.dataset) as port:
            result = asyncio.run(AutonomousDataAgent(port, planner, purpose='analysis_evidence',
                limits={'max_steps':len(actions),'max_packet_bytes':128000,
                        'observation_bytes':32000,'page_items':page_items}).run(
                            self.request, output=self.root/'run'))
        return result, planner

    def change_duplicate_origin(self, *, long_quote=False):
        rid = 'acme-annual-revenue-2031-second-disclosure'
        quote = ('Description ' * 30 + '100') if long_quote else '100'
        db = duckdb.connect(str(self.dataset/'research.duckdb'))
        row = json.loads(db.execute('SELECT payload FROM evidence WHERE evidence_id=?', [rid]).fetchone()[0])
        row.update(block_id='b8', quote=quote, cell={'row':0,'column':1})
        db.execute('UPDATE evidence SET payload=? WHERE evidence_id=?', [json.dumps(row),rid]);db.close()
        folder=self.dataset/'indexes/acme-annual';path=folder/'blocks.jsonl'
        blocks=[json.loads(line) for line in path.read_text().splitlines()]
        blocks[8]['text']='Sales '+quote
        blocks[8]['table']['cells']=[{'row':0,'column':0,'text':'Sales','rowspan':1,'colspan':1},
                                   {'row':0,'column':1,'text':quote,'rowspan':1,'colspan':1}]
        path.write_text(''.join(json.dumps(b)+'\n' for b in blocks))
        manifest=json.loads((folder/'manifest.json').read_text())
        manifest['artifacts']['blocks.jsonl']['sha256']=digest(path.read_bytes())
        (folder/'manifest.json').write_text(json.dumps(manifest))
        pin_dataset(self.dataset)

    def test_default_origin_page_links_all_occurrences_and_persists_after_body_read(self):
        self.change_duplicate_origin()
        state={}
        def read(packet):
            origins=packet['record_origins'];state['origins']=origins
            self.assertTrue(origins['navigation_only'])
            self.assertEqual(origins['returned_count'],2)
            self.assertIsNone(origins['next_cursor'])
            self.assertEqual({c['block_id'] for r in origins['items'] for c in r['citations']},{'b8','b9'})
            self.assertEqual(len(packet['evidence_index']),1)
            self.assertEqual(packet['retained_body']['items'],[])
            return context_read(block='b8',requirement='revenue')
        def select(packet):
            self.assertEqual(packet['record_origins'],state['origins'])
            selected=next(r for r in packet['record_origins']['items'] if r['citations'][0]['block_id']=='b8')
            self.assertEqual(selected['citations'][0]['cell'],{'row':0,'column':1})
            self.assertEqual(selected['citations'][0]['source_snapshot_id'],'acme-annual')
            return {'action':'select_records','requirement_ids':['revenue'],
                'record_selection':{'record_ids':[selected['evidence_id']]},'reason':'Use the checked original occurrence.'}
        result,_=self.run_actions([fixtures.plan([fixtures.criterion()]),fixtures.query([fixtures.criterion()]),
                                  read,select,{'action':'finish'}])
        self.assertEqual(result['status'],'evidence_ready',result['trace'])
        selected=result['coverage'][0]['selected_record_ids']
        self.assertEqual(selected,[next(r['evidence_id'] for r in state['origins']['items']
                                       if r['citations'][0]['block_id']=='b8')])

    def test_long_quote_has_bounded_preview_and_readable_full_original_citation(self):
        self.change_duplicate_origin(long_quote=True)
        result,planner=self.run_actions([fixtures.plan([fixtures.criterion()]),
                                        fixtures.query([fixtures.criterion()]),{'action':'finish'}])
        origins=planner.packets[-1]['record_origins']
        cite=next(c for r in origins['items'] for c in r['citations'] if c['block_id']=='b8')
        self.assertTrue(cite['quote_truncated']);self.assertEqual(len(cite['quote_preview']),160)
        artifact_id=cite['read_request']['artifact_id']
        artifact=json.loads((self.root/'run/artifacts'/f'{artifact_id}.json').read_text())
        self.assertGreater(len(artifact['quote']),160)
        self.assertEqual(artifact['quote'][:160],cite['quote_preview'])
        self.assertNotEqual(result['status'],'evidence_ready')  # Mapping is not a final selection.

    def test_prompt_explains_immutable_origin_and_cross_check_distinction(self):
        prompt=runtime_prompt('planner','analysis_evidence')
        self.assertIn('record_origins',prompt)
        self.assertIn('does not change the record',prompt)
        self.assertIn('Selecting source_evidence does not replace',prompt)


class FrozenRecordOriginTests(unittest.TestCase):
    def test_google_ten_occurrences_have_visible_correct_origins_without_index_pagination(self):
        base=Path(__file__).resolve().parents[2]/'experiments/agent_design/2026-10-09-data-agent-completion-v1'
        config=base/'configs/googl-revenue.json'
        if not config.exists():self.skipTest('Explicit frozen fixture unavailable')
        request=json.loads(config.read_text())['request'];dataset=base/'datasets/googl'
        sources=json.loads((dataset/'sources.json').read_text())
        periods={x['fiscal_year']:x['period'] for s in sources for x in s['fiscal_periods']}
        records=[{'entity_id':request['scope']['company_ids'][0],'metric_id':'revenue','period':periods[y]}
                 for y in (2024,2025)]
        original_citations=json.loads((dataset/'evidence.json').read_text())
        def select(packet):
            origins=packet['record_origins']
            self.assertEqual(origins['returned_count'],10)
            self.assertIsNone(origins['next_cursor'])
            self.assertEqual(len(packet['evidence_index']),1)
            for row in origins['items']:
                for citation in row['citations']:
                    original=original_citations[citation['citation_id']]
                    for key in ('source_snapshot_id','block_id','cell','fact_dom_path'):
                        self.assertEqual(citation.get(key),original.get(key))
            chosen=[]
            for period in periods[2024],periods[2025]:
                row=next(r for r in origins['items'] if r['period']['end']==period['end'])
                chosen.append(row['evidence_id'])
            return {'action':'select_records','requirement_ids':['revenue'],
                'record_selection':{'record_ids':chosen},'reason':'Offline source-map protocol check.'}
        before=digest((dataset/'manifest.json').read_bytes())
        with tempfile.TemporaryDirectory() as folder,QueryDataPort(dataset) as port:
            result=asyncio.run(AutonomousDataAgent(port,
                ScriptedPlanner([fixtures.plan(records),fixtures.query(records),select,{'action':'finish'}]),
                purpose='analysis_evidence',limits={'max_steps':4,'max_packet_bytes':120000,
                'observation_bytes':24000,'page_items':1}).run(
                    {'question':request['question'],'scope':request['scope']},output=Path(folder)/'run'))
        self.assertEqual(result['status'],'evidence_ready',result['trace'])
        self.assertEqual(before,digest((dataset/'manifest.json').read_bytes()))


if __name__=='__main__':unittest.main()
