"""Pinned, portable acceptance entry; scripted Data fixtures, no API or browser."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import shutil
import unittest
from urllib.parse import unquote, urlparse, parse_qs

from lxml import html
from apps.review_workbench.pages.data_retrieval_suite import render_data_retrieval_suite
from uteki.agents.data_query.answer_handoff import prepare_review_packet, review_data_answer
from uteki.agents.data_query.retrieval_cycle import _seal
from uteki.infrastructure.research_data.financial_records import digest
from tests.unit import test_analysis_evidence_runtime as runtime_fixtures
from tests.unit.test_analysis_evidence_runtime import choose
from tests.unit.test_autonomous_source_evidence import source_plan, context_read
from tests.unit.test_answer_handoff import ScriptedRole
from tests.unit.test_bounded_answer_handoff import narrow_assessment


class SuiteDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=runtime_fixtures.AnalysisEvidenceRuntimeTests(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root
        _,_,query=self.fixture.run_actions([source_plan(),context_read(),choose('b1'),{'action':'finish'}])
        self.packet=prepare_review_packet(query,self.fixture.dataset,expected_scope=self.fixture.scope,
            max_packet_bytes=100000,source_delivery='query_evidence_v1')
        self.cycle=self.root/'cycle'; attempt=self.cycle/'attempt-01'; attempt.mkdir(parents=True)
        def assess(packet):
            result=narrow_assessment(packet)
            for fact in result['facts']: fact['relevance']='necessary'
            result['body_checks']=[{'source_snapshot_id':d['source_snapshot_id'],'block_id':b['block_id'],
                'relevance':'necessary','rationale':'Synthetic exact requested original.'}
                for d in packet['source_documents'] for b in d['blocks']]
            return result
        review=asyncio.run(review_data_answer(self.packet,attempt/'review-01',
            reviewer_factory=lambda path:ScriptedRole(assess)))
        self.assertEqual(review['status'],'reviewed',review)
        row={'attempt':1,'path':'attempt-01','status':'reviewed_data_ready','execution':'reused_frozen',
            'query_ref':self.packet['query_ref'],'reviews':[{'status':'reviewed','review_ref':review['review_ref'],'analysis_eligible':True}]}
        self.save(attempt/'result.json',row)
        self.result={'schema_version':'data-retrieval-cycle-v1','status':'reviewed_data_ready',
            'question':self.packet['question'],'scope':self.packet['scope'],'purpose':'analysis_evidence',
            'analysis_called':False,'attempts':[row],'final_query_ref':self.packet['query_ref'],
            'final_review_ref':review['review_ref'],'failures':[]}
        self.save(self.cycle/'original-request.json',{'question':self.packet['question'],'scope':self.packet['scope'],'purpose':'analysis_evidence'})
        self.save(self.cycle/'result.json',self.result); _seal(self.cycle)
        self.suite=self.root/'suite.json'; self.output=self.root/'delivery'
        self.spec={'schema_version':'data-retrieval-suite-v1','cases':[{'case_id':'acme-originals','cycle_dir':'cycle',
            'manifest_sha256':digest((self.cycle/'manifest.json').read_bytes())}]}
        self.save(self.suite,self.spec)

    @staticmethod
    def save(path,value):
        path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(value))

    def reseal(self):
        (self.cycle/'manifest.json').unlink()
        _seal(self.cycle)
        self.spec['cases'][0]['manifest_sha256']=digest((self.cycle/'manifest.json').read_bytes())
        self.save(self.suite,self.spec)

    def test_portable_entry_links_to_exact_evidence_and_reused_query_trace(self):
        report=render_data_retrieval_suite(self.suite,self.output)
        case=report['cases'][0]
        self.assertEqual(case['delivered_blocks'],1)
        self.assertEqual(case['original_characters'],len(self.packet['source_documents'][0]['blocks'][0]['text']))
        self.assertEqual(case['revision_rounds'],0)
        self.assertEqual(case['human_acceptance'],'not_evaluated')
        self.assertEqual(case['external_query_copies'],['external-query-1'])
        self.assertEqual(case['query_executions'],[{'attempt':1,'execution':'reused_frozen'}])
        relocated=(self.root/'moved-delivery').resolve(); shutil.copytree(self.output,relocated)
        for path in relocated.rglob('*.html'):
            page=html.fromstring(path.read_bytes())
            for href in page.xpath('//a/@href'):
                url=urlparse(href)
                if url.scheme: self.assertIn(url.scheme,{'https','http'}); continue
                self.assertFalse(Path(unquote(url.path)).is_absolute())
                target=(path.parent/unquote(url.path)).resolve() if url.path else path
                self.assertTrue(target.is_relative_to(relocated))
                self.assertTrue(target.exists(),href)
        self.assertIn('模型复核通过不等于 Codex 独立验收',(relocated/'index.html').read_text())
        copied=relocated/'cases/acme-originals/process/external-query-1/result.json'
        self.assertEqual(copied.read_bytes(),(Path(self.packet['query_ref']['path'])/'result.json').read_bytes())

    def test_failed_sealed_cycle_has_trace_without_success_or_fake_metrics(self):
        self.result.update(status='blocked_by_query',final_review_ref=None,final_query_ref=None)
        self.result['attempts'][0].update(status='blocked_by_query',query_status='failed',reviews=[])
        self.save(self.cycle/'attempt-01/result.json',self.result['attempts'][0])
        self.save(self.cycle/'result.json',self.result); self.reseal()
        result=render_data_retrieval_suite(self.suite,self.output)
        self.assertEqual(result['cases'][0]['status'],'blocked_by_query')
        self.assertIsNone(result['cases'][0]['delivered_blocks'])
        self.assertFalse((self.output/'cases/acme-originals/review').exists())
        self.assertTrue((self.output/'cases/acme-originals/process/index.html').exists())
        self.assertIn('尚无复核交付',(self.output/'index.html').read_text())

    def test_optional_independent_assessment_is_copied_without_marking_accepted(self):
        assessment=self.root/'independent.md'; assessment.write_text('Independent review: still pending.')
        self.spec['cases'][0]['independent_assessment']={'path':'independent.md','sha256':digest(assessment.read_bytes())}
        self.save(self.suite,self.spec)
        result=render_data_retrieval_suite(self.suite,self.output)
        self.assertTrue(result['cases'][0]['independent_assessment_supplied'])
        self.assertEqual(result['cases'][0]['human_acceptance'],'not_evaluated')
        self.assertEqual((self.output/'cases/acme-originals/independent-assessment.md').read_bytes(),assessment.read_bytes())

    def test_assessment_links_remain_portable_after_inputs_removed(self):
        folder=self.root/'evaluation-only'; folder.mkdir()
        assessment=folder/'review.md'; sidecar=folder/'review.json'
        sidecar.write_text('{"verdict":"pass","note":"offline synthetic review"}')
        query=Path(self.packet['query_ref']['path'])
        assessment.write_text('# Independent review\n\n| Evidence | Status |\n|---|---|\n'
            '| [Cycle](../cycle/result.json) | pinned |\n\n'
            '[Review](../cycle/attempt-01/review-01/input.json)\n'
            '[Query]('+str(query/'result.json')+')\n'
            '[Details](review.json)\n'
            '[Unpinned](unlisted.json)\n'
            '[Outside](https://example.org/original)\n'
            '[Unsafe](javascript:alert)\n<script>do_not_execute()</script>')
        (folder/'unlisted.json').write_text('{"private":"not requested"}')
        original=assessment.read_bytes(); sidecar_raw=sidecar.read_bytes()
        self.spec['cases'][0]['independent_assessment']={'path':'evaluation-only/review.md',
            'sha256':digest(original),'attachments':[{'path':'review.json','sha256':digest(sidecar_raw)}]}
        self.save(self.suite,self.spec)
        result=render_data_retrieval_suite(self.suite,self.output)
        moved=(self.root/'relocated').resolve();shutil.copytree(self.output,moved)
        # The delivery must stand alone even after its input sources disappear.
        shutil.rmtree(self.cycle);shutil.rmtree(folder);shutil.rmtree(query)
        dest=moved/'cases/acme-originals'
        self.assertEqual((dest/'independent-assessment.md').read_bytes(),original)
        self.assertEqual((dest/'assessment-files/review.json').read_bytes(),sidecar_raw)
        page=html.fromstring((dest/'independent-assessment.html').read_bytes())
        self.assertTrue(page.xpath('//table'));self.assertFalse(page.xpath('//script'))
        links=page.xpath('//a/@href')
        for href in links:
            parsed=urlparse(href)
            if parsed.scheme:
                self.assertEqual(href,'https://example.org/original');continue
            target=(dest/unquote(parsed.path)).resolve()
            self.assertTrue(target.is_relative_to(moved));self.assertTrue(target.is_file(),href)
        self.assertIn('process/cycle/result.json',links)
        self.assertIn('process/cycle/attempt-01/review-01/input.json',links)
        self.assertIn('process/external-query-1/result.json',links)
        self.assertIn('assessment-files/review.json',links)
        self.assertFalse((dest/'assessment-files/unlisted.json').exists())
        metadata=result['cases'][0]['independent_assessment_files']
        self.assertEqual(metadata['original_sha256'],digest(original))
        self.assertEqual(metadata['attachments'],[{'path':'assessment-files/review.json','sha256':digest(sidecar_raw)}])
        self.assertEqual(metadata['portable_link_count'],4)
        self.assertEqual(metadata['unbundled_sources'],['unlisted.json','javascript:alert'])
        self.assertIn('未随包复制',page.text_content())

    def test_assessment_attachments_require_same_directory_explicit_json_and_hash(self):
        folder=self.root/'assessment';folder.mkdir();doc=folder/'review.md';doc.write_text('Review')
        sidecar=folder/'review.json';sidecar.write_text('{}')
        symlink=folder/'alias.json';symlink.symlink_to(sidecar)
        cases=[{'path':'../assessment/review.json','sha256':digest(sidecar.read_bytes())},
               {'path':str(sidecar),'sha256':digest(sidecar.read_bytes())},
               {'path':'review.md','sha256':digest(doc.read_bytes())},
               {'path':'review.json','sha256':'0'*64},
               {'path':'alias.json','sha256':digest(sidecar.read_bytes())},
               {'path':'missing.json','sha256':'0'*64}]
        for item in cases:
            self.spec['cases'][0]['independent_assessment']={'path':'assessment/review.md',
                'sha256':digest(doc.read_bytes()),'attachments':[item]}
            self.save(self.suite,self.spec)
            with self.subTest(item=item),self.assertRaises((ValueError,FileNotFoundError)):
                render_data_retrieval_suite(self.suite,self.output)
            self.assertFalse(self.output.exists())

    def test_explicit_preview_reaches_every_original_highlight_link(self):
        self.spec['cases'][0]['preview']={'dataset_key':'registered-acme',
            'source_preview_base_url':'http://127.0.0.1:8765/data-workspace/source'}
        self.save(self.suite,self.spec)
        render_data_retrieval_suite(self.suite,self.output)
        page=html.fromstring((self.output/'cases/acme-originals/review/index.html').read_bytes())
        refs=json.loads((self.output/'cases/acme-originals/review/delivery.json').read_text())['references']
        links=[urlparse(href) for href in page.xpath('//a/@href') if '/data-workspace/source?' in href]
        self.assertEqual(len(links),len(refs))
        self.assertTrue(links)
        for link,ref in zip(links,refs):
            query=parse_qs(link.query)
            self.assertEqual(query['dataset'],['registered-acme'])
            self.assertEqual(query['char_start'],[str(ref['char_start'])])
            self.assertEqual(query['char_end'],[str(ref['char_end'])])
            self.assertEqual(query['source_sha256'],[ref['source_sha256']])
            self.assertEqual(link.fragment,'workspace-evidence')

    def test_partial_or_invalid_preview_is_rejected_before_delivery(self):
        for preview in (None,{}, {'dataset_key':'registered-acme'},
                {'source_preview_base_url':'http://localhost/source'},
                {'dataset_key':None,'source_preview_base_url':None},
                {'dataset_key':'../bad','source_preview_base_url':'http://localhost/source'},
                {'dataset_key':'registered-acme','source_preview_base_url':'javascript:alert(1)'},
                {'dataset_key':'registered-acme','source_preview_base_url':'http://localhost/source?dataset=other'}):
            self.spec['cases'][0]['preview']=preview;self.save(self.suite,self.spec)
            with self.subTest(preview=preview),self.assertRaises(ValueError):
                render_data_retrieval_suite(self.suite,self.output)
            self.assertFalse(self.output.exists())

    def test_all_explicit_cases_render_without_selecting_an_unlisted_cycle(self):
        self.spec['cases']=[{**self.spec['cases'][0],'case_id':f'case-{i}'} for i in range(1,7)]
        self.save(self.suite,self.spec)
        unlisted=self.root/'newer-cycle'; unlisted.mkdir(); (unlisted/'result.json').write_text('not sealed')
        result=render_data_retrieval_suite(self.suite,self.output)
        self.assertEqual([c['case_id'] for c in result['cases']],[f'case-{i}' for i in range(1,7)])
        self.assertEqual(len(list((self.output/'cases').iterdir())),6)
        self.assertNotIn('newer-cycle',(self.output/'index.html').read_text())

    def test_absolute_manifest_entry_cannot_overwrite_frozen_original(self):
        manifest=json.loads((self.cycle/'manifest.json').read_text())
        original=(self.cycle/'result.json').read_bytes()
        manifest['files'][str((self.cycle/'result.json').resolve())]=digest(original)
        self.save(self.cycle/'manifest.json',manifest)
        self.spec['cases'][0]['manifest_sha256']=digest((self.cycle/'manifest.json').read_bytes())
        self.save(self.suite,self.spec)
        with self.assertRaisesRegex(ValueError,'relative'):
            render_data_retrieval_suite(self.suite,self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual((self.cycle/'result.json').read_bytes(),original)

    def test_missing_unsealed_or_hash_mismatched_cycle_rejected_without_output(self):
        original=deepcopy(self.spec)
        for update in ({'cycle_dir':'missing'},{'manifest_sha256':'0'*64},{'manifest_sha256':None}):
            self.spec=deepcopy(original); self.spec['cases'][0].update(update); self.save(self.suite,self.spec)
            with self.subTest(update=update),self.assertRaises((ValueError,FileNotFoundError)):
                render_data_retrieval_suite(self.suite,self.output)
            self.assertFalse(self.output.exists())
        self.spec=deepcopy(original); self.save(self.suite,self.spec); (self.cycle/'manifest.json').unlink()
        with self.assertRaises(FileNotFoundError):render_data_retrieval_suite(self.suite,self.output)
        self.assertFalse(self.output.exists())

    def test_resealed_cross_question_success_without_review_and_duplicate_case_rejected(self):
        original=deepcopy(self.result)
        for changes in ({'question':'Different question'},{'final_review_ref':None}):
            self.result={**original,**changes}; self.save(self.cycle/'result.json',self.result); self.reseal()
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                render_data_retrieval_suite(self.suite,self.output)
            self.assertFalse(self.output.exists())
        self.save(self.cycle/'result.json',original); self.reseal()
        self.spec['cases'].append(deepcopy(self.spec['cases'][0])); self.save(self.suite,self.spec)
        with self.assertRaisesRegex(ValueError,'Unique'):render_data_retrieval_suite(self.suite,self.output)
        self.assertFalse(self.output.exists())
