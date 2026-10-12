"""Generic image provenance/consumption and bounded runtime failure tests; no API."""
import asyncio
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from agents.exceptions import ModelBehaviorError
from pydantic import ValidationError

import tests.unit.test_figure_acquisition as acquisition_fixtures
from tests.unit.test_figure_grounding import mock_ocr_process, tsv
from uteki.agents.figure_materials import Figure, prepare_inputs, run_figure_preparation, reground_figure_preparation
from uteki.infrastructure.document_sources.figure_reader import FigureMaterialReader


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def text(identifier, role, words):
    return dict(id=identifier, role=role, text=words, box=dict(x0=10, y0=10, x1=300, y1=50))


def chart():
    return dict(kind='chart', texts=[text('legend', 'legend', 'Series A'), text('tick', 'y_tick', '$100')],
                series=[dict(legend_id='legend', color='blue')], printed_values=[],
                unreadable_regions=[], limitations=['No numeric observation labels are printed.'])


class FigureMaterialsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = acquisition_fixtures.FigureAcquisitionTests()
        self.fixture.setUp()
        self.dataset = self.fixture.dataset
        self.acquisition = self.fixture.output
        self.fixture.run_acquire()
        self.bundle = self.fixture.root / 'transcription'

    def tearDown(self):
        self.fixture.tearDown()

    def run_materials(self, *, effect=None, answer=None, output=None, model='claude-sonnet-5-5',
                      coordinate_policy='model_proposal'):
        runner = AsyncMock(side_effect=effect, return_value=SimpleNamespace(final_output=answer or chart()))
        fixture_ocr = mock_ocr_process({0: tsv([('Series', 1, 1, 3, 1, 99, 1), ('A', 5, 1, 2, 1, 99, 1), ('$100', 1, 5, 4, 1, 99, 2)])})
        with patch('uteki.agents.figure_materials.Runner.run', runner), patch('uteki.agents.figure_materials.load_provider_key'), patch('uteki.infrastructure.document_sources.figure_grounding.shutil.which', return_value='/offline/tesseract'), patch('uteki.infrastructure.document_sources.figure_grounding.subprocess.run', side_effect=fixture_ocr):
            result = asyncio.run(run_figure_preparation(self.dataset, self.acquisition, output or self.bundle,
                model=model, budget=None, credentials_root=self.fixture.root,
                coordinate_policy=coordinate_policy))
        return result, runner

    def test_host_coordinate_policy_is_provider_independent_and_legacy_default_stays_strict(self):
        from uteki.agents.figure_materials import FigureTranscription, HOST_OCR_PROMPT
        answer=chart()
        for entry in answer['texts']:
            del entry['box']
        report, runner=self.run_materials(answer=answer,coordinate_policy='host_ocr_v1')
        self.assertEqual(report['status'],'prepared')
        self.assertEqual(runner.call_args.args[0].instructions,HOST_OCR_PROMPT)
        self.assertEqual(runner.call_args.args[0].output_type.output_type,FigureTranscription)
        row=report['figures'][0]
        Figure.model_validate(FigureMaterialReader(self.bundle,self.dataset).read(row['figure_id'])['transcription'])

    def rewrite_bundle_file(self, relative, value):
        path = self.bundle / relative
        path.write_text(json.dumps(value))
        manifest_path = self.bundle / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['files'][relative] = sha(path.read_bytes())
        manifest_path.write_text(json.dumps(manifest))

    def test_chart_rejects_missing_duplicate_or_unbound_legend(self):
        for series in [[], [dict(legend_id='legend', color='blue')] * 2,
                       [dict(legend_id='other', color='blue')]]:
            value = chart(); value['series'] = series
            with self.subTest(series=series), self.assertRaises(ValidationError):
                Figure.model_validate(value)

    def test_nonchart_series_references_cannot_bypass_identity_contract(self):
        for kind in ('table', 'diagram', 'logo', 'other'):
            for series in ([dict(legend_id='unknown', color='blue')], chart()['series'] * 2):
                value = chart(); value.update(kind=kind, series=series)
                with self.subTest(kind=kind), self.assertRaises(ValidationError):
                    Figure.model_validate(value)

    def test_duplicate_text_and_ticks_cannot_be_observations(self):
        value = chart(); value['texts'].append(copy.deepcopy(value['texts'][0]))
        with self.assertRaises(ValidationError):
            Figure.model_validate(value)
        for field in ('tick', 'invented-label'):
            value = chart(); value['printed_values'] = [dict(text_id=field, series_legend_id='legend', period_text_id=None)]
            with self.assertRaises(ValidationError):
                Figure.model_validate(value)

    def test_printed_values_require_observation_and_bound_series_and_period(self):
        valid = chart()
        valid['texts'].extend([text('amount', 'data_value', '$120'), text('period', 'x_tick', '2025')])
        valid['printed_values'] = [dict(text_id='amount', series_legend_id='legend', period_text_id='period')]
        Figure.model_validate(valid)
        for overrides in [dict(series_legend_id='tick'), dict(period_text_id='legend'), dict(period_text_id='tick')]:
            value = copy.deepcopy(valid); value['printed_values'][0].update(overrides)
            with self.assertRaises(ValidationError):
                Figure.model_validate(value)
        value = copy.deepcopy(valid); value['printed_values'] = []
        with self.assertRaises(ValidationError):
            Figure.model_validate(value)

    def test_out_of_bounds_or_empty_box_rejected(self):
        for box in [dict(x0=10, x1=10, y0=10, y1=20), dict(x0=-1, x1=100, y0=10, y1=20)]:
            value = chart(); value['texts'][0]['box'] = box
            with self.assertRaises(ValidationError):
                Figure.model_validate(value)

    def test_complete_runtime_inventory_and_reader_preserve_all_source_locations(self):
        manifest, runner = self.run_materials()
        self.assertEqual(runner.await_count, 1)
        self.assertEqual(manifest['status'], 'prepared')
        self.assertEqual(manifest['independent_acceptance'], 'pending')
        reader = FigureMaterialReader(self.bundle, self.dataset)
        listing = reader.list()
        self.assertEqual(len(listing), 1)
        result = reader.read(listing[0]['figure_id'])
        self.assertEqual(len(result['locations']), 2)
        self.assertEqual(len(result['source_blocks']), 2)
        self.assertEqual(Path(result['original_image_path']).read_bytes(), acquisition_fixtures.png())
        expected = chart()
        expected['texts'][0]['box'] = dict(x0=100, y0=50, x1=700, y1=100)
        expected['texts'][1]['box'] = dict(x0=100, y0=250, x1=500, y1=300)
        self.assertEqual(result['transcription'], expected)
        self.assertEqual(result['company_id'], 'sec-0000000123')
        self.assertEqual(result['independent_acceptance'], 'pending')
        with self.assertRaisesRegex(ValueError, 'Unknown figure'):
            reader.read('another-company-figure')

    def test_local_output_error_has_bounded_revision_and_retained_failure(self):
        manifest, runner = self.run_materials(effect=[ModelBehaviorError('schema mismatch'), SimpleNamespace(final_output=chart())])
        self.assertEqual(runner.await_count, 2)
        self.assertEqual(manifest['status'], 'prepared')
        identifier = manifest['figures'][0]['figure_id']
        self.assertTrue((self.bundle / identifier / 'attempt-1/failure.json').exists())
        self.assertTrue((self.bundle / identifier / 'attempt-1/response.json').exists())
        amended = json.loads((self.bundle / identifier / 'attempt-2/input.json').read_text())
        self.assertEqual(amended['host_validation_feedback'], 'schema mismatch')
        self.assertIn(identifier + '/attempt-1/failure.json', manifest['files'])

    def test_network_failure_not_blindly_retried_and_partial_bundle_explicit(self):
        manifest, runner = self.run_materials(effect=RuntimeError('transport failed'))
        self.assertEqual(runner.await_count, 1)
        self.assertEqual(manifest['status'], 'with_gaps')
        self.assertEqual(manifest['figures'], [])
        self.assertEqual(manifest['gaps'][0]['code'], 'RuntimeError')
        self.assertEqual(FigureMaterialReader(self.bundle, self.dataset).list(), [])
        self.assertTrue(any(name.endswith('/response.json') for name in manifest['files']))

    def test_two_bad_outputs_stay_failed_not_marked_prepared(self):
        manifest, runner = self.run_materials(answer={'kind': 'chart'})
        self.assertEqual(runner.await_count, 2)
        self.assertEqual(manifest['status'], 'with_gaps')
        self.assertEqual(manifest['figures'], [])
        self.assertEqual(manifest['gaps'][0]['code'], 'ValidationError')

    def test_prepare_rejects_tampered_metadata_and_source_before_any_model_run(self):
        path = self.acquisition / 'manifest.json'
        original = json.loads(path.read_text())
        for field, replacement in [('width', 123), ('media_type', 'image/jpeg'), ('company_id', 'sec-0000000009')]:
            modified = copy.deepcopy(original); modified['figures'][0][field] = replacement
            path.write_text(json.dumps(modified))
            with self.subTest(field=field), self.assertRaises(ValueError):
                prepare_inputs(self.dataset, self.acquisition)
        path.write_text(json.dumps(original))
        frozen = self.acquisition / original['figures'][0]['artifact_path']
        frozen.write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError, 'integrity mismatch'):
            prepare_inputs(self.dataset, self.acquisition)

    def test_runtime_rejects_nested_output_and_invalid_model_before_directory_created(self):
        for output in (self.dataset / 'child', self.acquisition / 'child'):
            with self.assertRaises(ValueError):
                self.run_materials(output=output)
            self.assertFalse(output.exists())
        with self.assertRaises(ValueError):
            self.run_materials(model='unsupported-model')
        self.assertFalse(self.bundle.exists())

    def test_reader_detects_artifact_and_dataset_tamper_including_after_open(self):
        manifest, _ = self.run_materials()
        reader = FigureMaterialReader(self.bundle, self.dataset)
        row = manifest['figures'][0]
        path = self.bundle / row['transcription']
        old = path.read_bytes(); path.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            reader.read(row['figure_id'])
        path.write_bytes(old)
        dataset_file = self.dataset / 'sources/sample/report.html'
        dataset_file.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            reader.list()

    def test_reader_rejects_repinned_cross_source_context_or_image_metadata(self):
        manifest, _ = self.run_materials()
        source_path = manifest['figures'][0]['source']
        original = json.loads((self.bundle / source_path).read_text())
        for case in ('company', 'context', 'dimensions'):
            value = copy.deepcopy(original)
            if case == 'company':
                value['figure']['company_id'] = 'sec-0000000009'
            elif case == 'context':
                value['document_context'] = [{'block_id': 'invented', 'text': 'other document'}]
            else:
                value['figure']['width'] = 500
            self.rewrite_bundle_file(source_path, value)
            with self.subTest(case=case), self.assertRaises(ValueError):
                FigureMaterialReader(self.bundle, self.dataset)

    def test_reader_rejects_duplicate_unknown_or_missing_records_and_escape_path(self):
        manifest, _ = self.run_materials()
        path = self.bundle / 'manifest.json'
        for case in ('duplicate', 'unknown', 'missing', 'escape'):
            value = copy.deepcopy(manifest)
            if case == 'duplicate':
                value['figures'] *= 2
            elif case == 'unknown':
                value['figures'][0]['figure_id'] = 'wrong'
            elif case == 'missing':
                value['figures'] = []
            else:
                value['files']['../not-in-bundle'] = '0' * 64
            path.write_text(json.dumps(value))
            with self.subTest(case=case), self.assertRaises(ValueError):
                FigureMaterialReader(self.bundle, self.dataset)


    def test_reader_rejects_grounding_identity_box_hash_and_unresolved_results(self):
        manifest, _ = self.run_materials()
        # Latest binding contract is required even if the producing runtime version
        # is being updated concurrently by another implementation task.
        manifest['version'] = 'figure-materials-v3'
        (self.bundle / 'manifest.json').write_text(json.dumps(manifest))
        row = manifest['figures'][0]
        original = json.loads((self.bundle / row['grounding']).read_text())
        for case in ('image', 'missing', 'box', 'text', 'confidence', 'gap'):
            value = copy.deepcopy(original)
            if case == 'image':
                value['image_sha256'] = '0' * 64
            elif case == 'missing':
                del value['matches']['legend']
            elif case == 'box':
                value['matches']['legend']['box']['x0'] += 1
            elif case == 'text':
                value['matches']['legend']['text'] = 'Other series'
            elif case == 'confidence':
                value['matches']['legend']['confidence'] = 79
            else:
                value['gaps'] = [{'code': 'ocr_ambiguous', 'text_id': 'legend'}]
            self.rewrite_bundle_file(row['grounding'], value)
            with self.subTest(case=case), self.assertRaises(ValueError):
                FigureMaterialReader(self.bundle, self.dataset)

    def test_reader_replays_selected_words_from_pinned_tsv(self):
        manifest, _ = self.run_materials()
        row = manifest['figures'][0]
        relative = (Path(row['grounding']).parent / 'ocr-0.tsv').as_posix()
        path = self.bundle / relative
        path.write_text(path.read_text().replace('Series', 'Changed'))
        manifest['files'][relative] = sha(path.read_bytes())
        (self.bundle / 'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'absent from the pinned OCR'):
            FigureMaterialReader(self.bundle, self.dataset)

    def repin_ocr(self, row, number, words, *, append=False):
        relative = (Path(row['grounding']).parent / f'ocr-{number}.tsv').as_posix()
        path = self.bundle / relative
        changed = tsv(words)
        path.write_text(path.read_text() + changed.split('\n', 1)[1] if append else changed)
        manifest_path = self.bundle / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['files'][relative] = sha(path.read_bytes())
        manifest_path.write_text(json.dumps(manifest))

    def test_reader_rejects_resealed_multiple_locations_in_selected_ocr_run(self):
        manifest, _ = self.run_materials()
        row = manifest['figures'][0]
        self.repin_ocr(row, 0, [('Series', 1, 10, 3, 1, 99, 3), ('A', 5, 10, 2, 1, 99, 3)], append=True)
        with self.assertRaisesRegex(ValueError, 'ocr_ambiguous'):
            FigureMaterialReader(self.bundle, self.dataset)

    def test_reader_replays_other_angles_before_accepting_selected_location(self):
        manifest, _ = self.run_materials()
        row = manifest['figures'][0]
        # At +90 degrees this returns an original location y=12..13, far from
        # the selected zero-degree location y=1..2. The selected TSV is intact.
        self.repin_ocr(row, 8, [('Series A', 12, 3, 1, 6, 99, 1)])
        with self.assertRaisesRegex(ValueError, 'ocr_ambiguous'):
            FigureMaterialReader(self.bundle, self.dataset)

    def test_reader_accepts_same_physical_occurrence_across_angles_without_ocr(self):
        manifest, _ = self.run_materials()
        row = manifest['figures'][0]
        # A second angle confirms the same occurrence, with lower confidence.
        self.repin_ocr(row, 8, [('Series A', 1, 3, 1, 6, 98, 1)])
        with patch('uteki.infrastructure.document_sources.figure_grounding.subprocess.run') as process:
            result = FigureMaterialReader(self.bundle, self.dataset).read(row['figure_id'])
        process.assert_not_called()
        self.assertEqual(result['coordinate_status'], 'ocr_grounded')

    def test_reader_rejects_resealed_duplicate_identities_for_one_occurrence(self):
        manifest, _ = self.run_materials()
        row = manifest['figures'][0]
        model_path = (Path(row['transcription']).parent / 'model-transcription.json').as_posix()
        for relative in (row['transcription'], model_path):
            value = json.loads((self.bundle / relative).read_text())
            duplicate = copy.deepcopy(value['texts'][0]); duplicate['id'] = 'second-legend'
            value['texts'].append(duplicate)
            value['series'].append(dict(legend_id='second-legend', color='blue'))
            self.rewrite_bundle_file(relative, value)
        grounding = json.loads((self.bundle / row['grounding']).read_text())
        grounding['matches']['second-legend'] = copy.deepcopy(grounding['matches']['legend'])
        self.rewrite_bundle_file(row['grounding'], grounding)
        with self.assertRaisesRegex(ValueError, 'ocr_location_reused'):
            FigureMaterialReader(self.bundle, self.dataset)

    def test_legacy_v2_retains_explicit_weaker_selected_location_validation(self):
        manifest, _ = self.run_materials()
        row = manifest['figures'][0]
        self.repin_ocr(row, 8, [('Series A', 12, 3, 1, 6, 99, 1)])
        current = json.loads((self.bundle / 'manifest.json').read_text())
        current['version'] = 'figure-materials-v2'
        (self.bundle / 'manifest.json').write_text(json.dumps(current))
        result = FigureMaterialReader(self.bundle, self.dataset).read(row['figure_id'])
        self.assertEqual(result['coordinate_status'], 'ocr_grounded_legacy_no_required_image_hash')

    def test_reader_rejects_fact_changes_between_model_and_grounded_artifact(self):
        manifest, _ = self.run_materials()
        row = manifest['figures'][0]
        model_path = (Path(row['transcription']).parent / 'model-transcription.json').as_posix()
        model = json.loads((self.bundle / model_path).read_text())
        model['limitations'] = ['An altered interpretation']
        self.rewrite_bundle_file(model_path, model)
        with self.assertRaisesRegex(ValueError, 'changed semantic model output'):
            FigureMaterialReader(self.bundle, self.dataset)

    def test_legacy_bundles_remain_explicitly_weaker(self):
        manifest, _ = self.run_materials()
        row = manifest['figures'][0]
        path = self.bundle / 'manifest.json'
        # v1 is protocol-only. It cannot acquire a verified coordinate label.
        legacy = copy.deepcopy(manifest)
        legacy['version'] = 'figure-materials-v1'
        legacy['figures'][0]['status'] = 'protocol_validated'
        path.write_text(json.dumps(legacy))
        reader = FigureMaterialReader(self.bundle, self.dataset)
        self.assertEqual(reader.read(row['figure_id'])['coordinate_status'], 'unverified_model_coordinates')
        # v2 historically did not pin the original hash inside its grounding report.
        legacy = copy.deepcopy(manifest); legacy['version'] = 'figure-materials-v2'
        path.write_text(json.dumps(legacy))
        grounding = json.loads((self.bundle / row['grounding']).read_text())
        grounding.pop('image_sha256')
        self.rewrite_bundle_file(row['grounding'], grounding)
        reader = FigureMaterialReader(self.bundle, self.dataset)
        self.assertEqual(reader.read(row['figure_id'])['coordinate_status'], 'ocr_grounded_legacy_no_required_image_hash')
        current = json.loads(path.read_text()); current['version'] = 'figure-materials-v3'
        path.write_text(json.dumps(current))
        with self.assertRaisesRegex(ValueError, 'grounding contract'):
            FigureMaterialReader(self.bundle, self.dataset)

    def test_invalid_grounded_coordinates_record_gap_instead_of_aborting_manifest(self):
        bad = {'gaps': [], 'matches': {key: {'box': dict(x0=10, y0=10, x1=10, y1=30)} for key in ('legend', 'tick')}}
        with patch('uteki.infrastructure.document_sources.figure_grounding.locate_texts', return_value=bad):
            manifest, runner = self.run_materials()
        self.assertEqual(runner.await_count, 1)
        self.assertEqual(manifest['status'], 'with_gaps')
        self.assertEqual(manifest['figures'], [])
        self.assertEqual(manifest['gaps'][0]['code'], 'invalid_grounded_coordinates')
        self.assertTrue((self.bundle / 'manifest.json').exists())
        self.assertTrue(any(name.endswith('/grounding-error.json') for name in manifest['files']))

    def test_coordinate_replay_preserves_frozen_prior_and_never_runs_model(self):
        manifest, _ = self.run_materials()
        before = {str(path.relative_to(self.bundle)): path.read_bytes() for path in self.bundle.rglob('*') if path.is_file()}
        replay = self.fixture.root / 'replayed'
        fixture_ocr = mock_ocr_process({0: tsv([('Series', 1, 1, 3, 1, 99, 1), ('A', 5, 1, 2, 1, 99, 1), ('$100', 1, 5, 4, 1, 99, 2)])})
        with patch('uteki.agents.figure_materials.Runner.run') as model, patch('uteki.infrastructure.document_sources.figure_grounding.shutil.which', return_value='/offline/tesseract'), patch('uteki.infrastructure.document_sources.figure_grounding.subprocess.run', side_effect=fixture_ocr):
            result = reground_figure_preparation(self.dataset, self.bundle, replay)
        model.assert_not_called()
        self.assertEqual(result['status'], 'prepared')
        self.assertEqual(result['stage'], 'deterministic_coordinate_replay')
        self.assertEqual(before, {str(path.relative_to(self.bundle)): path.read_bytes() for path in self.bundle.rglob('*') if path.is_file()})
        self.assertEqual((replay / 'prior/manifest.json').read_bytes(), before['manifest.json'])
        identifier = manifest['figures'][0]['figure_id']
        current = FigureMaterialReader(replay, self.dataset).read(identifier)
        previous = FigureMaterialReader(self.bundle, self.dataset).read(identifier)
        self.assertEqual(current['transcription'], previous['transcription'])
        self.assertEqual(current['image_sha256'], previous['image_sha256'])


if __name__ == '__main__':
    unittest.main()
