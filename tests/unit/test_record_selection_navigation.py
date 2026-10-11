"""Selection-state visibility and metadata isolation; no external models."""
from copy import deepcopy
import json
import tempfile
from pathlib import Path
import unittest

from uteki.agents.data_query.record_selection_navigation import candidate_index, selection_effect, navigation_page
from uteki.infrastructure.research_data.run_artifacts import ArtifactStore, json_size
from tests.unit import test_record_origins as origin_fixtures
from tests.unit import test_analysis_record_selection as fixtures


class SelectionNavigationTests(unittest.TestCase):
    def setUp(self):
        self.scope = {'snapshot_id': 'synthetic-scoped-v1', 'company_ids': ['acme'],
            'source_snapshot_ids': ['acme-annual'], 'source_policy_id': 'local-frozen-v1',
            'knowledge_cutoff': '2032-05-01', 'include_candidates': True}
        self.evidence, self.origins = {}, {}
        for eid, year, block, unit, basis, dimensions in (
            ('ev-prior-shared', 2030, 'statement', 'USD', 'gaap', {}),
            ('ev-current-shared', 2031, 'statement', 'USD', 'gaap', {}),
            ('ev-prior-region', 2030, 'geographic', 'USD', 'gaap', {}),
            ('ev-unit', 2030, 'other', 'EUR', 'gaap', {}),
            ('ev-basis', 2030, 'other', 'USD', 'adjusted', {}),
            ('ev-dimension', 2030, 'other', 'USD', 'gaap', {'region': 'East'})):
            record = {'record_id': eid+'-original', **fixtures.criterion(year), 'record_type': 'metric',
                'value_kind': 'actual', 'value_decimal': '100', 'unit': unit, 'accounting_basis': basis,
                'dimensions': dimensions, 'source_snapshot_id': 'acme-annual'}
            self.evidence[eid] = {'kind': 'record', 'scope': self.scope, 'value': record}
            self.origins[eid] = {'citations': [{'citation_id':eid+'-cite', 'role':'evidence_ids',
                'source_snapshot_id':'acme-annual', 'block_id':block, 'quote_preview':'100'}]}
        self.coverage = {'numeric': {'kind':'query','evidence_ids': list(self.evidence),
            'query_scope':self.scope, 'source_id':'acme-annual',
            'query':{'records':[fixtures.criterion(2030),fixtures.criterion(2031)]}}}

    def test_candidates_keep_criteria_and_distinct_semantics_without_recommending(self):
        original = deepcopy((self.coverage,self.evidence,self.origins))
        value = candidate_index(self.coverage,self.evidence,self.origins,self.scope)
        self.assertEqual([r['candidate_count'] for r in value['criteria']], [5,1])
        self.assertEqual(len(value['candidates']),6)
        self.assertEqual({r['unit'] for r in value['record_semantics']},{'USD','EUR'})
        self.assertEqual({r['accounting_basis'] for r in value['record_semantics']},{'gaap','adjusted'})
        self.assertIn({'region':'East'},[r['dimensions'] for r in value['record_semantics']])
        self.assertNotIn('preferred',json.dumps(value));self.assertNotIn('equivalent',json.dumps(value))
        self.assertEqual((self.coverage,self.evidence,self.origins),original)
        self.assertEqual(value['criteria'][0]['candidate_evidence_ids'], list(self.evidence)[::1][:1]+list(self.evidence)[2:])

    def test_both_selections_visible_then_replacement_removes_only_record_obligation(self):
        self.evidence['ctx'] = {'kind':'context','scope':self.scope,
            'value':{'source_snapshot_id':'acme-annual'}}
        documents = {'body':[{'context_id':'ctx','block_id':'statement'}]}
        chosen = {'numeric':['ev-prior-region','ev-current-shared']}
        value = selection_effect(self.coverage,self.evidence,self.origins,chosen,documents)
        self.assertEqual({r['block_id'] for r in value['record_citation_anchors']},{'geographic','statement'})
        self.assertEqual({r['block_id']:r['introduced_by'] for r in value['combined_anchor_blocks']},
            {'geographic':['record_citation'],'statement':['record_citation','explicit_source_selection']})
        # Explicit source selection cannot move the geographic record to statement.
        self.assertEqual(value['numeric_selections'][0]['selected_records'][0]['citations'][0]['block_id'],'geographic')
        chosen['numeric']=['ev-prior-shared','ev-current-shared']
        replaced=selection_effect(self.coverage,self.evidence,self.origins,chosen,documents)
        self.assertEqual([r['block_id'] for r in replaced['combined_anchor_blocks']],['statement'])
        self.assertEqual(len(replaced['record_citation_anchors'][0]['record_evidence_ids']),2)
        # A requested additional geographic dimension remains explicitly deliverable.
        documents['region']=[{'context_id':'ctx','block_id':'geographic'}]
        retained=selection_effect(self.coverage,self.evidence,self.origins,chosen,documents)
        self.assertEqual(len(retained['combined_anchor_blocks']),2)

    def test_separate_report_requirements_and_unqueried_criteria_are_not_dropped(self):
        amended=deepcopy(self.coverage['numeric']);amended['source_id']='acme-amended'
        amended['query_scope']={**self.scope,'source_snapshot_ids':['acme-amended']}
        amended['evidence_ids']=[];self.coverage['amended']=amended
        value=candidate_index(self.coverage,self.evidence,self.origins,self.scope)
        self.assertEqual(len(value['criteria']),4)
        self.assertEqual([r['candidate_count'] for r in value['criteria'][2:]],[0,0])
        self.assertEqual(value['criteria'][2]['source_id'],'acme-amended')

    def test_large_directory_has_explicit_incomplete_child_pointer_and_full_artifact(self):
        value=candidate_index(self.coverage,self.evidence,self.origins,self.scope)
        value['record_semantics'][0]['dimensions']={'long': 'scope'*1000}
        with tempfile.TemporaryDirectory() as temp:
            store=ArtifactStore(Path(temp))
            page=navigation_page(store,'record-candidate-index',value,scope=self.scope,step=1,max_bytes=512)
            self.assertFalse(page['complete']);self.assertTrue(page['truncated']);self.assertTrue(page['reads'])
            self.assertTrue(page['navigation_only']);self.assertFalse(page['source_body_reading_established'])
            self.assertEqual(store.load(page['artifact']['artifact_id']),value)
            self.assertTrue(any(r['pointer'] for r in page['reads']))


class RuntimeSelectionEffectTests(unittest.TestCase):
    def test_actual_agent_receipt_and_next_packet_show_replacement_without_new_body_read(self):
        fixture=origin_fixtures.RecordOriginsTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.change_duplicate_origin()
        criteria=[fixtures.criterion()]
        def choose(packet,block):
            value=packet['record_candidate_index']
            self.assertTrue(value['complete'])
            self.assertEqual(value['value']['criteria'][0]['candidate_count'],2)
            self.assertEqual(packet['retained_body']['items'],[])
            eid=next(r['evidence_id'] for r in value['value']['candidates'] if r['citations'][0]['block_id']==block)
            return {'action':'select_records','requirement_ids':['revenue'],
                'record_selection':{'record_ids':[eid]},'reason':'Inspect original immutable binding.'}
        def replace(packet):
            effect=packet['record_selection_effect']
            self.assertTrue(effect['complete'])
            self.assertEqual(effect['value']['record_citation_anchors'][0]['block_id'],'b8')
            self.assertEqual(packet['observation']['record_selection_effect'],effect)
            return choose(packet,'b9')
        result,planner=fixture.run_actions([fixtures.plan(criteria),fixtures.query(criteria),
            lambda p:choose(p,'b8'),replace,{'action':'finish'}])
        self.assertEqual(result['status'],'evidence_ready',result['trace'])
        final=planner.packets[-1]['record_selection_effect']
        self.assertEqual(final['value']['record_citation_anchors'][0]['block_id'],'b9')
        self.assertEqual(planner.packets[-1]['retained_body']['items'],[])
        feedback=json.loads((fixture.root/'run/turn-003/feedback.json').read_text())
        self.assertEqual(feedback['record_selection_effect']['value']['record_citation_anchors'][0]['block_id'],'b8')


if __name__=='__main__':unittest.main()
