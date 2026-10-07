"""Small independent scope and evidence failures, not sample-answer tests."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('map_view',Path(__file__).with_name('build_view.py'))
view=importlib.util.module_from_spec(spec);spec.loader.exec_module(view)

class ViewBoundaryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        source=self.root/'source.html';source.write_text('<html><meta charset="utf-8"><p id="p1">Zeta owns a tools business.</p></html>')
        self.data={'schema_version':'candidate-v1','company_id':'zeta','document_id':'zeta-2024',
            'summary':'Independent synthetic company, no financial answer.',
            'businesses':[{'id':'zeta','name':'Zeta','kind':'company','description':'Company.', 'evidence_ids':['e1'],'review_status':'candidate'},
                {'id':'tools','name':'Tools','kind':'business','description':'Tools business.', 'evidence_ids':['e1'],'review_status':'candidate'}],
            'relationships':[{'source_id':'tools','target_id':'zeta','kind':'part_of','description':'Belongs to company.','evidence_ids':['e1'],'review_status':'candidate'}],
            'unknowns':[], 'evidence':[{'id':'e1','document_id':'zeta-2024','section_path':['Business'],'paragraph_ordinal':1,
                'text_hash':hashlib.sha256(b'Zeta owns a tools business.').hexdigest(),'source_url':'https://example.invalid/report','support':'Zeta owns a tools business.'}],
            'metadata':{'report_label':'Zeta 2024','period_end':'2024-12-31','source_local_path':'source.html',
                'source_url':'https://example.invalid/report','source_sha256':view.sha(source),'extraction_method':'codex_source_review',
                'evidence_locators':{'e1':{'local_path':'source.html','fragment':'p1','exact_quote':'Zeta owns a tools business.'}}}}
        patcher=patch.object(view,'ROOT',self.root);patcher.start();self.addCleanup(patcher.stop)
    def validate(self,data=None):
        path=self.root/'business_map.json';path.write_text(json.dumps(data or self.data))
        return view.validate(path)[0]
    def test_other_company_period_and_inverse_relationship_are_preserved(self):
        data=self.validate();mmd,ids=view.mermaid(data)
        self.assertEqual(data['company_id'],'zeta');self.assertEqual(data['metadata']['period_end'],'2024-12-31')
        self.assertIn('N000 -->|"包含"| N001',mmd)
        self.assertEqual(ids,{'zeta':'N000','tools':'N001'})
        self.assertEqual(data['relationships'][0]['source_id'],'tools')
    def test_missing_scope_and_cross_document_evidence_are_rejected(self):
        for field in ['period_end','source_local_path','source_sha256']:
            bad=copy.deepcopy(self.data);bad['metadata'].pop(field)
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'missing_metadata'):self.validate(bad)
        bad=copy.deepcopy(self.data);bad['evidence'][0]['document_id']='other-company'
        with self.assertRaisesRegex(ValueError,'cross_document_evidence'):self.validate(bad)
    def test_invented_quote_missing_anchor_and_source_change_are_rejected(self):
        bad=copy.deepcopy(self.data);bad['metadata']['evidence_locators']['e1']['exact_quote']='Made up a new line.'
        with self.assertRaisesRegex(ValueError,'quote_not_in_anchored_fragment'):self.validate(bad)
        bad=copy.deepcopy(self.data);bad['metadata']['evidence_locators']['e1']['fragment']='not-here'
        with self.assertRaisesRegex(ValueError,'evidence_anchor'):self.validate(bad)
        (self.root/'source.html').write_text('Changed source')
        with self.assertRaisesRegex(ValueError,'source_hash_mismatch'):self.validate()
    def test_mermaid_labels_cannot_escape_node_and_edge_labels_keep_inverse_meaning(self):
        self.data['businesses'][1]['name']='Tools"] --> Fake["<script>'
        self.data['relationships'][0]['kind']='supports'
        mmd,_=view.mermaid(self.validate())
        self.assertIn('#quot;',mmd);self.assertIn('#lt;script#gt;',mmd)
        self.assertIn('N000 -.->|"支撑来自"| N001',mmd)

    def test_layer_view_preserves_shared_relations_and_declines_cycles(self):
        self.assertEqual(view.layer_ranks(self.data),{'zeta':0,'tools':1})
        cyclic=copy.deepcopy(self.data)
        cyclic['relationships'].append({'source_id':'zeta','target_id':'tools','kind':'supports','evidence_ids':['e1']})
        self.assertIsNone(view.layer_ranks(cyclic))
        self.assertEqual(len(view.presentation_edges(cyclic)),2)
        self.assertEqual(len(cyclic['relationships']),2)

if __name__=='__main__':unittest.main()
