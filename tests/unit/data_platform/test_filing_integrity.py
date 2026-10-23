"""Independent synthetic issuers; no network or financial expected answers."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from uteki.data_platform.connectors.filing_integrity import atomic_write_new, validate_sec_filing


def filing(cik='0000098765', form='20-F', period='2031-12-31', *, duplicate='', title='Annual report', date_format=''):
    return f'''<!DOCTYPE html><html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:dei="http://xbrl.sec.gov/dei/2031"><head><title>{title}</title></head><body>
      <ix:nonNumeric name="dei:EntityCentralIndexKey" contextRef="c">{cik}</ix:nonNumeric>
      <ix:nonNumeric name="dei:DocumentType" contextRef="c">{form}</ix:nonNumeric>
      <ix:nonNumeric name="dei:DocumentPeriodEndDate" contextRef="c" {date_format}>{period}</ix:nonNumeric>
      {duplicate}<p>Synthetic issuer report. No financial answer values.</p></body></html>'''.encode()


class FilingIdentityTests(unittest.TestCase):
    def check(self, raw, **kwargs):
        return validate_sec_filing(raw, kwargs.get('cik', '0000098765'), kwargs.get('form', '20-F'), kwargs.get('period', '2031-12-31'))

    def test_two_independent_issuers_forms_and_fiscal_calendars(self):
        for cik, form, period in [('0000098765', '20-F', '2031-12-31'), ('12345', '10-K', '2031-12-27')]:
            result = self.check(filing(cik, form, period), cik=cik, form=form, period=period)
            self.assertEqual(result['cik'], cik.zfill(10))
            self.assertEqual(result['period_end'], period)
            self.assertEqual(result['financial_semantics'], 'not_evaluated')
            self.assertEqual(result['validation_version'], 'sec-inline-identity-v1')

    def test_mismatched_company_period_and_form(self):
        for raw in (filing(cik='55555'), filing(form='10-K'), filing(period='2031-06-30')):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'identity_mismatch'):
                self.check(raw)

    def test_missing_and_conflicting_duplicate_identity(self):
        missing = filing().replace(b'dei:DocumentType', b'dei:OtherConcept')
        with self.assertRaisesRegex(ValueError, 'missing_inline'):
            self.check(missing)
        for key, text in [('EntityCentralIndexKey', '1111'), ('DocumentType', '10-Q'), ('DocumentPeriodEndDate', '2031-01-01')]:
            duplicate = f'<ix:nonNumeric name="dei:{key}">{text}</ix:nonNumeric>'
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'identity_mismatch'):
                self.check(filing(duplicate=duplicate))

    def test_duplicate_equal_values_are_preserved(self):
        result = self.check(filing(duplicate='<ix:nonNumeric name="dei:EntityCentralIndexKey">98765</ix:nonNumeric>'))
        self.assertEqual(len(result['evidence']['entitycentralindexkey']), 2)

    def test_wrong_namespace_cannot_spoof_dei(self):
        for raw in (filing().replace(b'xbrl.sec.gov/dei', b'example.test/dei'),
                    filing().replace(b'www.xbrl.org/2013/inlineXBRL', b'example.test/inlineXBRL')):
            with self.assertRaisesRegex(ValueError, 'missing_inline'):
                self.check(raw)

    def test_pdf_error_challenge_and_truncation_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unsupported_pdf'):
            self.check(b'%PDF-1.7\n%%EOF')
        for title in ('SEC | Request Rate Threshold Exceeded', 'Access Denied', 'Just a moment...', 'Verify you are human'):
            with self.subTest(title=title), self.assertRaisesRegex(ValueError, 'challenge'):
                self.check(filing(title=title))
        for raw in (filing()[:-7], filing().replace(b'</body>', b''),
                    filing()[:-14] + b'<!-- </body></html> -->'):
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                self.check(raw)
        with self.assertRaisesRegex(ValueError, 'missing_inline'):
            self.check(b'<html><body>HTTP 200: Request failed</body></html>')

    def test_transformed_english_and_numeric_dates(self):
        for raw_date, transform in [('December 31, 2031', 'ixt:datemonthdayyearen'),
                                    ('Dec. 31, 2031', 'ixt:date-monthname-day-year-en'),
                                    ('12/31/2031', 'ixt:date-month-day-year')]:
            result = self.check(filing(period=raw_date, date_format=f'format="{transform}"'))
            self.assertEqual(result['period_end'], '2031-12-31')
        with self.assertRaisesRegex(ValueError, 'unsupported_inline_date'):
            self.check(filing(period='12/31/2031'))
        with self.assertRaisesRegex(ValueError, 'unsupported_inline_date'):
            self.check(filing(date_format='format="ixt:unknown-transform"'))

    def test_missing_invalid_expected_scope(self):
        for cik, form, period in [(None, '20-F', '2031-12-31'), (True, '20-F', '2031-12-31'),
                                  ('98765', '', '2031-12-31'), ('98765', [], '2031-12-31'),
                                  ('98765', '20-F', '2031-02-30')]:
            with self.subTest(cik=cik, form=form, period=period), self.assertRaises(ValueError):
                self.check(filing(), cik=cik, form=form, period=period)


class AtomicArtifactTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.path = self.root / 'objects/report.bin'

    def test_create_equal_reuse_and_different_bytes_rejected(self):
        self.assertEqual(atomic_write_new(self.path, b'complete'), 'created')
        self.assertEqual(atomic_write_new(self.path, b'complete'), 'reused')
        with self.assertRaisesRegex(ValueError, 'conflict'):
            atomic_write_new(self.path, b'different')
        self.assertEqual(self.path.read_bytes(), b'complete')
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_symlink_target_and_parent_rejected(self):
        other = self.root / 'other'
        other.write_bytes(b'original')
        self.path.parent.mkdir()
        self.path.symlink_to(other)
        with self.assertRaises(ValueError):
            atomic_write_new(self.path, b'original')
        alias = self.root / 'alias'
        alias.symlink_to(self.path.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            atomic_write_new(alias / 'new.bin', b'data')
        self.assertFalse((self.path.parent / 'new.bin').exists())
        self.assertEqual(other.read_bytes(), b'original')

    def test_interrupted_write_does_not_publish_and_retry_succeeds(self):
        with patch('uteki.data_platform.connectors.filing_integrity.os.fsync', side_effect=OSError('disk failure')):
            with self.assertRaises(ValueError):
                atomic_write_new(self.path, b'complete')
        self.assertFalse(self.path.exists())
        self.assertEqual(list(self.path.parent.iterdir()), [])
        residue = self.path.parent / '.report.bin.crashed.tmp'
        residue.write_bytes(b'partial old temporary data')
        self.assertEqual(atomic_write_new(self.path, b'complete'), 'created')
        self.assertEqual(self.path.read_bytes(), b'complete')
        self.assertEqual(residue.read_bytes(), b'partial old temporary data')

    def test_concurrent_identical_publish_never_overwrites(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(lambda _: atomic_write_new(self.path, b'complete'), range(4)))
        self.assertEqual(outcomes.count('created'), 1)
        self.assertEqual(outcomes.count('reused'), 3)
        self.assertEqual(self.path.read_bytes(), b'complete')


if __name__ == '__main__':
    unittest.main()
