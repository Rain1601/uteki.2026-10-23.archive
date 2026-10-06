"""Registered aliases select reviewed profiles; no network or company inference."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from uteki.infrastructure.document_sources.company_registry import CATALOG_VERSION, resolve_company_profile


class CompanyRegistryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.path = self.root / 'catalog.json'
        self.configs, self.entries = [], []
        for symbol, cik, market, form, end, aliases in [
            ('ACME', '0000000123', 'NASDAQ', '10-K', '2024-12-28', ['ACME', 'Acme Devices']),
            ('OTHER', '0000000456', 'NYSE', '20-F', '2024-09-30', ['OTHER', 'Other Foundry']),
        ]:
            config = {'symbol': symbol, 'cik': cik, 'market': market, 'as_of': '2025-06-30',
                'filing_selection': {'mode': 'annual_filing_period', 'annual_form': form, 'report_period_end': end},
                'source_policy': {'official': [], 'third_party': []}, 'limits': {'max_documents': 3},
                'document_validation': 'sec_inline_identity_v1', 'download_policy': 'reuse_verified'}
            filename = symbol.lower() + '.json'
            self.configs.append(config)
            self.entries.append({'company_id': 'sec-' + cik, 'cik': cik, 'symbol': symbol, 'market': market,
                'aliases': aliases, 'profile': {'filename': filename, 'sha256': self.write_profile(filename, config)}})
        self.write_catalog()

    def write_profile(self, filename, config):
        raw = (json.dumps(config, ensure_ascii=False, indent=2) + '\n').encode()
        (self.root / filename).write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def write_catalog(self, entries=None, version=CATALOG_VERSION):
        self.path.write_text(json.dumps({'schema_version': version, 'profiles': self.entries if entries is None else entries}))

    def test_two_registered_companies_keep_their_own_complete_scope(self):
        for index, alias in [(0, 'ACME'), (0, ' acme devices '), (1, 'OTHER'), (1, 'other foundry')]:
            with self.subTest(alias=alias):
                result = resolve_company_profile(self.path, alias)
                self.assertEqual(result, self.configs[index])
                result['limits']['max_documents'] = 999
                self.assertEqual(resolve_company_profile(self.path, alias), self.configs[index])

    def test_unknown_empty_or_nonstring_company_never_falls_back(self):
        for name in ('UNKNOWN', 'Acme Unlisted', '', '   ', None, 123, [], 'ACME\n'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                resolve_company_profile(self.path, name)
        with self.assertRaisesRegex(ValueError, 'nonempty'):
            resolve_company_profile(self.root / 'not-read.json', ' ')

    def test_shared_alias_is_ambiguous_not_the_first_profile(self):
        entries = deepcopy(self.entries)
        for entry in entries:
            entry['aliases'].append('Shared Name')
        self.write_catalog(entries)
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            resolve_company_profile(self.path, 'shared name')

    def test_swapped_profile_mapping_fails_even_with_correct_file_hash(self):
        entries = deepcopy(self.entries)
        entries[0]['profile'] = deepcopy(entries[1]['profile'])
        self.write_catalog(entries)
        with self.assertRaisesRegex(ValueError, 'identity'):
            resolve_company_profile(self.path, 'ACME')

    def test_company_id_cik_market_and_symbol_cannot_disagree(self):
        for field, value in [('company_id', 'sec-0000000999'), ('cik', '0000000999'),
                             ('market', 'NYSE'), ('symbol', 'OTHER')]:
            entries = deepcopy(self.entries)
            entries[0][field] = value
            if field == 'symbol':
                entries[0]['aliases'].append(value)
            self.write_catalog(entries)
            with self.subTest(field=field), self.assertRaises(ValueError):
                resolve_company_profile(self.path, 'ACME')

    def test_profile_byte_drift_is_rejected_without_rewriting_catalog(self):
        before = self.path.read_bytes()
        (self.root / 'acme.json').write_bytes((self.root / 'acme.json').read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            resolve_company_profile(self.path, 'ACME')
        self.assertEqual(self.path.read_bytes(), before)

    def test_profile_paths_cannot_escape_catalog_directory(self):
        for filename in ('../acme.json', '/tmp/acme.json', 'nested/acme.json', 'nested\\acme.json', '..', ''):
            entries = deepcopy(self.entries)
            entries[0]['profile']['filename'] = filename
            self.write_catalog(entries)
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                resolve_company_profile(self.path, 'ACME')
        self.write_catalog()
        actual = self.root / 'acme.json'
        actual.rename(self.root / 'actual.json')
        actual.symlink_to(self.root / 'actual.json')
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            resolve_company_profile(self.path, 'ACME')

    def test_invalid_catalog_version_structure_and_duplicate_keys_fail(self):
        for version in ('company-profile-catalog-v999', '', None):
            self.write_catalog(version=version)
            with self.subTest(version=version), self.assertRaises(ValueError):
                resolve_company_profile(self.path, 'ACME')
        for raw in ('[]', 'null', '{}', '{"schema_version":1,"schema_version":2}'):
            self.path.write_text(raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                resolve_company_profile(self.path, 'ACME')

    def test_catalog_symlink_or_parent_traversal_is_rejected(self):
        link = self.root / 'alias.json'
        link.symlink_to(self.path)
        for path in (link, self.root / 'unused' / '..' / 'catalog.json', None):
            with self.subTest(path=path), self.assertRaises(ValueError):
                resolve_company_profile(path, 'ACME')

    def test_missing_scope_is_not_completed_with_defaults(self):
        config = deepcopy(self.configs[0])
        del config['filing_selection']
        self.entries[0]['profile']['sha256'] = self.write_profile('acme.json', config)
        self.write_catalog()
        with self.assertRaisesRegex(ValueError, 'complete acquisition scope'):
            resolve_company_profile(self.path, 'ACME')

    def test_pilot_catalog_resolves_only_explicitly_registered_names(self):
        catalog = Path(__file__).resolve().parents[2] / 'config/company_sources/annual-pilot-catalog-v1.json'
        for name, symbol in [('AMD', 'AMD'), ('Advanced Micro Devices', 'AMD'),
                             ('TSM', 'TSM'), ('TSMC', 'TSM'), ('台积电', 'TSM')]:
            with self.subTest(name=name):
                result = resolve_company_profile(catalog, name)
                filename = 'amd-annual-v1.json' if symbol == 'AMD' else 'tsmc-annual-v1.json'
                self.assertEqual(result, json.loads((catalog.parent / filename).read_text()))
        with self.assertRaisesRegex(ValueError, 'not registered'):
            resolve_company_profile(catalog, 'MSFT')


if __name__ == '__main__':
    unittest.main()
