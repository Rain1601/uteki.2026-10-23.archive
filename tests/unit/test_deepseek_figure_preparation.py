"""Provider-selectable figure preparation, with real Runner and mocked HTTP/OCR."""
import asyncio
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx2 as httpx
from openai import AsyncOpenAI
from pydantic import ValidationError

import tests.unit.test_figure_acquisition as acquisitions
import tests.unit.test_figure_materials as figures
from tests.unit.test_figure_grounding import mock_ocr_process, tsv
from uteki.agents.figure_materials import (Figure, FigureTranscription, HOST_OCR_PROMPT,
    run_figure_preparation, reground_figure_preparation)
from uteki.infrastructure.document_sources.figure_reader import FigureMaterialReader
from uteki.agents.runtime.call_costs import summarize
from uteki.agents.runtime.deepseek_vision import DeepSeekVisionModel
from uteki.agents.runtime.run_budget import RunBudget


class DeepSeekFigurePreparationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = acquisitions.FigureAcquisitionTests()
        self.fixture.setUp()
        self.fixture.run_acquire()
        self.output = self.fixture.root/'prepared'
        self.sent = []

    def tearDown(self):
        self.fixture.tearDown()

    def prepare(self, *, finish='stop', usage=True, schema_repair=False,
                coordinate_policy='model_proposal', answer=None, ocr_effect=None):
        payload = {'id': 'figure-response', 'object': 'chat.completion', 'created': 1,
            'model': 'deepseek-flash', 'choices': [{'index': 0, 'finish_reason': finish,
                'message': {'role': 'assistant', 'content': json.dumps(
                    figures.chart() if answer is None else answer)}}]}
        if usage:
            payload['usage'] = {'prompt_tokens': 150, 'completion_tokens': 30, 'total_tokens': 180}
        def respond(request):
            self.sent.append(request)
            if schema_repair and len(self.sent) == 1:
                first = json.loads(json.dumps(payload))
                first['choices'][0]['message']['content'] = '{"wrong":true}'
                return httpx.Response(200, json=first)
            return httpx.Response(200, json=payload)
        clients = []
        def model_factory(model, **kwargs):
            client = AsyncOpenAI(api_key='offline-deepseek-key', base_url='https://api.deepseek.com',
                max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
            clients.append(client)
            return DeepSeekVisionModel(model, openai_client=client, **kwargs)
        fixture_ocr = mock_ocr_process({0: tsv([
            ('Series', 1, 1, 3, 1, 99, 1), ('A', 5, 1, 2, 1, 99, 1),
            ('$100', 1, 5, 4, 1, 99, 2)])})
        async def invoke():
            try:
                return await run_figure_preparation(self.fixture.dataset, self.fixture.output,
                    self.output, model='deepseek-flash', provider='deepseek', reasoning_effort='high',
                    coordinate_policy=coordinate_policy,
                    budget=RunBudget(self.fixture.root/'budget.sqlite', '2'), credentials_root=self.fixture.root)
            finally:
                for client in clients:
                    await client.close()
        with patch('uteki.agents.figure_materials.DeepSeekVisionModel', side_effect=model_factory), \
             patch('uteki.agents.figure_materials.load_provider_key') as key, \
             patch('uteki.agents.figure_materials.ClaudeVisionModel') as claude, \
             patch('uteki.infrastructure.document_sources.figure_grounding.shutil.which', return_value='/offline/tesseract'), \
             patch('uteki.infrastructure.document_sources.figure_grounding.subprocess.run', side_effect=ocr_effect or fixture_ocr):
            result = asyncio.run(invoke())
            key.assert_called_once_with(self.fixture.root, 'deepseek')
            claude.assert_not_called()
        return result

    def test_real_typed_preparation_selects_deepseek_and_keeps_pending_acceptance(self):
        original = {str(p): p.read_bytes() for p in self.fixture.dataset.rglob('*') if p.is_file()}
        report = self.prepare()
        self.assertEqual(report['status'], 'prepared')
        self.assertEqual(report['independent_acceptance'], 'pending')
        self.assertEqual(len(self.sent), 1)
        config = json.loads((self.output/'config.json').read_text())
        self.assertEqual(config['provider'], 'deepseek')
        self.assertEqual(config['api_format'], 'chat_completions')
        self.assertEqual(config['thinking'], 'enabled')
        self.assertEqual(config['pricing_snapshot']['output_per_million'], '1.20')
        self.assertEqual(config['image_detail'], 'high')
        figure = report['figures'][0]
        response = json.loads((self.output/figure['figure_id']/'attempt-1/response.json').read_text())
        self.assertEqual(response['metadata']['finish_reason'], 'stop')
        self.assertEqual(response['metadata']['raw_usage']['prompt_tokens'], 150)
        self.assertEqual(original, {str(p): p.read_bytes() for p in self.fixture.dataset.rglob('*') if p.is_file()})

    def test_truncated_output_stops_without_automatic_resend_and_keeps_usage(self):
        report = self.prepare(finish='length')
        self.assertEqual(report['status'], 'with_gaps')
        self.assertEqual(len(self.sent), 1)
        self.assertFalse(list(self.output.glob('*/attempt-2')))
        calls = next(self.output.glob('*/attempt-1/calls'))
        self.assertEqual(summarize(calls)['records'][0]['usage']['output_tokens'], 30)
        self.assertFalse(list(self.output.glob('*/transcription.json')))

    def test_one_local_schema_revision_preserves_both_attempts_on_one_budget(self):
        report = self.prepare(schema_repair=True)
        self.assertEqual(report['status'], 'prepared')
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(len(list(self.output.glob('*/attempt-*/calls/*-end.json'))), 2)
        self.assertTrue(list(self.output.glob('*/attempt-1/failure.json')))
        self.assertEqual(len({row['budget_reservation_id'] for path in self.output.glob('*/attempt-*/calls')
            for row in summarize(path)['records']}), 2)

    def test_unknown_usage_is_retained_and_cannot_become_a_zero_fee(self):
        report = self.prepare(usage=False)
        self.assertEqual(report['independent_acceptance'], 'pending')
        row = summarize(next(self.output.glob('*/attempt-1/calls')))['records'][0]
        self.assertIsNone(row['estimated_usd'])
        self.assertGreater(float(row['reserved_usd']), 0)

    def test_invalid_provider_model_or_effort_rejected_before_output_or_key(self):
        for options in ({'provider':'deepseek', 'model':'claude-sonnet-5-5'},
                        {'provider':'other', 'model':'deepseek-flash'},
                        {'provider':'deepseek', 'model':'deepseek-flash', 'reasoning_effort':'max'},
                        {'provider':'deepseek', 'model':'deepseek-flash', 'coordinate_policy':'unknown'}):
            with self.subTest(options=options), patch('uteki.agents.figure_materials.load_provider_key') as key:
                with self.assertRaises(ValueError):
                    asyncio.run(run_figure_preparation(self.fixture.dataset, self.fixture.output,
                        self.output, budget=None, credentials_root=self.fixture.root, **options))
                self.assertFalse(self.output.exists())
                key.assert_not_called()

    @staticmethod
    def host_transcript():
        value = figures.chart()
        for text in value['texts']:
            del text['box']
        return value

    def test_host_ocr_actual_sdk_schema_omits_text_boxes_and_final_reader_is_strict(self):
        answer = self.host_transcript()
        report = self.prepare(coordinate_policy='host_ocr_v1', answer=answer)
        self.assertEqual(report['status'], 'prepared')
        self.assertEqual(report['independent_acceptance'], 'pending')
        self.assertEqual(len(self.sent), 1)
        body = json.loads(self.sent[0].content)
        system = body['messages'][0]['content']
        self.assertIn(HOST_OCR_PROMPT, system)
        schema = json.loads(system.split('Follow this JSON Schema; all required fields must be present:\n')[1])
        self.assertNotIn('box', schema['$defs']['TranscriptionText']['properties'])
        self.assertIn('box', Figure.model_json_schema()['$defs']['Text']['properties'])
        item = report['figures'][0]
        original_model = json.loads((self.output/item['figure_id']/'model-transcription.json').read_text())
        self.assertEqual(original_model, answer)
        final = FigureMaterialReader(self.output, self.fixture.dataset).read(item['figure_id'])['transcription']
        self.assertEqual(final['texts'][0]['box'], {'x0':100,'y0':50,'x1':700,'y1':100})
        Figure.model_validate(final)
        config = json.loads((self.output/'config.json').read_text())
        self.assertEqual(config['coordinate_policy'], 'host_ocr_v1')
        self.assertEqual(config['schema'], FigureTranscription.model_json_schema())
        self.assertEqual(config['final_schema'], Figure.model_json_schema())

    def test_host_ocr_shared_semantics_reject_missing_empty_duplicate_or_unbound_text(self):
        invalid=[]
        value=self.host_transcript(); del value['texts']; invalid.append(value)
        value=self.host_transcript(); value['texts'][0]['text']=''; invalid.append(value)
        value=self.host_transcript(); value['texts'].append(dict(value['texts'][0])); invalid.append(value)
        value=self.host_transcript(); value['series'][0]['legend_id']='unknown'; invalid.append(value)
        value=self.host_transcript(); value['printed_values']=[dict(text_id='tick',series_legend_id=None,period_text_id=None)]; invalid.append(value)
        value=self.host_transcript(); value['texts'][0]['box']={'x0':0,'y0':0,'x1':1100,'y1':100}; invalid.append(value)
        value=self.host_transcript(); value['unreadable_regions']=[{'x0':0,'y0':0,'x1':1100,'y1':100}]; invalid.append(value)
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                FigureTranscription.model_validate(value)

    def test_host_ocr_actual_sdk_rejects_missing_text_without_silent_invention(self):
        answer=self.host_transcript(); del answer['texts'][0]['text']
        report=self.prepare(coordinate_policy='host_ocr_v1',answer=answer)
        self.assertEqual(report['status'],'with_gaps')
        self.assertEqual(len(self.sent),2)
        self.assertEqual(report['gaps'][0]['code'],'ModelBehaviorError')
        self.assertFalse(list(self.output.glob('*/model-transcription.json')))
        self.assertFalse(list(self.output.glob('*/transcription.json')))

    def test_host_ocr_empty_text_collection_preserves_pending_semantic_acceptance(self):
        # Empty collections were legal in Figure (e.g. an image without any
        # printed text). Structural/OCR completion cannot establish coverage.
        answer=self.host_transcript(); answer.update(texts=[],series=[])
        report=self.prepare(coordinate_policy='host_ocr_v1',answer=answer)
        self.assertEqual(report['independent_acceptance'],'pending')
        item=report['figures'][0]
        final=FigureMaterialReader(self.output,self.fixture.dataset).read(item['figure_id'])['transcription']
        self.assertEqual(final['texts'],[])
        self.assertEqual(final['series'],[])

    def test_host_ocr_reader_rejects_repinned_policy_and_semantic_tampering(self):
        self.prepare(coordinate_policy='host_ocr_v1',answer=self.host_transcript())
        manifest_path=self.output/'manifest.json'
        original_manifest=manifest_path.read_bytes()
        import hashlib
        manifest=json.loads(original_manifest)
        config_path=self.output/'config.json'; original_config=config_path.read_bytes()
        for policy in ('unknown',None,'model_proposal'):
            config=json.loads(original_config); config['coordinate_policy']=policy
            config_path.write_text(json.dumps(config))
            manifest['files']['config.json']=hashlib.sha256(config_path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(manifest))
            with self.subTest(policy=policy),self.assertRaises(ValueError):
                FigureMaterialReader(self.output,self.fixture.dataset)
        config_path.write_bytes(original_config)
        manifest_path.write_bytes(original_manifest)
        model_path=next(self.output.glob('*/model-transcription.json'))
        model=json.loads(model_path.read_text()); model['texts'][1]['text']='$999'
        model_path.write_text(json.dumps(model))
        manifest=json.loads(original_manifest)
        manifest['files'][str(model_path.relative_to(self.output))]=hashlib.sha256(model_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'changed semantic model output'):
            FigureMaterialReader(self.output,self.fixture.dataset)

    def test_host_ocr_unmatched_text_never_becomes_final_evidence(self):
        answer = self.host_transcript(); answer['texts'][1]['text'] = '$999'
        report = self.prepare(coordinate_policy='host_ocr_v1', answer=answer)
        self.assertEqual(report['status'], 'with_gaps')
        self.assertEqual(report['gaps'][0]['code'], 'unresolved_text_coordinates')
        self.assertFalse(list(self.output.glob('*/transcription.json')))
        self.assertEqual(FigureMaterialReader(self.output,self.fixture.dataset).list(), [])
        self.assertEqual(len(self.sent), 1)

    def test_host_ocr_failure_preserves_model_output_without_claiming_grounding(self):
        report = self.prepare(coordinate_policy='host_ocr_v1', answer=self.host_transcript(),
                              ocr_effect=OSError('OCR unavailable'))
        self.assertEqual(report['gaps'][0]['code'], 'grounding_unavailable')
        self.assertTrue(list(self.output.glob('*/model-transcription.json')))
        self.assertFalse(list(self.output.glob('*/transcription.json')))

    def test_host_ocr_invalid_final_coordinates_still_fail_original_figure_schema(self):
        invalid = {'matches': {'legend': {'box':{'x0':100,'y0':50,'x1':1100,'y1':100}},
                    'tick':{'box':{'x0':100,'y0':250,'x1':500,'y1':300}}}, 'gaps':[]}
        with patch('uteki.infrastructure.document_sources.figure_grounding.locate_texts', return_value=invalid):
            report = self.prepare(coordinate_policy='host_ocr_v1', answer=self.host_transcript())
        self.assertEqual(report['gaps'][0]['code'], 'invalid_grounded_coordinates')
        self.assertFalse(list(self.output.glob('*/transcription.json')))

    def test_host_ocr_replay_uses_original_text_schema_and_keeps_final_reader_contract(self):
        self.prepare(coordinate_policy='host_ocr_v1', answer=self.host_transcript())
        replay = self.fixture.root/'replay'
        fixture_ocr = mock_ocr_process({0: tsv([
            ('Series',1,1,3,1,99,1), ('A',5,1,2,1,99,1), ('$100',1,5,4,1,99,2)])})
        with patch('uteki.infrastructure.document_sources.figure_grounding.shutil.which', return_value='/offline/tesseract'), \
             patch('uteki.infrastructure.document_sources.figure_grounding.subprocess.run', side_effect=fixture_ocr):
            report = reground_figure_preparation(self.fixture.dataset,self.output,replay)
        self.assertEqual(report['status'], 'prepared')
        self.assertEqual(len(self.sent), 1)
        reader = FigureMaterialReader(replay,self.fixture.dataset)
        Figure.model_validate(reader.read(report['figures'][0]['figure_id'])['transcription'])


if __name__ == '__main__':
    unittest.main()
