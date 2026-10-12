"""Version gates protect both direct parsing and the legacy index entry point."""
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from uteki.infrastructure.document_sources.index_artifacts import build_index_artifacts
from uteki.infrastructure.document_sources.sec_index import parse_sec_source


RAW = b'<html><body><p>Source <span id="amount">17</span></p><p>Following</p></body></html>'


class SecParserVersionTests(unittest.TestCase):
    def test_direct_parser_rejects_unknown_blank_and_nonstring_versions(self):
        for version in ('sec-source-blocks-v0.1.14', 'future', '', ' ', None, []):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, '^unsupported SEC parser version$'):
                parse_sec_source('independent', 'https://example.invalid/report', RAW, parser_version=version)

    def test_existing_version_inventory_and_quarterly_default_are_retained(self):
        # Observed identities in frozen inputs, scripts, source and legacy tests.
        versions = ('sec-source-blocks-v0.1.1', 'sec-source-blocks-v0.1.2-quarterly',
            'sec-source-blocks-v0.1.3', 'sec-source-blocks-v0.1.3-quarterly',
            'sec-source-blocks-v0.1.4-quarterly', 'sec-source-blocks-v0.1.5',
            'sec-source-blocks-v0.1.6', 'sec-source-blocks-v0.1.7', 'sec-source-blocks-v0.1.8',
            'sec-source-blocks-v0.1.9', 'sec-source-blocks-v0.1.10', 'sec-source-blocks-v0.1.11', 'sec-source-blocks-v0.1.12', 'sec-source-blocks-v0.1.13')
        for version in versions:
            with self.subTest(version=version):
                parsed = parse_sec_source('independent', 'https://example.invalid/report', RAW, parser_version=version)
                self.assertEqual(parsed.parser_version, version)
                self.assertEqual([b.text for b in parsed.blocks], ['Source 17', 'Following'])
        quarterly = parse_sec_source('independent', 'https://example.invalid/report', RAW, form_type='10-Q')
        self.assertEqual(quarterly.parser_version, 'sec-source-blocks-v0.1.4-quarterly')

    def test_legacy_builder_rejects_unknown_or_blank_without_publishing_and_keeps_omission(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root/'source'
            source.mkdir()
            (source/'manifest.json').write_text(json.dumps({'document_id':'independent',
                'source_url':'https://example.invalid/report', 'source_snapshot_id':'independent-snapshot',
                'form':'10-K', 'content_sha256':hashlib.sha256(RAW).hexdigest()}))
            (source/'source.html.gz').write_bytes(gzip.compress(RAW))
            for number,version in enumerate(('sec-source-blocks-v0.1.14','future','',' ')):
                output = root/f'rejected-{number}'
                with self.subTest(version=version), self.assertRaisesRegex(ValueError, '^unsupported SEC parser version$'):
                    build_index_artifacts(source, output, parser_version=version)
                self.assertFalse(output.exists())
            default = build_index_artifacts(source, root/'default')
            self.assertEqual(default['parser_version'], 'sec-source-blocks-v0.1.1')
            for version in ('sec-source-blocks-v0.1.7','sec-source-blocks-v0.1.8'):
                result = build_index_artifacts(source, root/version, parser_version=version)
                self.assertEqual(result['parser_version'], version)


if __name__ == '__main__':
    unittest.main()
