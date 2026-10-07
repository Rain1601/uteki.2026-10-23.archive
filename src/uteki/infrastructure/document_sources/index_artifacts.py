from __future__ import annotations

import gzip
import hashlib
import json
import mimetypes
import os
import struct
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from uteki.domain.documents import ParsedDocument, SourceBlock
from uteki.infrastructure.document_sources.sec_index import build_legal_outline, parse_sec_source, validate_parser_version
from uteki.infrastructure.document_sources.snapshots import verify_snapshot


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _block_payload(block: SourceBlock) -> dict[str, Any]:
    value = asdict(block)
    value["style_signature"] = dict(block.style_signature)
    return value


def _jpeg_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:2] != b"\xff\xd8":
        raise ValueError(f"unsupported image format: {path.name}")
    offset = 2
    while offset + 9 < len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9}:
            continue
        length = struct.unpack(">H", data[offset : offset + 2])[0]
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
            return width, height
        offset += length
    raise ValueError(f"JPEG dimensions were not found: {path.name}")


def _asset_payloads(parsed: ParsedDocument, assets_dir: Path, output_dir: Path) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for reference in parsed.assets:
        filename = Path(reference.source_path).name
        asset_path = assets_dir / filename
        if not asset_path.is_file():
            raise FileNotFoundError(f"frozen source asset is missing: {asset_path}")
        raw = asset_path.read_bytes()
        width, height = _jpeg_size(asset_path)
        payloads.append(
            {
                **asdict(reference),
                "filename": filename,
                "local_path": Path(os.path.relpath(asset_path.resolve(), output_dir.resolve())).as_posix(),
                "mime_type": mimetypes.guess_type(filename)[0] or "application/octet-stream",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "width": width,
                "height": height,
            }
        )
    return payloads


def _publish_manifest(output_dir: Path, content: bytes) -> None:
    """Make the completion marker visible only after a complete write.

    The hard link atomically creates a new name without replacing another
    manifest. The temporary file is on the same filesystem as that name.
    """
    descriptor, temporary_name = tempfile.mkstemp(prefix=".manifest-", dir=output_dir)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.link(temporary_path, output_dir / "manifest.json")
    finally:
        temporary_path.unlink(missing_ok=True)


def build_index_artifacts(snapshot_dir: Path, output_dir: Path, *, parser_version: str | None = None) -> dict[str, Any]:
    if parser_version is not None:
        validate_parser_version(parser_version)
    # Reject even an empty or incomplete previous build. Retrying needs a new
    # output identity; an existing review artifact must never be overwritten.
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(f"index output already exists: {output_dir}")
    source_manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    full_snapshot = any(key in source_manifest for key in ("schema_version", "legacy_source_manifest", "identity_basis"))
    if full_snapshot:
        source_manifest = verify_snapshot(snapshot_dir)
        if output_dir.resolve().is_relative_to(snapshot_dir.resolve()):
            raise ValueError("index output must stay outside the verified source snapshot")
    with gzip.open(snapshot_dir / "source.html.gz", "rb") as source:
        raw_html = source.read()
    if hashlib.sha256(raw_html).hexdigest() != source_manifest["content_sha256"]:
        raise ValueError("frozen SEC source does not match its manifest SHA")
    parsed = parse_sec_source(
        source_manifest["document_id"],
        source_manifest["source_url"],
        raw_html,
        source_snapshot_id=source_manifest["source_snapshot_id"],
        form_type=source_manifest["form"],
        **({"parser_version": parser_version} if parser_version is not None else {}),
    )
    if full_snapshot:
        excluded_paths = {item["source_path"] for item in source_manifest["excluded_image_references"]}
        if any(asset.source_path in excluded_paths for asset in parsed.assets):
            raise ValueError("selected parser includes an excluded tracking pixel; choose a compatible parser_version")
    index = build_legal_outline(parsed)
    assets = _asset_payloads(parsed, snapshot_dir / "assets", output_dir)
    if full_snapshot:
        expected_assets = {asset["filename"]: asset for asset in source_manifest["assets"]}
        for asset in assets:
            expected = expected_assets.get(asset["filename"])
            if expected is None or any(asset[field] != expected[field] for field in ("sha256", "bytes")):
                raise ValueError("indexed asset differs from the verified source snapshot")
    index_payload = asdict(index)
    block_lines = b"".join(
        json.dumps(_block_payload(block), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        for block in parsed.blocks
    )
    assets_bytes = _json_bytes({"assets": assets})
    index_bytes = _json_bytes(index_payload)
    files = {
        "index.json": index_bytes,
        "blocks.jsonl": block_lines,
        "assets.json": assets_bytes,
    }
    manifest = {
        "index_id": index.index_id,
        "index_version": output_dir.name,
        "status": "candidate",
        "schema_version": index.schema_version,
        "parser_version": index.parser_version,
        "source_snapshot_id": index.source_snapshot_id,
        "source_sha256": parsed.content_hash,
        "source_verification": "complete_snapshot" if full_snapshot else "legacy_html_hash_only",
        "form_type": index.form_type,
        "counts": {
            "blocks": len(parsed.blocks),
            "tables": sum(block.type == "table" for block in parsed.blocks),
            "images": len(parsed.assets),
            "parts": sum(node.kind == "part" for node in index.nodes),
            "items": sum(node.kind == "item" for node in index.nodes),
            "diagnostics": len(index.diagnostics),
        },
        "artifacts": {
            filename: {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
            for filename, content in files.items()
        },
    }
    manifest_bytes = _json_bytes(manifest)
    output_dir.mkdir(parents=True, exist_ok=False)
    for filename, content in files.items():
        with (output_dir / filename).open("xb") as target:
            target.write(content)
    _publish_manifest(output_dir, manifest_bytes)
    return manifest
