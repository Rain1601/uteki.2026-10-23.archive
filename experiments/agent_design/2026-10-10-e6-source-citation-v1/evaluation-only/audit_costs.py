"""Independent read-only ledger and sealed API cost audit; makes no model calls."""
import hashlib
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
E = Path(__file__).resolve().parent
O = ROOT / "output/e6-source-citation-20261010-r1"
read = lambda p: json.loads(p.read_bytes())
before = read(O / "ledger-before.v1.json")
progress = read(O / "progress.v2.json")
assert progress["status"] == "completed", "fixed execution is not completed"
assert [s["id"] for s in progress["steps"]] == ["repair-01-network-recovery", "repair-02", "fresh-S3"]
recovery = read(E / "network-recovery.v1.json")
unknown_ids = set(recovery["retained_unknown_ids"])
roots = [O / "repair-01", O / "repair-01-network-recovery", O / "repair-02", O / "fresh-S3/run-r1"]
sealed = set()
manifest_hashes = {}
for root in roots:
    manifest_path = root / "manifest.json"
    manifest_hashes[str(root.relative_to(ROOT))] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    manifest = read(manifest_path)["files"]
    for name, expected in manifest.items():
        p = root / name
        assert hashlib.sha256(p.read_bytes()).hexdigest() == expected, str(p)
        if name.endswith(("-start.json", "-end.json")):
            sealed.add(p.resolve())
observed = {p.resolve() for suffix in ("*-start.json", "*-end.json") for p in O.rglob(suffix)}
assert observed == sealed, "every API cost record must be sealed"
starts = [(p, read(p)) for p in O.rglob("*-start.json")]
ends = [(p, read(p)) for p in O.rglob("*-end.json")]
start_by_id = {v["call_id"]: v for _, v in starts}
end_by_id = {v["call_id"]: v for _, v in ends}
assert len(start_by_id) == len(starts) == len(end_by_id) == len(ends)
assert set(start_by_id) == set(end_by_id)
reservation_ids = [v["budget_reservation_id"] for _, v in ends]
assert len(set(reservation_ids)) == len(ends)
cfg = read(O / "runtime-config.v1.json")
conn = sqlite3.connect(Path(cfg["planner"]["budget_ledger"]).as_uri() + "?mode=ro", uri=True)
rows = {v[0]: v[1:] for v in conn.execute("SELECT id,reserved,actual,state FROM reservations")}
limit = conn.execute("SELECT usd FROM config").fetchone()[0]
cap = conn.execute("SELECT maximum FROM autonomous_request_limit").fetchone()[0]
authorization = conn.execute("SELECT COUNT(*) FROM limit_authorizations WHERE id=?", ("E6-20261010-user-add-10usd-v1",)).fetchone()[0]
conn.close()
assert limit == "13" and cap == 1000 and authorization == 1
assert set(before["ids"]) <= set(rows), "baseline reservations lost"
assert set(rows) - set(before["ids"]) == set(reservation_ids)
assert {k for k, (_, _, s) in rows.items() if s != "settled"} == unknown_ids
grouped = {}
details = []
known = Decimal(0)
held = Decimal(0)
for p, end in ends:
    start = start_by_id[end["call_id"]]
    key = str(p.relative_to(O)).split("/")[0]
    group = grouped.setdefault(key, {"calls": 0, "known_estimated_usd": Decimal(0), "held_reserved_usd": Decimal(0), "unknown_calls": 0})
    group["calls"] += 1
    rid = end["budget_reservation_id"]
    reserve, actual, state = rows[rid]
    assert start["budget_reservation_id"] == rid
    assert Decimal(start["reserved_usd"]) == Decimal(end["reserved_usd"]) == Decimal(reserve)
    assert start["pricing_snapshot"] == end["pricing_snapshot"]
    if rid in unknown_ids:
        assert state == "unknown" and actual is None
        assert end["estimated_usd"] is None and end["usage"] is None
        assert end["error_type"] == "APIConnectionError"
        held += Decimal(reserve)
        group["held_reserved_usd"] += Decimal(reserve)
        group["unknown_calls"] += 1
    else:
        assert state == "settled" and end["estimated_usd"] is not None
        pricing, usage = end["pricing_snapshot"], end["usage"]
        assert usage is not None and pricing["currency"] == "USD"
        expected = (Decimal(usage["input_tokens"]) * Decimal(pricing["input_per_million"]) + Decimal(usage["output_tokens"]) * Decimal(pricing["output_per_million"])) / Decimal(1000000)
        assert expected == Decimal(end["estimated_usd"]) == Decimal(actual), str(p)
        assert end["actual_billed_usd"] is None
        known += expected
        group["known_estimated_usd"] += expected
    details.append({"file": str(p.relative_to(ROOT)), "call_id": end["call_id"], "reservation_id": rid, "ledger_state": state, "reserved_usd": reserve, "estimated_usd": actual})
assert held == Decimal(recovery["retained_unknown_reserved_usd"])
total = sum((Decimal(a) for _, a, s in rows.values() if s == "settled"), Decimal(0))
assert total - Decimal(before["estimated_usd"]) == known
assert known + held < Decimal("3")
after = progress["ledger_after"]
assert after["requests"] == len(rows) and Decimal(after["estimated_usd"]) == total and Decimal(after["held_usd"]) == held
for g in grouped.values():
    for k in ("known_estimated_usd", "held_reserved_usd"):
        g[k] = str(g[k])
report = {"schema_version": "e6-r1-independent-cost-audit-v1", "status": "passed", "model_api_calls_for_audit": 0,
          "fixed_steps_completed": True, "verified_manifest_hashes": manifest_hashes,
          "baseline_requests": before["requests"], "baseline_estimated_usd": before["estimated_usd"],
          "new_calls": len(ends), "new_settled_calls": len(ends) - len(unknown_ids), "new_known_estimated_usd": str(known),
          "new_unknown_calls": len(unknown_ids), "new_held_reserved_usd": str(held), "new_known_plus_held_usd": str(known + held),
          "total_requests": len(rows), "total_known_estimated_usd": str(total), "total_held_reserved_usd": str(held), "total_known_plus_held_usd": str(total + held),
          "unknown": len(unknown_ids), "inflight": 0, "limit_usd": limit, "request_cap": cap,
          "original_authorization_retained": True, "baseline_ids_retained": True, "all_new_rows_matched_sealed_unique_calls": True,
          "cost_arithmetic_recomputed": True, "cache_discount_applied": False, "actual_supplier_bill_verified": False,
          "unknown_connection_failures_retained_not_zeroed": True, "by_execution": grouped, "calls": details}
(E / "cost-audit.v1.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({k: v for k, v in report.items() if k not in ("calls", "verified_manifest_hashes")}, ensure_ascii=False))
