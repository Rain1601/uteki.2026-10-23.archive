"""Direct extraction freezes distinct module identities from one byte read each."""
import asyncio
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.unit import test_extraction_batches as batch_fixtures
from uteki.agents.data_extraction.direct import extract_packet
from uteki.domain.research_data.direct_extraction import DirectExtraction
from uteki.infrastructure.research_data.direct_extraction import build_extraction_packet, run_direct_extraction
from uteki.infrastructure.research_data.direct_normalization import normalize_direct_candidates
from uteki.infrastructure.research_data.financial_records import digest


class DirectExtractionProvenanceTests(unittest.TestCase):
    def test_same_named_domain_and_infrastructure_files_have_distinct_verified_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            dataset, job = batch_fixtures.ExtractionBatchTests().source(root / 'source',
                company='sec-0000090033', source='independent-provenance-source', end='2032-12-31')
            sources = {Path(inspect.getfile(obj)).resolve() for obj in
                       (build_extraction_packet, extract_packet, normalize_direct_candidates, DirectExtraction)}
            original = Path.read_bytes
            expected_bytes = {source: original(source) for source in sources}
            reads = {source: 0 for source in sources}
            def observed_read(path):
                if path in reads:
                    reads[path] += 1
                return original(path)
            async def fixture(packet):
                return {'records': [], 'relations': [], 'gaps': ['Provenance-only offline fixture.']}
            with patch.object(Path, 'read_bytes', observed_read):
                result = asyncio.run(run_direct_extraction(dataset, job, root / 'run',
                    strategy='direct', model_call=fixture))
            self.assertEqual(result['plan_origin'], 'scripted_fixture')
            self.assertEqual(result['status'], 'candidate')
            self.assertEqual(set(reads.values()), {1})
            files = json.loads((root / 'run/manifest.json').read_text())['files']
            implementation = result['implementation']
            infrastructure = 'implementation/uteki/infrastructure/research_data/direct_extraction.py'
            domain = 'implementation/uteki/domain/research_data/direct_extraction.py'
            self.assertIn(infrastructure, implementation)
            self.assertIn(domain, implementation)
            self.assertNotEqual(implementation[infrastructure], implementation[domain])
            self.assertEqual(len(implementation), 4)
            package_root = Path(inspect.getfile(build_extraction_packet)).resolve().parents[2]
            for source, content in expected_bytes.items():
                name = str(Path('implementation') / source.relative_to(package_root.parent))
                with self.subTest(source=source):
                    frozen = (root / 'run' / name).read_bytes()
                    self.assertEqual(frozen, content)
                    self.assertEqual(implementation[name], digest(frozen))
                    self.assertEqual(files[name], implementation[name])


if __name__ == '__main__':
    unittest.main()
