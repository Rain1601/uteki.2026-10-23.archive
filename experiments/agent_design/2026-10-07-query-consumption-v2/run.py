"""Offline consumption of explicitly selected historical model candidates.

No model call, extraction, relabelling or source mutation occurs here. Answers
are checked by a separate oracle only after the production query returns.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from uteki.agents.reading.document_reader import DocumentReader
from uteki.infrastructure.research_data.query_service import QueryDataPort

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n"


def save(name, value):
    path = HERE / name
    data = encoded(value)
    if path.exists() and path.read_bytes() != data:
        raise ValueError("preserve the existing receipt; choose a new experiment version: " + name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def main():
    cases = json.loads((HERE / "cases.json").read_bytes())
    receipts = []
    for case in cases:
        path = ROOT / case["dataset"]
        with QueryDataPort(path) as port:
            scope = {"snapshot_id": port.snapshot_id, "company_ids": [case["company_id"]],
                     "source_snapshot_ids": [case["source_id"]], "source_policy_id": "local-frozen-v1",
                     "knowledge_cutoff": case["cutoff"], "include_candidates": True}
            scoped = port.scoped(scope)
            request = {"query_id": case["id"], "snapshot_id": port.snapshot_id,
                       "knowledge_cutoff": case["cutoff"], "include_candidates": True,
                       "calculations": [{"formula_id": "operating_margin", "entity_id": case["company_id"],
                                         "periods": [case["period"]]}]}
            save(case["id"] + "/input.json", {"scope": scope, "query": request,
                 "dataset": case["dataset"], "dataset_manifest_sha256": sha256((path / "manifest.json").read_bytes()).hexdigest(),
                 "plan_origin": "codex_explicit_typed_plan", "model_calls": 0})
            results = [scoped.query_data(request) for _ in range(3)]
            assert results[0] == results[1] == results[2], "local repeat differs"
            result = results[0]
            assert result["status"] == "complete" and len(result["computed_facts"]) == 1
            context_gaps = []
            for ev in result["evidence"].values():
                context = scoped.read_context(source_snapshot_id=ev["source_snapshot_id"], block_id=ev["block_id"],
                                              representation="compact")
                if not any(b["block_id"] == ev["block_id"] for b in context.get("blocks", [])):
                    context_gaps.append({"block_id": ev["block_id"], "status": context["status"],
                                         "gaps": context.get("gaps", [])})
                source = next(s for s in port.sources if s["source_snapshot_id"] == ev["source_snapshot_id"])
                reader = DocumentReader(path / source["index_folder"])
                block = reader.blocks[reader.positions[ev["block_id"]]]
                assert ev["quote"] in block["text"] and ev["text_hash"] == block["text_hash"]
            save(case["id"] + "/result.json", result)
            rejected = []
            for name, change in (("missing-company-scope", {"company_ids": []}),
                                 ("wrong-company-scope", {"company_ids": [case["other_company_id"]]}),
                                 ("unknown-source-scope", {"source_snapshot_ids": ["not-in-this-snapshot"]})):
                try:
                    port.scoped({**scope, **change})
                except (ValueError, PermissionError, KeyError):
                    rejected.append(name)
                else:
                    raise AssertionError(name + " must reject")
            missing = deepcopy(request)
            missing["query_id"] += "-unprocessed-period"
            missing["calculations"][0]["periods"] = [case["missing_period"]]
            gap = scoped.query_data(missing)
            assert not gap["computed_facts"] and gap["gaps"]
            save(case["id"] + "/missing-period.json", gap)
            receipts.append({"case": case["id"], "local_repeats": 3,
                "repeat_sha256": sha256(encoded(result)).hexdigest(), "evidence_rechecked": len(result["evidence"]),
                "scope_rejections": rejected, "missing_period_has_no_substitute": True,
                "full_block_read_gaps": context_gaps,
                "computed": result["computed_facts"][0]})
    # Expected answers never go into source preparation, query inputs or model calls.
    oracle = json.loads((HERE / "oracle.json").read_bytes())
    for receipt in receipts:
        assert receipt["computed"]["display_decimal"] == oracle[receipt["case"]]["display_percent"]
    save("verification.json", {"status": "passed", "model_calls": 0,
        "new_model_cost_usd": "0", "extraction_origin": "frozen_historical_model_candidates",
        "query_origin": "production_SQL_and_Decimal_with_explicit_Codex_plan", "cases": receipts,
        "limits": ["No natural-language planner was rerun.", "Candidate inputs are not automatically adopted.",
                   "Same local execution repeating is not model reproducibility.",
                   "New parser evidence compatibility is assessed separately.",
                   "This single-period ratio does not establish week-year YoY comparability."]})
    print(json.dumps({"status": "passed", "cases": len(receipts), "model_calls": 0}))


if __name__ == "__main__":
    main()
