"""Verify and package retrieved data; no model, network, adoption or source writes."""
from copy import deepcopy
import json

from uteki.agents.reading.document_reader import DocumentReader
from uteki.domain.research_data.evidence_package import (
    PACKAGE_VERSION, EvidenceArtifact, EvidencePackage, Provenance, SourceLocator,
)
from uteki.domain.research_data.scoped_agent_query import ScopedAgentQuery
from .adapters.evidence_provenance import classify_record_origin
from .financial_records import digest
from .query_dataset import contained
from .evidence_coordinates import character_span


class _Packager:
    def __init__(self, port, result):
        request = ScopedAgentQuery.model_validate(result["request"])
        if request.scope != port.scope:
            raise ValueError("evidence package scope differs from the scoped port")
        self.port, self.result, self.scope = port, result, request.scope
        # Tool responses contain ordinary mutable dicts. Neither those dicts nor
        # the port's reader/source cache can authenticate an imported result.
        sources = json.loads(self.frozen_bytes("sources.json"))
        self.sources = {s["source_snapshot_id"]: s for s in sources
                        if s["source_snapshot_id"] in self.scope.source_snapshot_ids}
        if (len(self.sources) != len(self.scope.source_snapshot_ids)
                or any(s["company_id"] not in self.scope.company_ids for s in self.sources.values())):
            raise ValueError("frozen source metadata conflicts with the execution scope")
        self.readers = {}
        self.artifacts, self.bindings, self.coverage, self.gaps = {}, {}, {}, {}

    def frozen_bytes(self, relative):
        expected = self.port.manifest["files"].get(relative)
        if expected is None:
            raise ValueError("evidence input is not pinned in the frozen dataset")
        data = contained(self.port.dataset, relative).read_bytes()
        if digest(data) != expected:
            raise ValueError("frozen evidence input hash mismatch")
        return data

    def gap(self, reason, *, ids=(), sources=(), detail):
        value = {"reason": reason, "artifact_ids": list(ids), "source_snapshot_ids": list(sources), "detail": detail}
        gid = "egap-" + digest(value)[:24]
        self.gaps[gid] = {"gap_id": gid, **value}

    def source(self, sid):
        if sid not in self.sources or not self.scope.include_candidates:
            raise ValueError("evidence is outside permitted candidate/source scope")
        source = self.sources[sid]
        if source["available_at"] > str(self.scope.knowledge_cutoff):
            raise ValueError("evidence source is after the cutoff")
        return source

    def locator(self, sid, block=None, evidence=None):
        source = self.source(sid)
        block, evidence = block or {}, evidence or {}
        fields = {"source_snapshot_id": sid, "source_sha256": source.get("source_sha256"),
                  "source_url": source.get("source_url"), "available_at": source.get("available_at"),
                  "index_id": source.get("index_id"), "block_id": block.get("block_id"),
                  "reported_page": block.get("reported_page"), "pdf_page": block.get("pdf_page"),
                  "dom_path": block.get("dom_path"), "text_hash": block.get("text_hash")}
        span = character_span(evidence, text=block.get("text"))
        if span is not None:
            if not block.get("block_id") or not isinstance(block.get("text"), str):
                raise ValueError("Character evidence requires a verified original block")
            fields.update(char_start=span[0], char_end=span[1])
        if evidence.get("cell"):
            if any(type(evidence["cell"].get(key)) is not int or evidence["cell"][key] < 0 for key in ("row", "column")):
                raise ValueError("Evidence cell requires explicit nonnegative integer row and column")
            fields["cell"] = {key: evidence["cell"][key] for key in ("row", "column")}
        if block.get("bbox") is not None:
            fields.update(bbox=block["bbox"], region_coordinate_system="indexed_bbox_units_unverified")
            self.gap("region_units_unverified", sources=(sid,),
                     detail="Indexed block bounding box is retained; units are not independently declared here and the box is not quote-tight.")
        return SourceLocator.model_validate(fields).model_dump(mode="json")

    def artifact(self, kind, payload, *, sources, locators=(), parents=(), method, method_id,
                 verification="source_verified", notes=(), **provenance):
        value = {"kind": kind, "source_snapshot_ids": sorted(set(sources)), "locators": list(locators),
                 "derived_from": sorted(set(parents)), "payload": payload,
                 "provenance": Provenance(method=method, method_id=method_id, verification=verification,
                                          notes=notes, **provenance).model_dump(mode="json")}
        aid = "art-" + digest(value)[:24]
        artifact = EvidenceArtifact(artifact_id=aid, **value).model_dump(mode="json")
        self.artifacts[aid] = artifact
        for loc in artifact["locators"]:
            if any(loc.get(key) is None for key in ("source_sha256", "source_url", "available_at")):
                self.gap("source_metadata_incomplete", ids=(aid,), sources=(loc["source_snapshot_id"],),
                         detail="Some source identity metadata is absent in the selected snapshot; no replacement is inferred.")
        return aid

    def bind(self, namespace, old_id, ids):
        if not old_id or not ids:
            raise ValueError("evidence binding requires an explicit identifier and artifacts")
        key = namespace + ":" + old_id
        current = self.bindings.setdefault(key, [])
        current.extend(aid for aid in ids if aid not in current)

    def cover(self, sid, node_id, block_ids, mode):
        value = {"source_snapshot_id": sid, "node_id": node_id, "block_ids": list(dict.fromkeys(block_ids)), "mode": mode}
        self.coverage[digest(value)] = value

    def block(self, sid, bid):
        source = self.source(sid)
        if sid not in self.readers:
            folder = source["index_folder"]
            for name in ("manifest.json", "index.json", "blocks.jsonl"):
                self.frozen_bytes(folder + "/" + name)
            self.readers[sid] = DocumentReader(contained(self.port.dataset, folder))
            if self.readers[sid].index["index_id"] != source["index_id"]:
                raise ValueError("frozen source/index identity mismatch")
        reader = self.readers[sid]
        if bid not in reader.positions:
            raise ValueError("evidence block is not in its selected source")
        return reader, reader.blocks[reader.positions[bid]]

    def source_block(self, sid, block):
        _, canonical = self.block(sid, block["block_id"])
        if block != canonical:
            raise ValueError("returned block differs from its frozen source")
        locator = self.locator(sid, block)
        if block["type"] == "image":
            payload, notes = self.image_payload(sid, block)
            aid = self.artifact("image_reference", payload, sources=(sid,), locators=(locator,),
                                method="source_read", method_id="indexed-image-reference-v1", notes=notes)
            if payload["bytes_status"] != "verified_local":
                self.gap("image_bytes_unavailable", ids=(aid,), sources=(sid,),
                         detail="Only the indexed image reference is packaged. Alt text is not OCR; no image understanding ran.")
            return aid
        kind = "source_table" if block["type"] == "table" else "source_text"
        payload = {"text": block["text"], "block": block}
        if kind == "source_table":
            if not isinstance(block.get("table"), dict):
                raise ValueError("table block has no structured table payload")
            payload["table"] = block["table"]
        return self.artifact(kind, payload, sources=(sid,), locators=(locator,),
                             method="source_read", method_id="frozen-index-block-v1",
                             notes=("Exact indexed block, including table/speaker metadata; parsing fidelity and semantic completeness are not evaluated.",))

    def image_payload(self, sid, block):
        source = self.source(sid)
        folder = contained(self.port.dataset, source["index_folder"])
        assets_path = folder / "assets.json"
        relative = str(assets_path.relative_to(self.port.dataset))
        assets = []
        if relative in self.port.manifest["files"]:
            data = assets_path.read_bytes()
            if digest(data) != self.port.manifest["files"][relative]:
                raise ValueError("indexed image metadata hash mismatch")
            assets = json.loads(data).get("assets", [])
        asset_id = block.get("image_asset_id")
        if not isinstance(asset_id, str) or not asset_id.strip() or asset_id != asset_id.strip():
            asset_id = None
        matches = [asset for asset in assets if asset.get("asset_id") == asset_id] if asset_id else []
        if len(matches) > 1:
            raise ValueError("ambiguous image asset identity")
        asset = matches[0] if matches else None
        status, byte_hash = ("metadata_only" if asset else "unresolved"), None
        # Metadata paths are not capabilities: only files pinned in this dataset
        # may be opened, never an old checkout asset or a remote URL.
        if asset and asset.get("local_path"):
            path = (folder / asset["local_path"]).resolve()
            if path.is_relative_to(self.port.dataset):
                name = str(path.relative_to(self.port.dataset))
                pinned = self.port.manifest["files"].get(name)
                if pinned and path.is_file():
                    actual = digest(path.read_bytes())
                    if actual != pinned or actual != asset.get("sha256"):
                        raise ValueError("image bytes do not match the frozen asset hashes")
                    status, byte_hash = "verified_local", actual
        return {"alt_text": block.get("text", ""), "image_asset_id": asset_id,
                "asset_metadata": asset, "bytes_status": status, "bytes_sha256": byte_hash,
                "ocr_status": "not_run", "vision_status": "not_run"}, (
                    "Image metadata/alt text are not image content, OCR or a visual interpretation.",)

    def contexts(self):
        for context in self.result.get("contexts", []):
            sid = context["source_snapshot_id"]
            source = self.source(sid)
            for key in ("source_sha256", "source_url", "index_id", "company_id", "available_at"):
                if key in context and context[key] != source.get(key):
                    raise ValueError("context source metadata differs from the frozen source")
            if context.get("status", "read") != "read" or not context.get("blocks"):
                raise ValueError("a context must contain successfully read body blocks")
            blocks = context["blocks"]
            ids = [b["block_id"] for b in blocks]
            if len(set(ids)) != len(ids) or ("block_ids" in context and list(context["block_ids"]) != ids):
                raise ValueError("context block identifiers disagree with its body")
            node = context.get("node_id")
            if node:
                reader, _ = self.block(sid, ids[0])
                if node not in reader.nodes:
                    raise ValueError("context node is absent from its source")
                lo, hi = reader._range(node)
                if any(not lo <= reader.positions.get(bid, -1) < hi for bid in ids):
                    raise ValueError("context body is outside the declared node")
            aids = [self.source_block(sid, block) for block in blocks]
            self.bind("context", context["context_id"], aids)
            for mode, subset in (("body_returned", [b["block_id"] for b in blocks if b["type"] != "image"]),
                                 ("image_reference_only", [b["block_id"] for b in blocks if b["type"] == "image"])):
                if subset:
                    self.cover(sid, node, subset, mode)

    def quotes(self):
        supplied = self.result.get("evidence", {})
        ids = list(supplied)
        verified = {}
        for start in range(0, len(ids), 256):
            verified.update(self.port.get_evidence(ids[start:start + 256])["evidence"])
        for eid, ev in supplied.items():
            if ev != verified[eid] or ev.get("evidence_id") != eid:
                raise ValueError("evidence payload differs from the frozen dataset")
            sid = ev["source_snapshot_id"]
            self.source(sid)
            parents, block = [], None
            if ev.get("block_id"):
                _, block = self.block(sid, ev["block_id"])
                if not ev.get("quote") or ev["quote"] not in block["text"]:
                    raise ValueError("evidence quote is not present in the original block")
                source = self.sources[sid]
                for key, expected in (("text_hash", block.get("text_hash")),
                        ("source_sha256", source.get("source_sha256")), ("index_id", source.get("index_id"))):
                    if ev.get(key) is not None and ev[key] != expected:
                        raise ValueError("evidence locator disagrees with the frozen source")
                character_span(ev, text=block["text"])
                if ev.get("cell") or ev.get("verified_header_cells"):
                    cells = (block.get("table") or {}).get("cells", [])
                    for cell in ([ev["cell"]] if ev.get("cell") else []) + ev.get("verified_header_cells", []):
                        if not any(all(c.get(k) == v for k, v in cell.items()) for c in cells):
                            raise ValueError("evidence cell is not present in the frozen table")
                bids = list(dict.fromkeys([block["block_id"], *ev.get("context_block_ids", [])]))
                for bid in bids:
                    _, parent = self.block(sid, bid)
                    if parent["type"] == "image":
                        raise ValueError("image alt text cannot supply source quote evidence")
                    parents.append(self.source_block(sid, parent))
                self.cover(sid, None, bids, "provenance_only")
            aid = self.artifact("source_quote", {"text": ev["quote"], "evidence": ev}, sources=(sid,),
                                locators=(self.locator(sid, block, ev),), parents=parents,
                                method="source_quote", method_id="frozen-evidence-link-v1",
                                verification="source_verified" if parents else "snapshot_verified")
            if not parents:
                self.gap("quote_without_read_parent", ids=(aid,), sources=(sid,),
                         detail="The frozen evidence has no block locator; only its stored payload was verified, not its original text.")
            self.bind("evidence", eid, [aid])

    def records(self):
        for record in self.result.get("records", []):
            sid = record["source_snapshot_id"]
            self.source(sid)
            restriction, args = self.port._source_restriction("s.")
            row = self.port._db.execute(
                "SELECT o.payload FROM observations o JOIN sources s USING(source_snapshot_id) "
                "WHERE o.record_id = ? AND o.available_at <= ? AND s.available_at <= ? AND o.status = 'candidate'" + restriction,
                [record["record_id"], self.scope.knowledge_cutoff, self.scope.knowledge_cutoff, *args]).fetchone()
            if row is None or json.loads(row[0]) != record:
                raise ValueError("record differs from the selected frozen observation")
            parents = []
            for name in ("evidence_ids", "qualifier_evidence_ids", "question_evidence_ids"):
                for eid in record[name]:
                    if "evidence:" + eid not in self.bindings:
                        raise ValueError("record references evidence missing from the supplied result")
                    parents.extend(self.bindings["evidence:" + eid])
            origin = classify_record_origin(record, self.port.manifest)
            locators = [loc for parent in dict.fromkeys(parents) for loc in self.artifacts[parent]["locators"]]
            provenance = {"input_path": origin["input_artifact"], "input_sha256": origin["input_sha256"],
                          "input_artifact_id": str(origin["record_index"]) if origin["record_index"] is not None else None}
            if origin["raw_model_extract"] is not None:
                model = self.artifact("model_extract", {"extraction": origin["raw_model_extract"]},
                    sources=(sid,), locators=locators, parents=parents, method="model", method_id=origin["method_id"],
                    verification="snapshot_verified", **provenance,
                    notes=(*origin["notes"], "Parents are the returned source citations, not a reconstruction of the full original model prompt."))
                parents.append(model)
                self.gap("model_metadata_unavailable", ids=(model,), sources=(sid,),
                         detail="The frozen extraction lacks provider/model/prompt hashes. No new model ran and these fields are not guessed.")
            aid = self.artifact("normalized_record", {"record": record, "origin_kind": origin["origin_kind"]},
                sources=(sid,), locators=locators, parents=parents, method="normalization", method_id=origin["method_id"],
                verification="snapshot_verified", notes=origin["notes"], **provenance)
            if origin["origin_kind"] == "unknown":
                self.gap("normalization_origin_unresolved", ids=(aid,), sources=(sid,), detail="The frozen record has no uniquely registered provenance binding.")
            self.bind("record", record["record_id"], [aid])

    def calculations(self):
        for fact in self.result.get("computed_facts", []):
            parents = []
            for rid in fact["operand_record_ids"]:
                if "record:" + rid not in self.bindings:
                    raise ValueError("computed fact has a missing normalized operand")
                parents.extend(self.bindings["record:" + rid])
            result = self.port.query_data({"query_id": "evidence-package-verification", "snapshot_id": self.scope.snapshot_id,
                "source_policy_id": self.scope.source_policy_id, "knowledge_cutoff": self.scope.knowledge_cutoff,
                "include_candidates": self.scope.include_candidates, "calculations": [{
                    "formula_id": fact["formula_id"].removesuffix("-v1"), "entity_id": fact["entity_id"], "periods": fact["periods"]}]})
            if fact not in result["computed_facts"]:
                raise ValueError("computed value differs from registered deterministic execution")
            sources = {sid for parent in parents for sid in self.artifacts[parent]["source_snapshot_ids"]}
            aid = self.artifact("computed_scalar", {"fact": fact}, sources=sources, parents=parents,
                                method="registered_calculation", method_id=fact["formula_id"], verification="snapshot_verified",
                                notes=("Recomputed from the scoped stored observations; Decimal strings and rounding metadata are retained.",))
            self.bind("computed", fact["computed_id"], [aid])

    def package(self):
        self.contexts()
        self.quotes()
        self.records()
        self.calculations()
        for nav in self.result.get("navigation", []):
            sid = nav["source_snapshot_id"]
            if sid not in self.sources:
                raise ValueError("navigation source is outside scope")
            # A preview or outline does not introduce any body evidence.
            self.cover(sid, nav.get("node_id"), (), "navigation_only")
        for gap in self.result.get("gaps", []):
            sid = gap.get("source_snapshot_id")
            self.gap(gap["reason"], sources=(sid,) if sid else (), detail=json.dumps(gap, ensure_ascii=False, sort_keys=True))
        body = {"schema_version": PACKAGE_VERSION, "scope": self.scope.model_dump(mode="json"),
                "source_companies": {sid: self.sources[sid]["company_id"] for sid in self.scope.source_snapshot_ids},
                "artifacts": list(self.artifacts.values()), "bindings": self.bindings,
                "coverage": list(self.coverage.values()), "gaps": list(self.gaps.values()),
                "semantic_completeness": "not_evaluated"}
        return EvidencePackage(bundle_id="bundle-" + digest(body)[:24], **body).model_dump(mode="json")


def build_evidence_package(scoped_port, result):
    """Convert a scoped Agent result, verifying data against the frozen snapshot.

    This also accepts historical scoped v0.3 results. Conversion returns a new
    artifact and never rewrites the old result, dataset or analytical adoption.
    """
    return _Packager(scoped_port, deepcopy(result)).package()
