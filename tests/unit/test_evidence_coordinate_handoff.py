"""Direct-normalization spans survive frozen dataset -> packaged locator delivery."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import duckdb

from tests.unit import test_direct_normalization as fixtures
from tests.unit.test_scoped_query_service import make_scoped_dataset
from uteki.infrastructure.research_data.direct_normalization import normalize_direct_candidates
from uteki.infrastructure.research_data.evidence_packaging import build_evidence_package
from uteki.infrastructure.research_data.evidence_coordinates import character_span
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort


class EvidenceCoordinateHandoffTests(unittest.TestCase):
    def fixture(self, mutate=None):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        make_scoped_dataset(root)
        sources = json.loads((root/'sources.json').read_text())
        source = next(s for s in sources if s['source_snapshot_id'] == 'acme-annual')
        packet, draft = fixtures.DirectNormalizationTests().fixture('acme', 2031)
        packet['source'] = source
        packet['task']['source_snapshot_ids'] = ['acme-annual']
        packet['task']['knowledge_cutoff'] = '2032-05-01'
        normalized = normalize_direct_candidates(draft, packet)
        self.assertEqual(len(normalized['records']), 1)
        evidence = deepcopy(normalized['evidence'])
        if mutate: mutate(evidence)
        folder = root/source['index_folder']
        blocks = [json.loads(line) for line in (folder/'blocks.jsonl').read_text().splitlines()]
        blocks[1].update(packet['blocks'][0])
        (folder/'blocks.jsonl').write_text(''.join(json.dumps(b)+'\n' for b in blocks))
        manifest = json.loads((folder/'manifest.json').read_text())
        manifest['artifacts']['blocks.jsonl']['sha256'] = digest((folder/'blocks.jsonl').read_bytes())
        (folder/'manifest.json').write_text(json.dumps(manifest))
        with duckdb.connect(str(root/'research.duckdb')) as db:
            for eid, row in evidence.items():
                db.execute('INSERT INTO evidence VALUES (?, ?, ?)', [eid, row['source_snapshot_id'], json.dumps(row)])
        manifest = json.loads((root/'manifest.json').read_text())
        manifest['files'] = {str(p.relative_to(root)): digest(p.read_bytes()) for p in root.rglob('*')
                             if p.is_file() and p != root/'manifest.json'}
        (root/'manifest.json').write_text(json.dumps(manifest))
        port = QueryDataPort(root); self.addCleanup(port.close)
        scope = {'snapshot_id': port.snapshot_id, 'company_ids': ['acme'], 'source_snapshot_ids': ['acme-annual'],
                 'source_policy_id': 'local-frozen-v1', 'knowledge_cutoff': '2032-05-01', 'include_candidates': True}
        return port.scoped(scope), {'request': {'question': 'Retrieve the reported outlook and qualification.', 'scope': scope},
            'records': [], 'computed_facts': [], 'contexts': [], 'evidence': evidence, 'navigation': [], 'gaps': []}

    def test_normalization_source_coordinates_become_exact_packaged_locators(self):
        scoped, result = self.fixture()
        package = build_evidence_package(scoped, result)
        for item in package['artifacts']:
            if item['kind'] != 'source_quote': continue
            original = item['payload']['evidence']; locator = item['locators'][0]
            self.assertEqual((locator['char_start'], locator['char_end']),
                             (original['source_start'], original['source_end']))
            self.assertEqual(locator['block_id'], original['block_id'])
            self.assertEqual(locator['source_snapshot_id'], 'acme-annual')
            self.assertEqual(item['provenance']['verification'], 'source_verified')

    def test_conflicting_legacy_and_normalized_coordinates_are_rejected(self):
        def conflict(evidence):
            for item in evidence.values(): item.update(start=0, end=1)
        scoped, result = self.fixture(conflict)
        with self.assertRaisesRegex(ValueError, 'conflict'):
            build_evidence_package(scoped, result)

    def test_frozen_but_invalid_normalized_spans_cannot_pass_by_quote_presence(self):
        def invalid(evidence):
            for item in evidence.values(): item['source_start'] = item['source_start'] + 1
        scoped, result = self.fixture(invalid)
        with self.assertRaisesRegex(ValueError, 'offsets disagree'):
            build_evidence_package(scoped, result)

    def test_duplicate_text_is_disambiguated_by_coordinate_and_aliases_are_strict(self):
        text = '😀 same. same.'
        self.assertEqual(character_span({'source_start': 8, 'source_end': 13, 'quote': 'same.'}, text=text), (8, 13))
        self.assertEqual(character_span({'start': 8, 'end': 13, 'char_start': 8, 'char_end': 13}, text=text), (8, 13))
        for record in ({'start': True, 'end': 2}, {'source_start': 0}, {'source_end': 5},
                       {'start': -1, 'end': 2}, {'char_start': 0, 'char_end': 50},
                       {'source_start': 8, 'source_end': 13, 'start': 2, 'end': 7}):
            with self.subTest(record=record), self.assertRaises(ValueError): character_span(record, text=text)
