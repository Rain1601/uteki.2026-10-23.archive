"""Lossless cell encoding permits full large-table reads without truncation."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from pydantic import ValidationError

from tests.unit.test_scoped_query_service import make_scoped_dataset
from uteki.domain.research_data.execution_scope import SourceReadRequest
from uteki.domain.research_data.agent_query import ContextRequest
from uteki.agents.data_query.autonomous import AutonomousDecision
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_dataset import save
from uteki.infrastructure.research_data.query_service import QueryDataPort, compact_table_cells
from uteki.agents.reading.document_reader import DocumentReader


class CompactSourceReadTests(unittest.TestCase):
    def test_context_schema_exposes_lossless_encoding_and_keeps_legacy_hash(self):
        legacy = {"source_snapshot_id": "synthetic-annual", "block_id": "b8"}
        for supplied in (legacy, {**legacy, "representation": "full"}):
            request = ContextRequest.model_validate(supplied)
            self.assertEqual(request.model_dump(mode="json"), legacy)
            self.assertEqual(digest(request.model_dump(mode="json")), digest(legacy))
        decision = AutonomousDecision.model_validate({"action": "read_context",
            "requirement_ids": ["table"], "context": {**legacy, "representation": "compact"}})
        self.assertEqual(decision.context.model_dump(mode="json")["representation"], "compact")
        self.assertEqual(AutonomousDecision.model_json_schema()["$defs"]["ContextRequest"]
                         ["properties"]["representation"]["enum"], ["full", "compact"])
        with self.assertRaises(ValidationError):
            ContextRequest.model_validate({**legacy, "representation": "truncated"})

    def test_full_reads_preserve_legacy_request_hash_and_compact_is_explicit(self):
        legacy = {"source_snapshot_id": "synthetic-annual", "node_id": "business",
                  "start_block_id": None, "count": 8, "cursor": None}
        for supplied in (legacy, {**legacy, "representation": "full"}):
            request = SourceReadRequest.model_validate(supplied)
            self.assertEqual(request.representation, "full")
            self.assertEqual(request.model_dump(mode="json"), legacy)
            self.assertEqual(digest(request.model_dump(mode="json")), digest(legacy))
        compact = SourceReadRequest.model_validate({**legacy, "representation": "compact"})
        self.assertEqual(compact.model_dump(mode="json"), {**legacy, "representation": "compact"})
        self.assertNotEqual(digest(compact.model_dump(mode="json")), digest(legacy))

    def test_large_table_preserves_every_cell_and_does_not_mutate_frozen_index(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_scoped_dataset(root)
            folder = root / "indexes/acme-annual"
            blocks = [json.loads(line) for line in (folder / "blocks.jsonl").read_text().splitlines()]
            cells = [{"text": str(i) if i % 3 else "", "row": i // 10, "column": i % 10,
                      "rowspan": 1, "colspan": 2 if i == 1 else 1, "is_header": i < 10}
                     for i in range(1000)]
            blocks[8]["table"] = {"row_count": 100, "column_count": 10, "cells": cells}
            (folder / "blocks.jsonl").write_text("".join(json.dumps(b) + "\n" for b in blocks))
            save(folder / "manifest.json", {"status": "candidate", "artifacts": {
                name: {"sha256": digest((folder / name).read_bytes())} for name in ("index.json", "blocks.jsonl")}})
            manifest = json.loads((root / "manifest.json").read_text())
            manifest["files"] = {name: digest((root / name).read_bytes()) for name in manifest["files"]}
            save(root / "manifest.json", manifest)
            before = (folder / "blocks.jsonl").read_bytes()
            with QueryDataPort(root) as owner:
                port = owner.scoped({"snapshot_id": owner.snapshot_id, "company_ids": ["acme"],
                    "source_snapshot_ids": ["acme-annual"], "source_policy_id": "local-frozen-v1",
                    "knowledge_cutoff": "2032-06-01", "include_candidates": True})
                full = port.read_context(source_snapshot_id="acme-annual", block_id="b8")
                self.assertEqual(full["status"], "context_too_large")
                self.assertEqual(full["blocks"], [])
                self.assertIsNone(full["next_cursor"])
                self.assertFalse(full["node_complete"])
                self.assertEqual(full["required_bytes"], full["representation_bytes"]["full"])
                self.assertGreater(full["required_bytes"], full["max_bytes"])
                self.assertLessEqual(full["representation_bytes"]["compact"], full["max_bytes"])
                retry = port.read_source(full["retry_request"])
                self.assertEqual(retry["status"], "read")
                compact = port.read_context(source_snapshot_id="acme-annual", block_id="b8", representation="compact")
                self.assertEqual(compact["status"], "read")
                table = next(b["table"] for b in compact["blocks"] if b["block_id"] == "b8")
                restored = [dict(zip(table["cell_fields"], row, strict=True)) for row in table["cells"]]
                self.assertEqual(restored, cells)
                self.assertEqual(len(restored), 1000)
                self.assertEqual(port.read_context(source_snapshot_id="acme-annual", block_id="b8")["status"], "context_too_large")
                self.assertEqual(next(b for b in compact["blocks"] if b["block_id"] == "b8")["text"], "Sales 100")
                self.assertEqual(compact["block_ids"], ["b7", "b8", "b9"])
                self.assertEqual(retry["blocks"], compact["blocks"])
                # Explicit encoding never grants another company/source access.
                with self.assertRaises(ValueError):
                    port.read_context(source_snapshot_id="other-annual", block_id="b8", representation="compact")
            self.assertEqual((folder / "blocks.jsonl").read_bytes(), before)

    def test_heterogeneous_cells_are_not_silently_reinterpreted(self):
        cells = [{"text": "a", "row": 1}, {"text": "b", "extra": "qualifier"}]
        result = compact_table_cells({"blocks": [{"block_id": "b", "table": {"cells": cells}}]})
        self.assertEqual(result["blocks"][0]["table"]["cells"], cells)
        self.assertNotIn("cell_fields", result["blocks"][0]["table"])

    def test_compact_overhead_does_not_claim_both_encodings_are_too_large(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); make_scoped_dataset(root)
            reader = DocumentReader(root / 'indexes/acme-annual')
            original = reader.read('root', 'b8', count=1)
            full_bytes = len(json.dumps(original, ensure_ascii=False).encode())
            self.assertGreater(len(json.dumps(compact_table_cells(original), ensure_ascii=False).encode()), full_bytes)
            with QueryDataPort(root) as owner:
                port = owner.scoped({'snapshot_id': owner.snapshot_id, 'company_ids': ['acme'],
                    'source_snapshot_ids': ['acme-annual'], 'source_policy_id': 'local-frozen-v1',
                    'knowledge_cutoff': '2032-06-01', 'include_candidates': True})
                with patch('uteki.infrastructure.research_data.query_service.MAX_DOCUMENT_BYTES', full_bytes):
                    refusal = port.read_context(source_snapshot_id='acme-annual', block_id='b8', representation='compact')
                    self.assertEqual(refusal['status'], 'context_too_large')
                    self.assertEqual(refusal['retry_request']['representation'], 'full')
                    self.assertEqual(port.read_source(refusal['retry_request'])['status'], 'read')
