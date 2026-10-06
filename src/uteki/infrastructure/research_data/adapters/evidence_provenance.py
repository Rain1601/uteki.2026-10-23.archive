"""Classify legacy record provenance through explicitly pinned input adapters.

This registry describes production methods, not extraction correctness. It never
reads an artifact path or infers a method from record IDs, labels or prose.
"""
from copy import deepcopy
import re


ADAPTER_ORIGINS = {
    "us-gaap-inline-v1": "deterministic",
    "alphabet-financial-v1": "deterministic",
    "alphabet-call-reviewed-v1": "model_assisted",
}


def classify_record_origin(record: dict, manifest: dict) -> dict:
    origin = record.get("origin")
    origin = origin if isinstance(origin, dict) else {}
    artifact = origin.get("artifact")
    artifact = artifact if isinstance(artifact, str) and artifact.strip() == artifact and artifact else None
    source_id = record.get("source_snapshot_id")
    ordinal = origin.get("record_index")
    ordinal = ordinal if isinstance(ordinal, int) and not isinstance(ordinal, bool) and ordinal >= 0 else None
    result = {
        "origin_kind": "unknown", "method_id": "unresolved",
        "input_artifact": artifact, "input_sha256": None,
        "record_index": ordinal, "raw_model_extract": None, "notes": [],
    }
    if artifact is None or not isinstance(source_id, str) or not source_id.strip() or source_id != source_id.strip():
        result["notes"].append("Missing explicit input artifact or source identity; production method is unresolved.")
        return result

    build_spec = manifest.get("build_spec")
    inputs = build_spec.get("inputs") if isinstance(build_spec, dict) else None
    matches = [item for item in inputs if isinstance(item, dict)
               and item.get("path") == artifact and item.get("source_snapshot_id") == source_id] if isinstance(inputs, (list, tuple)) else []
    if len(matches) != 1:
        result["notes"].append("Input artifact/source binding is missing or ambiguous; production method is unresolved.")
        return result

    selected = matches[0]
    input_hash = selected.get("sha256")
    if not isinstance(input_hash, str) or re.fullmatch(r"[0-9a-f]{64}", input_hash) is None:
        result["notes"].append("Input binding has no valid pinned SHA256; production method is unresolved.")
        return result
    result["input_sha256"] = input_hash
    adapter = selected.get("adapter")
    kind = ADAPTER_ORIGINS.get(adapter) if isinstance(adapter, str) else None
    if kind is None:
        result["notes"].append("The selected adapter has no registered provenance classification.")
        return result

    result.update(origin_kind=kind, method_id=adapter)
    result["notes"].append("Production method is declared by the uniquely pinned build input; this does not establish semantic correctness or approval.")
    result["notes"].append("The input hash is a manifest declaration; this classifier does not read or independently rehash external input bytes.")
    if kind == "model_assisted":
        raw = origin.get("raw_record")
        if isinstance(raw, dict):
            result["raw_model_extract"] = deepcopy(raw)
            result["notes"].append("Preserved origin.raw_record is the model extraction; the normalized record and its summary may include later reviewed derivations.")
        else:
            result["notes"].append("The original model extraction is absent from this record.")
        if ordinal is None:
            result["notes"].append("The model input record index is absent or invalid.")
        result["notes"].append("Provider, model and prompt metadata are unavailable in this frozen provenance binding; they are not inferred from paths or summaries.")
    return result
