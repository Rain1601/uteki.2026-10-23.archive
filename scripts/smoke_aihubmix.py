"""Small, metered SDK tool + structured-output probe; never log credentials."""
import argparse
import asyncio
import json
import logging
from pathlib import Path
import secrets

from agents import Agent, ModelSettings, Runner, RunConfig, function_tool
from openai import AsyncOpenAI
from pydantic import BaseModel

from uteki.agents.runtime.call_costs import MeteredModel, pricing_snapshot, summarize
from uteki.agents.runtime.local_credentials import load_provider_key
from uteki.agents.runtime.model_factory import model_adapter
from uteki.agents.runtime.run_budget import RunBudget


ROOT = Path(__file__).resolve().parents[1]
PROVIDER = "aihubmix"
COST_NOTE = ("Historical registered price snapshot; local estimate only, not a provider "
             "bill or a guaranteed billing cap. Failed requests may have unknown cost.")


class Result(BaseModel):
    code: str


def safe_error(error):
    status = getattr(error, "status_code", None)
    return {"error_type": type(error).__name__,
            "http_status": status if type(status) is int else None}


async def run_probe(model, output_dir, *, budget_usd="0.10"):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    report = {"success": False, "provider": PROVIDER, "model": model,
              "cost_note": COST_NOTE, "tool_called": False, "code_matches": False,
              "output_contract": "explicit_json_instructions_and_sdk_validation",
              "limits": {"max_turns": 2, "max_output_tokens": 1000,
                         "timeout_seconds": 90, "sdk_retries": 0}}
    clients, calls = [], []
    budget = None
    stage = "configuration"
    logging_level = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        pricing = pricing_snapshot(PROVIDER, model)
        if pricing is None:
            raise ValueError("A registered model price snapshot is required")
        report["pricing_snapshot"] = pricing
        stage = "credentials"
        report["credential_origin"] = load_provider_key(ROOT, PROVIDER)
        stage = "budget"
        budget = RunBudget(output / "budget.sqlite", budget_usd)

        def client_factory(**kwargs):
            client = AsyncOpenAI(**kwargs)
            clients.append(client)
            return client

        code = secrets.token_hex(16)

        @function_tool
        def probe() -> str:
            """Return the verification code required for this test."""
            calls.append(True)
            return code

        stage = "model"
        inner = model_adapter(model, PROVIDER, client_factory=client_factory)
        metered = MeteredModel(inner, output / "calls", "compatibility", PROVIDER,
                               model, pricing, budget)
        agent = Agent(name="compatibility", model=metered,
            instructions=("Call probe once. After receiving its result, return one JSON object "
                "with the exact verification code. Do not include Markdown fences or explanations. "
                "Follow this JSON Schema: " + json.dumps(Result.model_json_schema())),
            tools=[probe], output_type=Result,
            model_settings=ModelSettings(max_tokens=1000, store=False))
        result = await asyncio.wait_for(Runner.run(agent, "Check tool and output compatibility.",
            max_turns=2, run_config=RunConfig(tracing_disabled=True)), timeout=90)
        report["code_matches"] = isinstance(result.final_output, Result) and result.final_output.code == code
        report["success"] = bool(calls) and report["code_matches"]
        if not report["success"]:
            report["failure_stage"] = "verification"
            report["error_type"] = "ToolNotCalled" if not calls else "OutputMismatch"
    except Exception as error:
        report.update(failure_stage=stage, **safe_error(error))
    finally:
        report["tool_called"] = bool(calls)
        report["tool_call_count"] = len(calls)
        for client in clients:
            try:
                await client.close()
            except Exception as error:
                report.update(success=False, cleanup_error=safe_error(error))
        report["costs"] = summarize(output / "calls")
        if budget is not None:
            report["budget"] = budget.summary()
        logging.disable(logging_level)
    with (output / "result.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output-dir", required=True, type=Path, help="New directory; existing runs are never overwritten")
    parser.add_argument("--budget-usd", default="0.10", help="Local estimated-cost ceiling, not a provider billing cap")
    args = parser.parse_args(argv)
    try:
        report = asyncio.run(run_probe(args.model, args.output_dir, budget_usd=args.budget_usd))
    except Exception as error:
        report = {"success": False, **safe_error(error)}
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
