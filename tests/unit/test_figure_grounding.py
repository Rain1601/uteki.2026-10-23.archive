"""OCR-location mechanics use frozen synthetic TSVs, never a local OCR process."""
from io import BytesIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
from uteki.infrastructure.document_sources.figure_grounding import locate_texts, original_box, ANGLES

HEADER = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'


def tsv(words):
    """words: (text, left, top, width, height, confidence, line)."""
    return HEADER + ''.join(f'5\t1\t1\t1\t{line}\t{n}\t{x}\t{y}\t{w}\t{h}\t{confidence}\t{text}\n'
        for n, (text, x, y, w, h, confidence, line) in enumerate(words, 1))


def mock_ocr_process(tsv_by_number):
    def execute(args, **kwargs):
        if args[-1] == '--version':
            return SimpleNamespace(stdout='tesseract offline-fixture\n')
        number = int(Path(args[1]).stem.split('-')[-1])
        return SimpleNamespace(stdout=tsv_by_number.get(number, HEADER))
    return execute


class FigureGroundingTests(unittest.TestCase):
    def run_fixture(self, texts, words):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            image = folder / 'image.png'
            Image.new('RGB', (100, 200), 'white').save(image)
            with patch('uteki.infrastructure.document_sources.figure_grounding.shutil.which', return_value='/offline/tesseract'), \
                 patch('uteki.infrastructure.document_sources.figure_grounding.subprocess.run', side_effect=mock_ocr_process({0: tsv(words)})) as process:
                report = locate_texts(image, texts, folder / 'grounding')
            self.assertEqual(process.call_count, len(ANGLES) + 1)
            self.assertTrue(all((folder / 'grounding' / run['tsv']).is_file() for run in report['runs']))
            self.assertEqual(json.loads((folder / 'grounding/grounding.json').read_text()), json.loads(json.dumps(report)))
            return report

    def test_inverse_transform_zero_and_quarter_turn(self):
        self.assertEqual(original_box((10, 20, 30, 40), 0, (100, 200), (100, 200)),
                         dict(x0=100, y0=100, x1=300, y1=200))
        # PIL's counter-clockwise rotation: original rectangle x=10..30,y=20..40
        # becomes x=20..40,y=70..90 on a 200x100 canvas.
        transformed = original_box((20, 70, 40, 90), 90, (200, 100), (100, 200))
        for key, expected in dict(x0=100, y0=100, x1=300, y1=200).items():
            self.assertLessEqual(abs(transformed[key] - expected), 1)

    def test_exact_contiguous_words_get_source_coordinates_not_model_box(self):
        texts = [{'id': 'series', 'text': 'Series A', 'box': dict(x0=0, y0=0, x1=1000, y1=1000)}]
        report = self.run_fixture(texts, [('Series', 10, 20, 20, 10, 95, 1), ('A', 35, 20, 10, 10, 92, 1)])
        self.assertEqual(report['status'], 'grounded')
        self.assertEqual(report['matches']['series']['box'], dict(x0=100, y0=100, x1=450, y1=150))
        self.assertEqual(report['matches']['series']['confidence'], 92)
        self.assertEqual(len(report['image_sha256']), 64)

    def test_missing_low_confidence_and_inexact_text_have_no_fallback(self):
        for words in [[], [('Other', 10, 20, 20, 10, 99, 1)], [('Wanted', 10, 20, 20, 10, 79, 1)], [('Wanted', 10, 20, 20, 10, 'nan', 1)], [('Wanted', 10, 20, 20, 10, 101, 1)]]:
            report = self.run_fixture([{'id': 't', 'text': 'Wanted', 'box': {}}], words)
            self.assertEqual(report['status'], 'with_gaps')
            self.assertEqual(report['matches'], {})
            self.assertEqual(report['gaps'][0]['code'], 'ocr_missing')

    def test_same_word_at_distinct_locations_is_ambiguous(self):
        report = self.run_fixture([{'id': 't', 'text': '100'}],
            [('100', 10, 20, 20, 10, 99, 1), ('100', 10, 100, 20, 10, 99, 2)])
        self.assertEqual(report['matches'], {})
        self.assertEqual(report['gaps'][0]['code'], 'ocr_ambiguous')

    def test_close_repeated_short_labels_need_overlap_not_only_near_centers(self):
        # Centers differ by only 20/1000, below the 25/1000 proximity threshold.
        # Their actual source rectangles do not overlap and are two occurrences.
        report = self.run_fixture([{'id': 't', 'text': '1'}],
            [('1', 10, 20, 1, 10, 99, 1), ('1', 12, 20, 1, 10, 99, 1)])
        self.assertEqual(report['matches'], {})
        self.assertEqual(report['gaps'][0]['code'], 'ocr_ambiguous')
        self.assertEqual(report['gaps'][0]['locations'], 2)

    def test_same_location_cannot_authorize_duplicate_model_texts(self):
        report = self.run_fixture([{'id': 'a', 'text': 'Same'}, {'id': 'b', 'text': 'Same'}],
            [('Same', 10, 20, 20, 10, 99, 1)])
        self.assertEqual(report['matches'], {})
        self.assertEqual({gap['code'] for gap in report['gaps']}, {'ocr_location_reused'})


if __name__ == '__main__':
    unittest.main()
