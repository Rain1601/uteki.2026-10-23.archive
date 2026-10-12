import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from PIL import Image
from uteki.infrastructure.document_sources.figure_acquisition import (
    acquire_figures, discover_figures, inspect_image, _scoped_url,
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def png():
    out = BytesIO()
    Image.new('RGB', (10, 20), 'white').save(out, format='PNG')
    return out.getvalue()


class FigureAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dataset = self.root / 'dataset'
        self.dataset.mkdir()
        self.raw = b'<html><body><div><img src="chart.png"></div><div><img src="chart.png"></div></body></html>'
        self.url = 'https://www.sec.gov/Archives/edgar/data/123/000000012325000001/report.htm'
        self.image_url = self.url.rsplit('/', 1)[0] + '/chart.png'
        self.make_dataset()
        self.output = self.root / 'output'

    def tearDown(self):
        self.tmp.cleanup()

    def make_dataset(self):
        folder = self.dataset / 'sources' / 'sample'
        folder.mkdir(parents=True, exist_ok=True)
        artifacts = {
            'report.html': self.raw,
            'assets.json': json.dumps({'assets': [
                dict(asset_id=f'asset-{n}', source_path='chart.png', source_url=self.image_url,
                     dom_path=f'/html/body/div[{n}]/img', alt='chart') for n in (1, 2)]}).encode(),
            'blocks.jsonl': b'\n'.join(json.dumps(dict(block_id=f'block-{n}', image_asset_id=f'asset-{n}',
                 dom_path=f'/html/body/div[{n}]/img', type='image')).encode() for n in (1, 2)),
        }
        artifacts['manifest.json'] = json.dumps({'source_sha256': sha(self.raw),
            'artifacts': {k: {'sha256': sha(v)} for k, v in artifacts.items()}}).encode()
        for name, content in artifacts.items():
            (folder / name).write_bytes(content)
        sources = [dict(source_snapshot_id='sample', company_id='sec-0000000123',
             source_url=self.url, source_sha256=sha(self.raw), raw_file_sha256=sha(self.raw),
             raw_file='sources/sample/report.html', index_folder='sources/sample')]
        (self.dataset / 'sources.json').write_text(json.dumps(sources))
        self.repin()

    def repin(self):
        files = {str(p.relative_to(self.dataset)): sha(p.read_bytes())
                 for p in self.dataset.rglob('*') if p.is_file() and p != self.dataset / 'manifest.json'}
        (self.dataset / 'manifest.json').write_text(json.dumps({'files': files}))

    def run_acquire(self, fetch=None, **kwargs):
        return acquire_figures(self.dataset, self.output, user_agent='Test test@example.com',
                               fetch=fetch or (lambda *a, **k: png()), **kwargs)

    def test_repeated_image_fetched_once_retains_two_locators_and_input_unchanged(self):
        before = {str(p): p.read_bytes() for p in self.dataset.rglob('*') if p.is_file()}
        called = []
        def fetch(url, **kwargs):
            called.append(url)
            return png()
        result = self.run_acquire(fetch)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(called, [self.image_url])
        image = result['figures'][0]
        self.assertEqual(len(image['locations']), 2)
        self.assertEqual((image['width'], image['height']), (10, 20))
        self.assertEqual(image['media_type'], 'image/png')
        self.assertEqual(sha((self.output / image['artifact_path']).read_bytes()), image['sha256'])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.dataset.rglob('*') if p.is_file()})

    def test_child_manifest_and_assets_tamper_rejected_by_top_level_pin(self):
        folder = self.dataset / 'sources/sample'
        raw = json.dumps({'assets': []}).encode()
        (folder / 'assets.json').write_bytes(raw)
        manifest = json.loads((folder / 'manifest.json').read_text())
        manifest['artifacts']['assets.json']['sha256'] = sha(raw)
        (folder / 'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'dataset artifact hash mismatch'):
            self.run_acquire()
        self.assertFalse(self.output.exists())

    def test_input_original_tamper_rejected_before_network(self):
        (self.dataset / 'sources/sample/report.html').write_bytes(b'bad')
        with self.assertRaises(ValueError):
            self.run_acquire()

    def test_cross_accession_cross_origin_traversal_blocked(self):
        for value in ('https://evil.example/chart.png', '../chart.png', '%2e%2e/chart.png',
                      '/Archives/edgar/data/123/other/chart.png', 'data:image/png;base64,eA=='):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _scoped_url(value, self.url)

    def test_locator_points_at_wrong_raw_element_rejected(self):
        folder = self.dataset / 'sources/sample'
        assets = json.loads((folder / 'assets.json').read_text())
        assets['assets'][0]['dom_path'] = '/html/body/div[1]'
        raw = json.dumps(assets).encode()
        (folder / 'assets.json').write_bytes(raw)
        manifest = json.loads((folder / 'manifest.json').read_text())
        manifest['artifacts']['assets.json']['sha256'] = sha(raw)
        (folder / 'manifest.json').write_text(json.dumps(manifest))
        self.repin()
        with self.assertRaisesRegex(ValueError, 'locator'):
            self.run_acquire()

    def test_bad_image_bytes_are_frozen_as_failed_receipt(self):
        result = self.run_acquire(lambda *a, **k: b'<html>not image</html>')
        self.assertEqual(result['status'], 'with_gaps')
        self.assertEqual(result['requests'], 1)
        figure = result['figures'][0]
        self.assertEqual(figure['status'], 'failed')
        self.assertTrue((self.output / figure['artifact_path']).exists())
        self.assertIn('failed', (self.output / 'requests.jsonl').read_text())

    def test_bounded_transient_retry_preserves_both_attempts(self):
        calls = []
        def fetch(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                raise TimeoutError()
            return png()
        with patch('uteki.infrastructure.document_sources.figure_acquisition.time.sleep'):
            result = self.run_acquire(fetch)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['requests'], 2)
        events = [json.loads(s) for s in (self.output / 'requests.jsonl').read_text().splitlines()]
        self.assertEqual([e['status'] for e in events], ['request_started','failed','request_started','fetched'])

    def test_retry_after_deferred_no_duplicate_request(self):
        def fetch(*a, **k):
            raise urllib.error.HTTPError(self.image_url, 429, 'wait', {'Retry-After': '120'}, None)
        result = self.run_acquire(fetch)
        self.assertEqual(result['requests'], 1)
        self.assertEqual(result['status'], 'with_gaps')
        self.assertIn('deferred', (self.output / 'requests.jsonl').read_text())

    def test_permanent_access_failure_no_retry(self):
        def fetch(*a, **k):
            raise urllib.error.HTTPError(self.image_url, 403, 'deny', {}, None)
        self.assertEqual(self.run_acquire(fetch)['requests'], 1)

    def test_oversize_does_not_retry(self):
        result = self.run_acquire(limits={'max_bytes_per_image': 5})
        self.assertEqual(result['requests'], 1)
        self.assertEqual(result['status'], 'with_gaps')

    def test_pixel_limit_decoding_failure(self):
        result = self.run_acquire(limits={'max_pixels': 10})
        self.assertEqual(result['status'], 'with_gaps')
        self.assertEqual(result['gaps'][0]['code'], 'image_pixel_limit')

    def test_existing_output_never_overwritten(self):
        self.output.mkdir()
        (self.output / 'keep').write_text('old')
        with self.assertRaises(FileExistsError):
            self.run_acquire()
        self.assertEqual((self.output / 'keep').read_text(), 'old')

    def test_output_cannot_be_inside_dataset(self):
        self.output = self.dataset / 'new'
        with self.assertRaisesRegex(ValueError, 'must not modify'):
            self.run_acquire()

    def test_no_images_is_valid_zero_requests(self):
        self.raw = b'<html><body><p>No images</p></body></html>'
        self.make_dataset()
        folder = self.dataset / 'sources/sample'
        for name, raw in [('assets.json', b'{"assets":[]}'), ('blocks.jsonl', b'')]:
            (folder / name).write_bytes(raw)
        m = json.loads((folder / 'manifest.json').read_text())
        for name in ('assets.json', 'blocks.jsonl'):
            m['artifacts'][name]['sha256'] = sha((folder / name).read_bytes())
        (folder / 'manifest.json').write_text(json.dumps(m))
        self.repin()
        result = self.run_acquire()
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['requests'], 0)

    def test_unsupported_animated_image_explicit_gap(self):
        buffer = BytesIO()
        Image.new('RGB', (4, 4), 'red').save(buffer, format='GIF', save_all=True,
                    append_images=[Image.new('RGB', (4, 4), 'blue')])
        with self.assertRaisesRegex(ValueError, 'animated_image'):
            inspect_image(buffer.getvalue(), 100)

    def test_missing_repeated_occurrence_is_gap_even_if_one_locator_survives(self):
        folder = self.dataset / 'sources/sample'
        assets = json.loads((folder / 'assets.json').read_text())
        assets['assets'] = assets['assets'][:1]
        content = json.dumps(assets).encode()
        (folder / 'assets.json').write_bytes(content)
        m = json.loads((folder / 'manifest.json').read_text())
        m['artifacts']['assets.json']['sha256'] = sha(content)
        (folder / 'manifest.json').write_text(json.dumps(m))
        self.repin()
        result = self.run_acquire()
        self.assertEqual(result['status'], 'with_gaps')
        self.assertIn('image_occurrence_coverage_mismatch', [g['code'] for g in result['gaps']])

    def test_unrelated_company_same_generic_protocol(self):
        self.url = 'https://www.sec.gov/Archives/edgar/data/987/000000098725000041/another.htm'
        self.image_url = self.url.rsplit('/', 1)[0] + '/chart.png'
        self.make_dataset()
        sources = json.loads((self.dataset / 'sources.json').read_text())
        sources[0]['company_id'] = 'sec-0000000987'
        (self.dataset / 'sources.json').write_text(json.dumps(sources))
        self.repin()
        result = self.run_acquire()
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['figures'][0]['source_url'], self.image_url)

    def test_unknown_proxy_host_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'SEC hostnames'):
            self.run_acquire(transport={'mode': 'trusted_local_http_proxy',
                'proxy_url': 'http://127.0.0.1:7890', 'destination_hosts': ['example.com']})

    def test_unsupported_visual_resources_remain_explicit_gaps(self):
        base = self.raw
        examples = [
            (b'<svg><rect width="10" height="10"/></svg>', 'unsupported_graphic_type'),
            (b'<object data="figure.pdf"></object>', 'unsupported_graphic_type'),
            (b'<embed src="figure.pdf">', 'unsupported_graphic_type'),
            (b'<picture><source srcset="figure2.png 2x"></picture>', 'unsupported_graphic_type'),
            (b'<canvas width="10" height="10"></canvas>', 'unsupported_graphic_type'),
            (b'<div style="background-image:url(chart.png)"></div>', 'unprocessed_css_resource'),
            (b'<style>.figure{background:image-set(url(chart.png) 1x)}</style>', 'unprocessed_css_resource'),
            (b'<style>@import "figures.css";</style>', 'unprocessed_css_resource'),
            (b'<link rel="StyleSheet" href="figures.css">', 'unprocessed_external_stylesheet'),
            (b'<svg hidden style="display:none"></svg>', 'unsupported_graphic_type'),
        ]
        for ordinal, (markup, expected_code) in enumerate(examples):
            with self.subTest(markup=markup):
                self.raw = base.replace(b'</body>', markup + b'</body>')
                self.make_dataset()
                self.output = self.root / ('unsupported-' + str(ordinal))
                result = self.run_acquire()
                self.assertEqual(result['status'], 'with_gaps')
                self.assertIn(expected_code, [row['code'] for row in result['gaps']])
                self.assertTrue(all('source_snapshot_id' in row for row in result['gaps']))

    def test_img_srcset_cannot_fall_back_to_src(self):
        self.raw = self.raw.replace(b'<img src="chart.png">',
                                    b'<img src="chart.png" srcset="other.png 2x">', 1)
        self.make_dataset()
        result = self.run_acquire()
        self.assertEqual(result['status'], 'with_gaps')
        self.assertEqual(result['requests'], 0)
        self.assertEqual(result['sources'][0]['discovery_status'], 'unsupported')
        self.assertIn('unsupported_image_source_contract', [row['code'] for row in result['gaps']])
        self.assertIn('srcset', [row.get('kind') for row in result['gaps']])

    def test_known_sec_tracking_pixel_exception_unchanged(self):
        pixel = (b'<noscript><img src="https://www.sec.gov/akam/13/pixel_3f5f58ec?a=QQ==" '
                 b'style="visibility:hidden;position:absolute;left:-999px;top:-999px;"></noscript>')
        self.raw = self.raw.replace(b'</body>', pixel + b'</body>')
        self.make_dataset()
        result = self.run_acquire()
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['sources'][0]['raw_image_reference_count'], 3)
        self.assertEqual(result['sources'][0]['unique_image_count'], 1)
        self.assertEqual(result['sources'][0]['excluded_references'][0]['reason'],
                         'sec_akamai_noscript_tracking_pixel')
        self.assertEqual(result['requests'], 1)

    def test_invalid_limits_rejected(self):
        for value in ({'retries': 2}, {'max_images': True}, {'bad': 1}, {'max_total_bytes': 0}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.run_acquire(limits=value)
