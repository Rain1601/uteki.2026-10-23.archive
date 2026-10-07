"""Render a bound, single-pair model comparison without modifying either run."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote, urlparse


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"Object required: {path}")
    return value


def local(root: Path, value: str | Path) -> Path:
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"Missing file or outside project: {value}")
    return path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def build(root: Path, protocol_path: Path, pages: dict[str, Path], output: Path,
          workbench_url: str, review_path: Path | None = None,
          provider_console_path: Path | None = None) -> dict:
    root = root.resolve()
    protocol_path = local(root, protocol_path)
    protocol = read(protocol_path)
    output = (root / output).resolve()
    require(output.is_relative_to(root), "Output must remain inside project")
    parsed = urlparse(workbench_url)
    require(parsed.scheme in {"http", "https"} and bool(parsed.netloc), "Invalid workbench URL")
    require(protocol["method"]["repeats_per_arm"] == 1, "This view supports one run per arm")
    require(protocol["request_comparison"]["differing_top_level_fields"] == ["model"], "Unexpected experiment variables")
    require(protocol["request_comparison"]["all_other_fields_equal"] is True, "Protocol does not assert matched requests")
    controlled = protocol["controlled_input"]

    def href(path: Path) -> str:
        return quote(os.path.relpath(path, output).replace(os.sep, "/"), safe="/.-_")

    arms, raw_requests, result_hashes, raw_packet = {}, {}, {}, None
    for key in ("A", "B"):
        spec = protocol["arms"][key]
        result_path = local(root, Path(spec["run_dir"]) / "result.json")
        run_dir = result_path.parent
        require(not output.is_relative_to(run_dir), "Cannot render into a frozen run")
        result = read(result_path)
        result_hashes[key] = sha(result_path)
        if "result_sha256" in spec:
            require(result_hashes[key] == spec["result_sha256"], f"{key}: frozen result changed")
        if "trace_id" in spec:
            require(result["trace_id"] == spec["trace_id"], f"{key}: Trace mismatch")
        request_path = local(root, run_dir / "request.json")
        require(sha(request_path) == spec["request_sha256"] == result["request_sha256"], f"{key}: request hash mismatch")
        request = read(request_path)
        require(request["model"] == result["model"] == spec["model"], f"{key}: requested model mismatch")
        for field, expected in controlled.items():
            require(result.get(field) == expected, f"{key}: controlled input mismatch: {field}")
        for field, filename in (("source_packet_sha256", "source_packet.json"), ("skill_sha256", "skill.md")):
            require(sha(local(root, run_dir / filename)) == controlled[field], f"{key}: {filename} changed")
        # The execution contract hashes Schema JSON using this serialization, not its pretty-printed file.
        schema = read(local(root, run_dir / "output_schema.json"))
        require(hashlib.sha256(json.dumps(schema, ensure_ascii=False).encode()).hexdigest() == controlled["output_schema_sha256"], f"{key}: output Schema changed")
        packet = read(run_dir / "source_packet.json")
        if raw_packet is None:
            raw_packet = packet
            source = local(root, packet["source_local_path"])
            raw = gzip.decompress(source.read_bytes()) if packet.get("source_encoding") == "gzip" else source.read_bytes()
            require(hashlib.sha256(raw).hexdigest() == controlled["source_sha256"], "Original source hash mismatch")
        require(packet == raw_packet, "Source packets differ")
        raw_requests[key] = request
        artifact_hashes = result.get("artifacts_sha256", {})
        for filename, expected in artifact_hashes.items():
            artifact = local(root, run_dir / filename)
            require(artifact.parent == run_dir, "Artifact must be local to its run")
            require(sha(artifact) == expected, f"{key}: artifact changed: {filename}")
        records = result.get("costs", {}).get("records", [])
        require(len(records) == 1, f"{key}: comparison requires exactly one recorded model call")
        call = records[0]
        require(call.get("request_sha256") == result["request_sha256"], f"{key}: dispatched request mismatch")
        require(call.get("requested_model") == request["model"], f"{key}: call model mismatch")
        config = read(local(root, run_dir / "configuration.json"))
        for field, value in {"timeout_seconds": protocol["request_comparison"]["timeout_seconds"],
                             "max_retries": protocol["request_comparison"]["max_retries"]}.items():
            require(config["fields"][field]["value"] == value, f"{key}: {field} differs")
        for field, value in protocol["request_comparison"]["body_parameters"].items():
            require(request.get(field) == value, f"{key}: {field} differs from protocol")
        usage = call.get("usage") or {}
        page = local(root, pages[key]) if result.get("status") == "candidate" else None
        if page:
            page_check = read(local(root, page.parent / "verification.json"))
            require(page_check["trace_id"] == result["trace_id"], f"{key}: rendered page belongs to another run")
            require(page_check["fingerprints"]["html"] == sha(page), f"{key}: rendered page changed")
            require(page_check["fingerprints"]["result"] == result_hashes[key], f"{key}: rendered result binding mismatch")
            require(page_check["with_svg"] is True, f"{key}: rendered diagram not ready")
        links = {"result": href(result_path), "request": href(request_path),
                 "packet": href(run_dir / "source_packet.json"), "skill": href(run_dir / "skill.md"),
                 "configuration": href(run_dir / "configuration.json"),
                 "process": workbench_url.rstrip("/") + "/agent-runs?agent=data&run=" + quote(result["trace_id"]),
                 "workbench_result": workbench_url.rstrip("/") + "/agent-results?agent=data&run=" + quote(result["trace_id"])}
        if page:
            links["page"] = href(page)
        for label, filename in (("evidence", "evidence.html"), ("business", "business_map.json"),
                                ("revenue", "revenue.json"), ("response", "response.txt"),
                                ("response_metadata", "response_metadata.json")):
            if (run_dir / filename).is_file():
                links[label] = href(run_dir / filename)
        arms[key] = {"label": "Sonnet 5.5" if key == "A" else "Opus 5.5", "trace_id": result["trace_id"],
                     "requested_model": result["model"], "returned_model": call.get("actual_upstream_model"),
                     "status": result.get("status"), "validation": result.get("validation"),
                     "counts": result.get("counts", {}), "input_tokens": usage.get("input_tokens"),
                     "output_tokens": usage.get("output_tokens"), "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
                     "elapsed_seconds": call.get("elapsed_seconds"), "started_at": call.get("started_at"),
                     "ended_at": call.get("ended_at"), "stop_reason": call.get("stop_reason"),
                     "estimated_usd": result.get("costs", {}).get("known_estimated_usd"),
                     "unknown_cost_requests": result.get("costs", {}).get("unknown_cost_requests"),
                     "held_usd": result.get("budget", {}).get("held_usd"),
                     "error_type": call.get("error_type"), "dispatch_status": call.get("dispatch_status"),
                     "http_status": call.get("http_status"), "links": links,
                     "result_sha256": result_hashes[key], "artifact_hashes": artifact_hashes}
    require(arms["A"]["trace_id"] != arms["B"]["trace_id"], "Cannot compare a run to itself")
    differing = sorted(key for key in raw_requests["A"].keys() | raw_requests["B"].keys()
                       if raw_requests["A"].get(key) != raw_requests["B"].get(key))
    require(differing == ["model"], f"Request bodies differ beyond model: {differing}")
    require(all(field not in raw_requests["A"] for field in ("temperature", "top_p", "top_k", "seed")), "Sampling controls were not omitted")

    review = None
    if review_path:
        review_path = local(root, review_path)
        review = read(review_path)
        require(isinstance(review.get("summary"), str) and isinstance(review.get("checks"), list), "Review summary/checks missing")
        for key in ("A", "B"):
            binding = review["bindings"][key]
            for field in ("trace_id", "result_sha256"):
                require(binding[field] == arms[key][field], f"Review {key}: {field} mismatch")
            for field, filename in (("business_map_sha256", "business_map.json"), ("revenue_sha256", "revenue.json")):
                require(binding[field] == arms[key]["artifact_hashes"].get(filename), f"Review {key}: {field} mismatch")
        blocks = {block["id"]: block for block in raw_packet["blocks"]}
        source_ids = list(dict.fromkeys(source_id for check in review["checks"] for source_id in check.get("source_block_ids", [])))
        require(all(source_id in blocks for source_id in source_ids), "Review uses blocks outside selected packet")
        review = dict(review, source_blocks=[blocks[source_id] for source_id in source_ids], href=href(review_path))

    console_record = None
    if provider_console_path:
        provider_console_path = local(root, provider_console_path)
        console_record = read(provider_console_path)
        binding = console_record['binding']
        require(binding['local_trace_id'] == arms['B']['trace_id'] and
                binding['result_sha256'] == result_hashes['B'] and
                binding['request_sha256'] == protocol['arms']['B']['request_sha256'],
                'Console record does not match B')
        require(console_record['provider_record']['model'] == arms['B']['requested_model'],
                'Console record model mismatch')
        console_record = dict(console_record, href=href(provider_console_path))
    data = {"arms": arms, "review": review, "protocol": protocol, "provider_console": console_record,
            "links": {"protocol": href(protocol_path), "source": raw_packet["source_url"],
                      "source_file": href(local(root, raw_packet["source_local_path"]))},
            "packet_counts": {"blocks": len(raw_packet["blocks"]), "tables": len(raw_packet.get("tables", []))}}
    template = Path(__file__).with_name("template.html").read_text()
    require(template.count("/* DATA */") == 1, "Template data marker mismatch")
    output.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    (output / "index.html").write_text(template.replace("/* DATA */", payload))
    verification = {"schema_version": "model-ab-view-verification-v1", "protocol_sha256": sha(protocol_path),
                    "result_sha256": result_hashes, "request_differing_fields": differing,
                    "source_packet_skill_schema_and_source_verified": True,
                    "frozen_artifacts_verified": True, "review_bound": review is not None,
                    "view_sha256": sha(output / "index.html"), "browser_visual_review": "not_performed"}
    (output / "verification.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2) + "\n")
    return verification


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("root", "protocol", "a-page", "b-page", "output", "workbench-url"):
        parser.add_argument("--" + arg, required=True)
    parser.add_argument("--review")
    parser.add_argument("--provider-console-record")
    args = parser.parse_args()
    print(json.dumps(build(Path(args.root), Path(args.protocol), {"A": Path(args.a_page), "B": Path(args.b_page)},
                           Path(args.output), args.workbench_url, Path(args.review) if args.review else None,
                           Path(args.provider_console_record) if args.provider_console_record else None), ensure_ascii=False, indent=2))
