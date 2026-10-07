"""Synthetic renderer acceptance; no provider requests or reported model quality."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from tests.unit.test_business_map_view import fixture,svg_fixture
from uteki.presentation.business_map_view import presentation

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('subsection_view',HERE/'build_view.py')
view=importlib.util.module_from_spec(spec);spec.loader.exec_module(view)


class BuilderTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(dir=HERE,prefix='.synthetic-render-')
        self.addCleanup(tmp.cleanup);self.base=Path(tmp.name);self.run=self.base/'run';self.run.mkdir()
        self.output=self.base/'page'
        data=fixture();text=data['evidence'][0]['support']
        self.source=self.base/'source.html';self.source.write_text('<html><body><p>'+text+'</p></body></html>')
        scope={'kind':'complete_report_subsection','title':'Orion / Products','section_block_ids':['source-block']}
        self.packet=dict(company_id='orion',document_id='filing-2031',period_end='2031-06-30',
            source_local_path=str(self.source.relative_to(view.ROOT)),source_sha256=view.sha(self.source),
            source_url='https://example.invalid/orion',extraction_scope=scope,
            blocks=[dict(id='source-block',ordinal=1,text=text,text_sha256=__import__('hashlib').sha256(text.encode()).hexdigest(),
                source_dom_path='/html/body/p',section_path=['Products'],input_role='selected_subsection')])
        self.write('source_packet.json',self.packet);self.write('request.json',{'synthetic':'not_a_model_run'})
        self.write('manifest.json',{'synthetic':True});(self.run/'skill.md').write_text('Synthetic skill.')
        (self.run/'evidence.html').write_text('<html><body><section id="source-block">'+text+'</section></body></html>')
        data['evidence'][0]['text_hash']=self.packet['blocks'][0]['text_sha256']
        loc={**data['evidence'][0],'source_dom_path':'/html/body/p','exact_quote':text,
            'local_path':str((self.run/'evidence.html').relative_to(view.ROOT)),'fragment':'source-block'}
        data['metadata']=dict(extraction_method='system_agent',period_end='2031-06-30',trace_id='synthetic-trace',
            source_sha256=self.packet['source_sha256'],source_packet_sha256=view.sha(self.run/'source_packet.json'),
            skill_sha256=view.sha(self.run/'skill.md'),extraction_scope=scope,evidence_locators={'source-block':loc},
            block_disposition=[dict(block_id='source-block',disposition='used',reason='Synthetic fixture selection.')])
        for item in data['businesses']+data['relationships']:item['review_status']='candidate'
        self.data=data;self.write('business_map.json',data)
        self.result=dict(company_id='orion',document_id='filing-2031',period_end='2031-06-30',trace_id='synthetic-trace',
            status='candidate',validation='passed',source_packet_sha256=data['metadata']['source_packet_sha256'],
            skill_sha256=data['metadata']['skill_sha256'],request_sha256=view.sha(self.run/'request.json'),
            artifacts_sha256={name:view.sha(self.run/name) for name in ('business_map.json','evidence.html')})
        self.write('result.json',self.result)

    def write(self,name,data):
        (self.run/name).write_text(json.dumps(data,ensure_ascii=False))

    def test_synthetic_page_has_complete_graph_bound_claims_and_no_unknown_line(self):
        view.build(self.run,self.output)
        (self.output/'assets/business.svg').write_text(svg_fixture(presentation(self.data)))
        view.build(self.run,self.output,with_svg=True)
        check=json.loads((self.output/'verification.json').read_text())
        self.assertEqual((check['nodes'],check['asserted_edges'],check['unresolved_edges']),(3,2,1))
        self.assertFalse(check['review_attached'])
        page=(self.output/'index.html').read_text()
        for value in ('Orion','Nimbus','Helix'):self.assertIn(value,page)
        self.assertIn('node-N002',page)
        self.assertIn('edge-R03',page)
        self.assertIn('关系未确定，未作为图中连线',page)
        self.assertNotIn('<!-- DIAGRAM -->',page)
        self.assertIn('模型自报',page)
        self.assertIn('选定小节 / Selected subsection: 1',page)
        self.assertIn('身份与报告期上下文 / Scope metadata: 0',page)

    def test_bound_review_gaps_are_prominent_without_promoting_candidate(self):
        *_,binding,_=view.validate(self.run,self.output,None)
        review=self.base/'review.json';review.write_text(json.dumps(dict(binding=binding,summary='Synthetic review.',
            checks=[dict(id='gap',label='Missing source coverage',status='gap',observation='Synthetic gap.',source_block_ids=['source-block'])])))
        view.build(self.run,self.output,review)
        (self.output/'assets/business.svg').write_text(svg_fixture(presentation(self.data)))
        view.build(self.run,self.output,review,with_svg=True)
        page=(self.output/'index.html').read_text()
        self.assertIn('候选待修 / Candidate needs work',page)
        self.assertIn('这份产物尚未通过内容验收',page)
        check=json.loads((self.output/'verification.json').read_text())
        self.assertEqual(check['semantic_acceptance'],'needs_work')
        self.assertEqual(json.loads((self.run/'result.json').read_text())['status'],'candidate')

    def test_changed_source_wrong_evidence_target_and_unbound_review_are_rejected(self):
        self.source.write_text('<html><body><p>Different source.</p></body></html>')
        with self.assertRaisesRegex(ValueError,'source_hash_mismatch'):view.validate(self.run,self.output,None)
        self.source.write_text('<html><body><p>'+self.data['evidence'][0]['support']+'</p></body></html>')
        review=self.base/'review.json';review.write_text(json.dumps({'binding':{},'checks':[]}))
        with self.assertRaisesRegex(ValueError,'review_binding_mismatch'):view.validate(self.run,self.output,review)
        data=deepcopy(self.data);data['metadata']['evidence_locators']['source-block']['fragment']='wrong'
        self.write('business_map.json',data)
        self.result['artifacts_sha256']['business_map.json']=view.sha(self.run/'business_map.json');self.write('result.json',self.result)
        with self.assertRaisesRegex(ValueError,'precise_evidence_anchor_mismatch'):view.validate(self.run,self.output,None)

    def test_repaired_candidate_exposes_failed_parent_and_separate_request(self):
        parent=self.base/'failed-parent';parent.mkdir()
        for name,value in {'result.json':{**self.result,'status':'failed','trace_id':'parent-trace'},
                'request.json':{'system':'Original extraction system'}}.items():
            (parent/name).write_text(json.dumps(value))
        (parent/'response.txt').write_text('Frozen original response.')
        self.write('request.json',{'system':'Repair only selected fields.'})
        for name in ('configuration.json','patch_output_schema.json','patch.json','patch-diff.json','patched-draft.json'):
            self.write(name,{'synthetic':True})
        lineage=dict(execution_mode='model_patch_repair',parent_run_dir=str(parent.relative_to(view.ROOT)),
            parent_trace_id='parent-trace',parent_result_sha256=view.sha(parent/'result.json'),
            parent_response_sha256=view.sha(parent/'response.txt'),parent_request_sha256=view.sha(parent/'request.json'),
            parent_extraction_skill_sha256=self.result['skill_sha256'],
            repair_system_sha256=__import__('hashlib').sha256(b'Repair only selected fields.').hexdigest(),
            patch_schema_sha256=view.sha(self.run/'patch_output_schema.json'),
            actual_skill_context='parent_extraction_snapshot_not_resent')
        self.data['metadata'].update(lineage);self.write('business_map.json',self.data)
        self.result.update(lineage,request_sha256=view.sha(self.run/'request.json'))
        self.result['artifacts_sha256']['business_map.json']=view.sha(self.run/'business_map.json')
        self.write('result.json',self.result)
        view.build(self.run,self.output)
        (self.output/'assets/business.svg').write_text(svg_fixture(presentation(self.data)))
        view.build(self.run,self.output,with_svg=True)
        page=(self.output/'index.html').read_text()
        self.assertIn('经一次模型局部修正',page)
        self.assertIn('原始运行仍记录为失败',page)
        self.assertIn('父提取 Skill 快照',page)
        self.assertIn('agent-runs?run=parent-trace',page)
        self.assertEqual(json.loads((parent/'result.json').read_text())['status'],'failed')
        (parent/'response.txt').write_text('Changed response.')
        with self.assertRaisesRegex(ValueError,'repair_parent_fingerprint_mismatch'):view.validate(self.run,self.output,None)


if __name__=='__main__':unittest.main()
