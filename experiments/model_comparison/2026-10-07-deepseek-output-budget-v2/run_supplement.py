"""One versioned DeepSeek supplement with the original packet and system prompt."""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[3]
ORIGINAL = ROOT / "experiments/model_comparison/2026-10-06-sonnet-deepseek-small-v1"
ORIGINAL_RUNNER = ORIGINAL / "run_comparison.py"
ORIGINAL_SUMMARY = ORIGINAL / "run-001/summary.json"
PREPARED = ORIGINAL / "prepared"
RUNNER_SHA256 = "ca7c5ad62eecda125acef97cc53aa7c91443908fe90098ff23eb5485113a4d62"
SUMMARY_SHA256 = "6b9be912aeb7152429ea1f218aeb0fd3718dcd8e48ab82775a5c6ec48d4ebadc"
INPUT_PINS = {
    "packet_sha256": "7bcdfbf11422bf8eaf7bf452f63009302a29a749632027835bbc401b1f610e7e",
    "manifest_sha256": "3f81244b3ad3fce8524dc4ed3b39943439108999265e062c2b249d368d7da923",
    "system_sha256": "d91f8a15d1723c4763192585397f03605625021b7017e37ab8af3f32a17a7809",
    "messages_sha256": "b03d7790b8daf91343eb147e7ca9e35f0a2d739f00508c1da0f405e952237049",
}
TOTAL_BUDGET_USD = "0.20"
PRIOR_SPENT_USD = "0.05104896"
REMAINING_BUDGET_USD = "0.14895104"
MAX_TOKENS = 24000
TIMEOUT_SECONDS = 180
# Named experiment snapshot: no production price registry changes.
PRICE = {
    "provider": "deepseek", "model": "deepseek-v4-pro", "currency": "USD",
    "input_per_million": "1.32", "output_per_million": "3.96",
    "cached_input_per_million": "0.044",
    "source": "https://api-docs.deepseek.com/quick_start/pricing/",
    "checked_on": "2026-10-07",
    "basis": "Pinned peak list-price estimate; no cache or off-peak discounts applied; not a provider bill.",
}


def _pinned_bytes(path, expected):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Pinned input must be a regular file")
    value = path.read_bytes()
    if hashlib.sha256(value).hexdigest() != expected:
        raise ValueError("Pinned prior artifact hash mismatch")
    return value


def load_configuration():
    """Read public artifacts only; this path never loads credentials or uses a client."""
    _pinned_bytes(ORIGINAL_RUNNER, RUNNER_SHA256)
    prior = json.loads(_pinned_bytes(ORIGINAL_SUMMARY, SUMMARY_SHA256))
    budget = prior["budget"]
    if (budget.get("unknown_requests") != 0 or budget.get("in_flight_requests") != 0
            or Decimal(budget["held_usd"]) != 0
            or Decimal(budget["estimated_spent_usd"]) != Decimal(PRIOR_SPENT_USD)
            or Decimal(TOTAL_BUDGET_USD) - Decimal(PRIOR_SPENT_USD) != Decimal(REMAINING_BUDGET_USD)):
        raise ValueError("Prior cost must be settled and match the remaining experiment budget")
    if any(prior["input"].get(key) != value for key, value in INPUT_PINS.items()):
        raise ValueError("Prior summary input pins differ")
    spec = importlib.util.spec_from_file_location("uteki_supplement_" + uuid4().hex, ORIGINAL_RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # This is a fresh module object. Overrides cannot mutate a previously imported runner.
    module.MAX_TOKENS = MAX_TOKENS
    module.TIMEOUT_SECONDS = TIMEOUT_SECONDS
    module.BUDGET_USD = REMAINING_BUDGET_USD
    module.ARMS = ({"id": "01-deepseek", "provider": "deepseek", "model": "deepseek-v4-pro",
        "base_url": "https://api.deepseek.com",
        "extra_body": {"thinking": {"type": "enabled"}, "reasoning_effort": "high"},
        "reasoning_configuration": "thinking_enabled_high"},)

    def experiment_price(provider, model):
        if (provider, model) != ("deepseek", "deepseek-v4-pro"):
            raise ValueError("Supplement permits only the pinned DeepSeek model")
        return deepcopy(PRICE)

    module.pricing_snapshot = experiment_price
    original_load = module.load_prepared

    def load_pinned_prepared(path):
        if Path(path).resolve() != PREPARED.resolve():
            raise ValueError("Supplement requires the original prepared packet")
        packet, messages, metadata = original_load(path)
        if any(metadata.get(key) != value for key, value in INPUT_PINS.items()):
            raise ValueError("Original prompt or packet changed")
        return packet, messages, metadata

    module.load_prepared = load_pinned_prepared
    inspection = module.inspect_prepared(PREPARED)
    audit = {
        "schema_version": "deepseek-output-budget-supplement-v2",
        "intent": "Exactly one supplemental paid request; retain both original results and do not select best-of retries.",
        "original_runner_sha256": RUNNER_SHA256,
        "original_summary_sha256": SUMMARY_SHA256,
        "original_input_pins": deepcopy(INPUT_PINS),
        "overrides": {"models": ["deepseek/deepseek-v4-pro"],
            "max_output_tokens": {"original": 4000, "supplement": MAX_TOKENS},
            "timeout_seconds": {"original": 90, "supplement": TIMEOUT_SECONDS},
            "thinking": "enabled", "reasoning_effort": "high", "automatic_retries": 0},
        "budget": {"total_experiment_limit_usd": TOTAL_BUDGET_USD,
            "prior_estimated_spent_usd": PRIOR_SPENT_USD,
            "remaining_limit_usd": REMAINING_BUDGET_USD, "actual_billed_usd": None},
        "pricing_snapshot": deepcopy(PRICE),
        "inspection": inspection,
        "comparison_limit": "Supplement changes the output allowance and deadline; this is not an equal-compute A/B or a replacement for the original truncated result.",
        "reference_answers_enter_request": False,
    }
    return module, audit


def _write_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


async def run_supplement(output, **testing_dependencies):
    module, audit = load_configuration()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    _write_new(output / "configuration.json", audit)
    result = await module.run_comparison(PREPARED, output / "execution", **testing_dependencies)
    result["supplement_configuration"] = "configuration.json"
    result["combined_estimated_spent_usd"] = str(
        Decimal(PRIOR_SPENT_USD) + Decimal(result["budget"]["estimated_spent_usd"]))
    result["combined_actual_billed_usd"] = None
    _write_new(output / "summary.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="Check pinned inputs and estimate only; no credentials or network")
    args = parser.parse_args()
    try:
        if args.dry_run:
            _, audit = load_configuration()
            print(json.dumps(audit, ensure_ascii=False, indent=2))
            return 0
        if args.output is None:
            parser.error("--output must name a new directory")
        report = asyncio.run(run_supplement(args.output))
        print(json.dumps({"status": report["status"], "budget": report["budget"],
            "combined_estimated_spent_usd": report["combined_estimated_spent_usd"]}, indent=2))
        return 0 if report["status"] in {"completed", "completed_with_invalid_outputs"} else 1
    except Exception as error:
        print(json.dumps({"error_type": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
