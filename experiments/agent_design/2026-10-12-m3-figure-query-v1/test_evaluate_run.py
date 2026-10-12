"""Independent evaluator positive and destructive checks; zero model calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import evaluate_run as evaluator


class IndependentAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.gold={'required_prose_references':[
            {'text':"The graph below matches Alphabet Inc. Class A's cumulative five-year total stockholder return on common stock with the cumulative total returns of the S&P 500 index, the NASDAQ Composite index, and the RDG Internet Composite index. The graph tracks the performance of a $100 investment in our common stock and in each index (with the reinvestment of all dividends) from December 31, 2020, to December 31, 2025. The returns shown are based on historical results and are not intended to suggest future performance."},
            {'text':"The graph below matches Alphabet Inc. Class C's cumulative five-year total stockholder return on capital stock with the cumulative total returns of the S&P 500 index, the NASDAQ Composite index, and the RDG Internet Composite index. The graph tracks the performance of a $100 investment in our Class C capital stock and in each index (with the reinvestment of all dividends) from December 31, 2020, to December 31, 2025. The returns shown are based on historical results and are not intended to suggest future performance."}]}
        self.documents=[{'source_snapshot_id':'frozen-source','blocks':[
            {'block_id':'arbitrary-A','type':'paragraph','text':self.gold['required_prose_references'][0]['text']},
            {'block_id':'arbitrary-C','type':'paragraph','text':self.gold['required_prose_references'][1]['text']}]}]

    def test_semantic_originals_allow_new_block_ids_and_parser_sentence_splits(self):
        checks,extras,repeats,_=evaluator.prose_components(self.documents,self.gold)
        self.assertTrue(all(c['passed'] for c in checks));self.assertFalse(extras+repeats)
        documents=deepcopy(self.documents)
        text=documents[0]['blocks'][0]['text'];cut=text.index(' The graph tracks')
        documents[0]['blocks'][0]['text']=text[:cut]
        documents[0]['blocks'].insert(1,{'block_id':'new-split','type':'paragraph','text':text[cut:].strip()})
        checks,extras,repeats,_=evaluator.prose_components(documents,self.gold)
        self.assertTrue(all(c['passed'] for c in checks));self.assertFalse(extras+repeats)

    def test_missing_other_stock_class_is_not_supplied_by_shared_assumptions(self):
        documents=deepcopy(self.documents);documents[0]['blocks'].pop()
        checks,_,_,_=evaluator.prose_components(documents,self.gold)
        self.assertTrue(all(c['passed'] for c in checks if c['component'].startswith('Class A')))
        self.assertTrue(all(not c['passed'] for c in checks if c['component'].startswith('Class C')))

    def test_deleted_limit_missing_period_extra_finance_and_repeated_prose_are_detected(self):
        documents=deepcopy(self.documents)
        documents[0]['blocks'][0]['text']=documents[0]['blocks'][0]['text'].split(' The returns shown')[0]
        checks,_,_,_=evaluator.prose_components(documents,self.gold)
        self.assertFalse(next(c['passed'] for c in checks if c['component']=='Class A historical_limit'))
        documents=deepcopy(self.documents)
        documents[0]['blocks'].append({'block_id':'finance','type':'paragraph','text':'Revenue increased to $20 billion.'})
        documents[0]['blocks'].append({**documents[0]['blocks'][0],'block_id':'duplicate'})
        checks,extras,repeats,_=evaluator.prose_components(documents,self.gold)
        self.assertTrue(all(c['passed'] for c in checks));self.assertEqual(len(extras),1);self.assertEqual(len(repeats),1)
        documents=deepcopy(self.documents)
        documents[0]['blocks'][0]['text']+=' Revenue increased to $20 billion.'
        checks,extras,_,_=evaluator.prose_components(documents,self.gold)
        self.assertTrue(all(c['passed'] for c in checks));self.assertEqual(len(extras),1)

    def test_rgb_categories_preserve_the_frozen_visual_semantics(self):
        for color,expected in [('red','red'),('#e02020','red'),('#4c9a2a','green'),('#f2d024','yellow'),('#1a3a8f','blue')]:
            self.assertEqual(evaluator.semantic_color(color),expected)
        self.assertNotEqual(evaluator.semantic_color('#202020'),'blue')

    def test_original_hash_inventory_mapping_checks_identity_count_not_labels(self):
        """Dict values are labels, never expected occurrence counts."""
        # Exercise the checker, including actual original file hashing. Two
        # independent synthetic inventories would fail the original dict bug.
        for labels in [('Issuer X Class A','Issuer X Class C'),('Company Z first chart','Company Z second chart')]:
            with self.subTest(labels=labels),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);figures=[];images={}
                others=['Market A','Market B','Market C']
                colors={label:['red'] for label in labels}
                colors.update(dict(zip(others,[['green'],['yellow'],['blue']])))
                for index,label in enumerate(labels):
                    path=root/('image-'+str(index));path.write_bytes(label.encode())
                    identity=hashlib.sha256(path.read_bytes()).hexdigest();images[identity]=label
                    legends=[label,*others]
                    transcription={'texts':[{'id':'legend-'+str(i),'role':'legend','text':text} for i,text in enumerate(legends)],
                        'series':[{'legend_id':'legend-'+str(i),'color':color} for i,color in enumerate(['red','green','yellow','blue'])],
                        'printed_values':[],'unreadable_regions':[]}
                    figures.append({'image_sha256':identity,'transcription':transcription,'figure_id':'figure-'+str(index),
                        'source_snapshot_id':'explicit-'+labels[0],'original_image_path':str(path),
                        'status':'ocr_grounded','coordinate_status':'ocr_grounded','transcription_sha256':'explicit-transcript-pin'})
                gold={'images':images,'legend_other':others,'x_ticks':[],'y_ticks':[],
                    'visible_text_count_per_image':4,'colors':colors}
                self.assertTrue(all(c['passed'] for c in evaluator.figure_components(figures,gold)))
                for malformed in [figures[:1],[figures[0],figures[0]],figures+[figures[0]]]:
                    self.assertFalse(evaluator.figure_components(malformed,gold)[0]['passed'])

    def test_empty_unobserved_fields_and_partial_text_are_not_complete(self):
        full={'context':'abcdefghijkl','empty':[],'texts':[{'text':'Label','x':1}],'empty_string':''}
        observer=evaluator.ObservedLeaves(full)
        observer.preview(full,{'context':'abcdef','texts':[{'text':'Label'}]})
        self.assertIn('/empty',observer.missing());self.assertIn('/empty_string',observer.missing())
        self.assertIn('/texts/0/x',observer.missing());self.assertIn('/context',observer.missing())
        observer.preview(full,{'empty':[],'empty_string':'','texts':[{'text':'Label','x':1}]})
        observer.page({'pointer':'/context','unit':'characters','items':'ghijkl','offset':6,
            'end_offset':12,'total_count':12,'returned_count':6})
        self.assertEqual(observer.missing(),[])
        with self.assertRaisesRegex(ValueError,'differ'):
            observer.page({'pointer':'/context','unit':'characters','items':'wrong','offset':0,
                'end_offset':5,'total_count':12,'returned_count':5})

    def test_actual_next_input_and_successful_selection_are_required(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);full={'figure':{'transcription':{'texts':[]},'document_context':'Original prose'},'identity':'pinned'}
            artifact=root/'figure.json';artifact.write_text(json.dumps(full))
            ref={'artifact_id':'figure-art','path':'figure.json','sha256':hashlib.sha256(artifact.read_bytes()).hexdigest()}
            (root/'evidence-bundle.json').write_text(json.dumps({'items':[{'kind':'figure','evidence_id':'e','artifact':ref}]}))
            first=root/'turn-001';first.mkdir();(first/'input.json').write_text(json.dumps({'observation':None}))
            second=root/'turn-002';second.mkdir()
            (second/'input.json').write_text(json.dumps({'observation':{'result_artifact':ref,'result':full}}))
            (second/'decision.json').write_text(json.dumps({'action':'select_figures','figure_delivery':{'evidence_ids':['e']}}))
            (second/'receipt.json').write_text(json.dumps({'status':'figures_selected'}))
            selected=[{'figure_id':'f','evidence_id':'e'}]
            self.assertTrue(evaluator.independent_reading(root,selected)[0]['passed'])
            (second/'input.json').write_text(json.dumps({'observation':{'result_artifact':ref,'result':{'identity':'pinned'}}}))
            row=evaluator.independent_reading(root,selected)[0]
            self.assertFalse(row['passed']);self.assertTrue(row['successful_explicit_selections'][0]['missing_at_selection'])

    def test_body_receipt_requires_exact_text_in_actual_input(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);full={'source_snapshot_id':'s','blocks':[{'block_id':'b','text':'Actual full text'}]}
            artifact=root/'body.json';artifact.write_text(json.dumps(full))
            ref={'artifact_id':'body-art','path':'body.json','sha256':hashlib.sha256(artifact.read_bytes()).hexdigest()}
            (root/'evidence-bundle.json').write_text(json.dumps({'items':[{'kind':'context','evidence_id':'c','artifact':ref}]}))
            turn=root/'turn-001';turn.mkdir()
            packet={'observation':None,'retained_body':{'items':[{'source_snapshot_id':'s','block_id':'b','text':'Actual full'}]}}
            path=turn/'input.json';path.write_text(json.dumps(packet))
            documents=[{'source_snapshot_id':'s','blocks':[{'block_id':'b','text':'Actual full text'}]}]
            self.assertFalse(evaluator.independent_body_reading(root,documents)[0]['passed'])
            packet['retained_body']['items'][0]['text']='Actual full text';path.write_text(json.dumps(packet))
            self.assertTrue(evaluator.independent_body_reading(root,documents)[0]['passed'])


if __name__=='__main__':unittest.main()
