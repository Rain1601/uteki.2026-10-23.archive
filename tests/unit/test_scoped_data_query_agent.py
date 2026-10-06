"""Scoped host-loop regressions; scripted decisions/HTTP mocks are not model evaluation."""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx2 as httpx
from openai import AsyncOpenAI
from pydantic import ValidationError

from uteki.agents.call_costs import MeteredModel, pricing_snapshot, summarize
from uteki.agents.data_query_agent import DataQueryAgent
from uteki.agents.data_query_model import SdkQueryPlanner
from uteki.agents.deepseek_model import DeepSeekChatCompletionsModel
from uteki.agents.run_budget import RunBudget
from uteki.domain.research_data.agent_query import AGENT_VERSION, AgentQuery, PlannerDecision
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.domain.research_data.query_contract import DataQuery, QueryResult, ResearchRecord, VERSION, export_query_schema
from uteki.domain.research_data.scoped_agent_query import (
    SCOPED_AGENT_VERSION, ScopedAgentQuery, ScopedPlannerDecision,
)
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort
from tests.unit import test_query_scope
from tests.unit.test_scoped_query_service import make_scoped_dataset


ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / "experiments/data_agent_query/2026-09-22-pilot-04/dataset"


class ScriptedPlanner:
    def __init__(self, actions):
        self.actions = iter(actions)
        self.packets = []

    async def decide(self, packet):
        self.packets.append(copy.deepcopy(packet))
        action = next(self.actions)
        return action(packet) if callable(action) else action


def scoped_request(port, *, companies, sources, question, cutoff):
    scope = ExecutionScope(snapshot_id=port.snapshot_id, company_ids=companies,
        source_snapshot_ids=sources, source_policy_id="local-frozen-v1",
        knowledge_cutoff=cutoff, include_candidates=True)
    return {"agent_schema_version": SCOPED_AGENT_VERSION,
            "question": question, "scope": scope.model_dump(mode="json")}


def finish_read_contexts(packet):
    contexts = [h["result"]["context_id"] for h in packet["history"]
                if h["result"].get("blocks") and "context_id" in h["result"]]
    return {"action": "finish", "answer_parts": [
        {"requested_information": "The source passages that were read", "context_ids": contexts}]}


class ScopedSyntheticAgentTests(unittest.TestCase):
    def setUp(self):
        fixture = test_query_scope.QueryScopeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.port = fixture.port
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.output = Path(temp.name) / "session"
        self.request = scoped_request(self.port, companies=["acme"], sources=["acme-2031"],
            question="What is Acme Services operating margin in 2031 Q2?", cutoff="2031-07-21")
        self.query = {"action": "query", "plan": {"calculations": [
            {"formula_id": "operating_margin", "entity_id": "acme-services", "periods": [
                {"kind": "quarter", "start": "2031-04-01", "end": "2031-06-30"}]}]}}

    def run_agent(self, actions, request=None, **limits):
        self.planner = ScriptedPlanner(actions)
        return asyncio.run(DataQueryAgent(self.port, self.planner, **limits).run_scoped(
            self.request if request is None else request, output=self.output))

    def test_required_scope_rejected_before_planning_or_creating_output(self):
        cases = [{"question": self.request["question"]},
                 {**self.request, "scope": None}]
        for field, value in (("company_ids", []), ("source_snapshot_ids", []),
                             ("source_snapshot_ids", [" "])):
            request = copy.deepcopy(self.request)
            request["scope"][field] = value
            cases.append(request)
        for request in cases:
            with self.subTest(request=request), self.assertRaises(ValidationError):
                self.run_agent([], request)
            self.assertEqual(self.planner.packets, [])
            self.assertFalse(self.output.exists())

    def test_company_and_source_scope_must_agree_before_planning(self):
        request = copy.deepcopy(self.request)
        request["scope"]["source_snapshot_ids"] = ["other-2030"]
        with self.assertRaisesRegex(ValueError, "company scope"):
            self.run_agent([], request)
        self.assertEqual(self.planner.packets, [])

    def test_scoped_query_returns_synthetic_calculation_without_other_company_catalog(self):
        def finish(packet):
            value = packet["history"][-1]["result"]
            return {"action": "finish", "answer_parts": [{
                "requested_information": "Operating margin",
                "computed_ids": [c["computed_id"] for c in value["computed_facts"]]}]}

        result = self.run_agent([self.query, finish])
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["agent_schema_version"], SCOPED_AGENT_VERSION)
        self.assertEqual(result["computed_facts"][0]["display_decimal"], "15.00")
        self.assertEqual({r["source_snapshot_id"] for r in result["records"]}, {"acme-2031"})
        self.assertEqual({s["source_snapshot_id"] for s in self.planner.packets[0]["catalog"]["sources"]},
                         {"acme-2031"})
        self.assertEqual({e["company_id"] for e in self.planner.packets[0]["catalog"]["entities"]}, {"acme"})

    def test_source_reporting_date_cannot_supply_missing_numeric_period(self):
        request = {**self.request, "question": "What is Acme Services operating margin?"}
        with patch.object(QueryDataPort, "query_data") as query:
            result = self.run_agent([self.query], request)
        query.assert_not_called()
        self.assertEqual(result["status"], "needs_clarification")
        self.assertFalse(result["records"] or result["computed_facts"])

    def test_all_source_tools_reject_cross_source_access_before_reading(self):
        actions = [
            {"action": "outline_source", "outline": {"source_snapshot_id": "other-2030"}},
            {"action": "read_source", "read": {"source_snapshot_id": "other-2030", "node_id": "root"}},
            {"action": "search_source", "search": {
                "source_snapshot_id": "other-2030", "node_id": "root", "phrase": "Revenue"}},
            {"action": "read_context", "context": {"source_snapshot_id": "other-2030", "block_id": "b"}},
        ]
        with patch.object(QueryDataPort, "_reader") as reader:
            result = self.run_agent(actions, max_steps=4)
        reader.assert_not_called()
        self.assertEqual(result["status"], "limited")
        self.assertEqual(len(self.planner.packets), 4)
        self.assertTrue(all(t["status"] == "invalid_plan" for t in result["trace"]))
        self.assertFalse(result["records"] or result["contexts"] or result["evidence"])

    def test_fabricated_context_reference_cannot_finish(self):
        action = {"action": "finish", "answer_parts": [
            {"requested_information": "Business", "context_ids": ["ctx-never-read"]}]}
        result = self.run_agent([action], max_steps=1)
        self.assertEqual(result["status"], "limited")
        self.assertEqual(result["answer_parts"], [])
        self.assertEqual(result["contexts"], [])


class ScopedRealSourceAgentTests(unittest.TestCase):
    def setUp(self):
        self.port = QueryDataPort(PILOT)
        self.addCleanup(self.port.close)
        self.source = next(s for s in self.port.sources
                           if s["company_id"] == "alphabet" and s["form"] == "10-K"
                           and s["period_end"] == "2025-12-31")
        self.sid = self.source["source_snapshot_id"]
        self.request = scoped_request(self.port, companies=["alphabet"], sources=[self.sid],
            question="Read the beginning of Business and locate 'Our mission' in the selected filing.",
            cutoff="2026-09-22")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.output = Path(temp.name) / "session"

    def run_agent(self, actions, **limits):
        self.planner = ScriptedPlanner(actions)
        return asyncio.run(DataQueryAgent(self.port, self.planner, **limits).run_scoped(
            self.request, output=self.output))

    @staticmethod
    def business_node(outline):
        return next(n for n in outline["nodes"] if n["kind"] == "item" and n["title"] == "Business")

    def first_read(self, packet):
        outline = packet["history"][-1]["result"]
        node = self.business_node(outline)
        return {"action": "read_source", "read": {
            "source_snapshot_id": self.sid, "node_id": node["node_id"], "count": 4}}

    def test_outline_read_continuation_search_finish_preserves_exact_blocks_and_audit(self):
        before = digest((PILOT / "manifest.json").read_bytes())

        def continue_read(packet):
            previous = packet["history"][-1]["result"]
            self.assertTrue(previous["next_cursor"])
            return {"action": "read_source", "read": {
                "source_snapshot_id": self.sid, "node_id": previous["node_id"],
                "cursor": previous["next_cursor"], "count": 4}}

        def search(packet):
            node = self.business_node(packet["history"][0]["result"])
            return {"action": "search_source", "search": {
                "source_snapshot_id": self.sid, "node_id": node["node_id"], "phrase": "Our mission"}}

        result = self.run_agent([
            {"action": "outline_source", "outline": {"source_snapshot_id": self.sid}},
            self.first_read, continue_read, search, finish_read_contexts,
        ], max_steps=5, max_packet_bytes=400000)
        self.assertEqual(result["status"], "answered")
        self.assertEqual([t["tool"] for t in result["trace"]],
                         ["outline_source", "read_source", "read_source", "search_source", "finish"])
        self.assertEqual(result["period_scope"]["periods"], [])
        self.assertEqual(len(result["contexts"]), 2)
        self.assertFalse(result["records"] or result["computed_facts"])
        first, second = result["contexts"]
        self.assertEqual(second["requested_start_block_id"], first["next_cursor"]["start_block_id"])
        self.assertFalse(first["node_complete"] or second["node_complete"])
        self.assertNotIn("context_id", self.planner.packets[1]["history"][0]["result"])
        search_result = self.planner.packets[-1]["history"][-1]["result"]
        self.assertTrue(search_result["hits"])
        self.assertNotIn("context_id", search_result)
        originals = {b["block_id"]: b for b in (
            json.loads(line) for line in (PILOT / self.source["index_folder"] / "blocks.jsonl").read_text().splitlines())}
        for context in result["contexts"]:
            self.assertEqual(context["source_snapshot_id"], self.sid)
            self.assertEqual(context["source_sha256"], self.source["source_sha256"])
            for block in context["blocks"]:
                self.assertEqual(block, originals[block["block_id"]])
        manifest = json.loads((self.output / "manifest.json").read_text())
        for name, expected in manifest["files"].items():
            self.assertEqual(digest((self.output / name).read_bytes()), expected)
        self.assertEqual(digest((PILOT / "manifest.json").read_bytes()), before)

    def test_outline_alone_does_not_register_evidence_context(self):
        def forge_finish(packet):
            outline = packet["history"][-1]["result"]
            self.assertNotIn("context_id", outline)
            return {"action": "finish", "answer_parts": [{"requested_information": "Business",
                "context_ids": [self.business_node(outline)["node_id"]]}]}

        result = self.run_agent([
            {"action": "outline_source", "outline": {"source_snapshot_id": self.sid}}, forge_finish], max_steps=2)
        self.assertEqual(result["status"], "limited")
        self.assertEqual(result["contexts"], [])
        self.assertEqual(result["answer_parts"], [])

    def test_search_preview_does_not_register_evidence_context(self):
        def search(packet):
            node = self.business_node(packet["history"][-1]["result"])
            return {"action": "search_source", "search": {
                "source_snapshot_id": self.sid, "node_id": node["node_id"], "phrase": "Our mission"}}

        def forge_finish(packet):
            value = packet["history"][-1]["result"]
            self.assertTrue(value["hits"])
            self.assertNotIn("context_id", value)
            return {"action": "finish", "answer_parts": [{"requested_information": "Mission",
                "context_ids": [value["hits"][0]["block_id"]]}]}

        result = self.run_agent([
            {"action": "outline_source", "outline": {"source_snapshot_id": self.sid}}, search, forge_finish], max_steps=3)
        self.assertEqual(result["status"], "limited")
        self.assertEqual(result["contexts"], [])

    def test_read_gap_is_referenceable_without_inventing_a_context(self):
        def finish_gap(packet):
            value = packet["history"][-1]["result"]
            self.assertEqual(value["status"], "node_missing")
            self.assertNotIn("context_id", value)
            return {"action": "finish", "answer_parts": [{"requested_information": "Missing chapter",
                "gap_ids": [g["gap_id"] for g in value["gaps"]]}]}

        result = self.run_agent([{"action": "read_source", "read": {
            "source_snapshot_id": self.sid, "node_id": "nonexistent-chapter"}}, finish_gap])
        self.assertEqual(result["status"], "unanswerable")
        self.assertEqual(result["contexts"], [])
        self.assertEqual(result["gaps"][0]["reason"], "node_missing")
        self.assertTrue(result["answer_parts"][0]["gap_ids"])

    def test_sdk_scoped_schema_and_text_tools_over_mock_http(self):
        requests = []

        def respond(http_request):
            body = json.loads(http_request.content)
            requests.append(body)
            packet = json.loads(body["messages"][-1]["content"])
            if not packet["history"]:
                decision = {"action": "outline_source", "outline": {"source_snapshot_id": self.sid}}
            elif len(packet["history"]) == 1:
                decision = self.first_read(packet)
            else:
                decision = finish_read_contexts(packet)
            return httpx.Response(200, json={"id": f"response-{len(requests)}",
                "object": "chat.completion", "created": 1, "model": "test-deepseek",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {
                    "role": "assistant", "content": json.dumps(decision)}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}})

        root = self.output.parent
        budget = RunBudget(root / "mock-budget.sqlite", "1")

        async def execute():
            async with AsyncOpenAI(api_key="test-key", base_url="https://api.deepseek.com", max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))) as client:
                model = DeepSeekChatCompletionsModel(model="deepseek-flash", openai_client=client)
                metered = MeteredModel(model, root / "calls", "scoped-planner", "deepseek", "deepseek-flash",
                                      pricing_snapshot("deepseek", "deepseek-flash"), budget)
                return await DataQueryAgent(self.port, SdkQueryPlanner(metered, scoped=True)).run_scoped(
                    self.request, output=self.output)

        result = asyncio.run(execute())
        self.assertEqual(result["status"], "answered")
        self.assertEqual(len(result["contexts"]), 1)
        self.assertEqual(len(requests), 3)
        self.assertEqual(summarize(root / "calls")["unknown_cost_requests"], 0)
        self.assertEqual(budget.summary()["requests"], 3)
        for body in requests:
            self.assertEqual(body["response_format"], {"type": "json_object"})
            self.assertEqual(body["thinking"], {"type": "disabled"})
            self.assertIn("ScopedPlannerDecision", body["messages"][0]["content"])
        self.assertIn("context_id", requests[-1]["messages"][-1]["content"])


class ScopedSyntheticDocumentAgentTests(unittest.TestCase):
    def test_oversized_query_context_is_a_gap_and_cannot_supply_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp) / "dataset"
            dataset.mkdir()
            make_scoped_dataset(dataset)
            with QueryDataPort(dataset) as port:
                source = next(s for s in port.sources if s["source_snapshot_id"] == "acme-annual")
                reader = port._reader(source)
                # Enlarge only the cached test paragraph, never the frozen fixture.
                reader.blocks[1] = {**reader.blocks[1], "text": "products " + "x" * 90000}
                request = scoped_request(port, companies=["acme"], sources=["acme-annual"],
                    question="FY2031 products disclosure", cutoff="2032-06-01")

                def finish_gap(packet):
                    value = packet["history"][-1]["result"]
                    context = value["documents"][0]["contexts"][0]
                    self.assertEqual(context["status"], "context_too_large")
                    self.assertEqual(context["blocks"], [])
                    self.assertNotIn("context_id", context)
                    self.assertEqual(value["contexts"], [])
                    return {"action": "finish", "answer_parts": [{
                        "requested_information": "Products disclosure exceeds the response limit",
                        "gap_ids": [g["gap_id"] for g in value["gaps"]]}]}

                planner = ScriptedPlanner([{"action": "query", "plan": {"documents": [{
                    "company_id": "acme", "form": "10-K", "period_end": "2031-12-31",
                    "phrase": "products"}]}}, finish_gap])
                result = asyncio.run(DataQueryAgent(port, planner).run_scoped(
                    request, output=Path(tmp) / "session"))
                self.assertEqual(result["status"], "unanswerable")
                self.assertEqual(result["contexts"], [])
                self.assertFalse(result["records"] or result["computed_facts"] or result["evidence"])
                self.assertTrue(result["answer_parts"][0]["gap_ids"])

    def test_two_explicit_companies_with_colliding_block_ids_keep_distinct_contexts(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp) / "dataset"
            dataset.mkdir()
            make_scoped_dataset(dataset)
            with QueryDataPort(dataset) as port:
                request = scoped_request(port, companies=["acme", "other"],
                    sources=["acme-annual", "other-annual"],
                    question="Read each selected company's Business chapter.", cutoff="2032-06-01")
                planner = ScriptedPlanner([
                    {"action": "read_source", "read": {
                        "source_snapshot_id": sid, "node_id": "business", "count": 3}}
                    for sid in ("acme-annual", "other-annual")
                ] + [finish_read_contexts])
                result = asyncio.run(DataQueryAgent(port, planner).run_scoped(
                    request, output=Path(tmp) / "session"))
                self.assertEqual(result["status"], "answered")
                self.assertEqual(len(result["contexts"]), 2)
                first, second = result["contexts"]
                self.assertEqual(first["block_ids"], second["block_ids"])
                self.assertNotEqual(first["context_id"], second["context_id"])
                self.assertEqual(first["source_snapshot_id"], "acme-annual")
                self.assertEqual(second["source_snapshot_id"], "other-annual")
                self.assertEqual(first["blocks"][1]["text"], "acme sales from products.")
                self.assertEqual(second["blocks"][1]["text"], "other sales from products.")
                self.assertTrue(first["node_complete"] and second["node_complete"])
                self.assertEqual(result["period_scope"]["periods"], [])


class ScopedContractCompatibilityTests(unittest.TestCase):
    def test_old_storage_schemas_and_legacy_agent_actions_stay_unchanged(self):
        for name, model in (("query", DataQuery), ("record", ResearchRecord), ("result", QueryResult)):
            with self.subTest(schema=name):
                expected = json.loads((PILOT / "schemas" / f"{name}.schema.json").read_text())
                self.assertEqual(export_query_schema(model, version=VERSION), expected)
        self.assertEqual(AGENT_VERSION, "data-agent-query-v0.2")
        self.assertEqual(SCOPED_AGENT_VERSION, "data-agent-query-v0.3")
        self.assertNotIn("scope", AgentQuery.model_fields)
        with self.assertRaises(ValidationError):
            PlannerDecision.model_validate({"action": "outline_source", "outline": {"source_snapshot_id": "s"}})
        decision = ScopedPlannerDecision.model_validate({
            "action": "outline_source", "outline": {"source_snapshot_id": "s"}})
        self.assertEqual(decision.action, "outline_source")
        self.assertIn("scope", ScopedAgentQuery.model_fields)


if __name__ == "__main__":
    unittest.main()
