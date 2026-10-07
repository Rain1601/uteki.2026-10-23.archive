"""Real local runner and accounting, with all HTTP replaced by MockTransport."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx2 as httpx
from agents.exceptions import ModelBehaviorError
from lxml import html
from pydantic import ValidationError

from apps.review_workbench.data import agent_runs_live
from uteki.agents.business_map import product_run as run
from uteki.agents.business_map import product_wire
from uteki.agents.runtime.run_budget import BudgetExceeded


PROJECT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("business_revenue_cli", PROJECT / "scripts/run_business_revenue_agent.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class BusinessRevenueRunTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.requests = []
        self.clients = []
        self.company, self.period = "lyra-tools", "2023-09-30"
        self.document = "lyra-filing-2023"
        source = '''<!doctype html><html><head><meta charset="utf-8"></head><body>
<p id="business">Lyra Tools supplies licensed tools and support services.</p>
<p id="unit">Revenue by type (in millions).</p>
<p id="currency">All amounts are in US dollars.</p>
<table id="table"><tr><th id="label">Revenue</th><td id="old-header" colspan="2">2022</td><td id="header" colspan="2">2023</td></tr>
<tr><td id="a-label">Licenses</td><td id="a-old-symbol">$</td><td id="a-old">30</td><td id="a-symbol">$</td><td id="a">60</td></tr>
<tr><td id="b-label">Services</td><td id="b-old-symbol">$</td><td id="b-old">20</td><td id="b-symbol">$</td><td id="b">40</td></tr>
<tr><td id="total-label">Total</td><td id="total-old-symbol">$</td><td id="total-old">50</td><td id="total-symbol">$</td><td id="total">100</td></tr></table>
</body></html>'''
        self.source = self.root / "source.html"
        self.source.write_text(source)
        dom = html.fromstring(self.source.read_bytes())
        tree = dom.getroottree()
        def source_item(eid):
            element = dom.get_element_by_id(eid)
            text = " ".join("".join(element.itertext()).split())
            return {"id": eid, "source_dom_path": tree.getpath(element), "text": text,
                    "text_sha256": hashlib.sha256(text.encode()).hexdigest()}
        blocks = [{**source_item(eid), "ordinal": ordinal, "section_path": ["Synthetic filing"]}
                  for ordinal, eid in enumerate(("business", "unit", "currency", "table"), 1)]
        positions = [("label", 0, 0, 1), ("old-header", 0, 1, 2), ("header", 0, 3, 2)]
        for ri, prefix in enumerate(("a", "b", "total"), 1):
            positions.extend((eid, ri, ci, 1) for ci, eid in enumerate(
                (prefix + "-label", prefix + "-old-symbol", prefix + "-old", prefix + "-symbol", prefix)))
        cells = [{**source_item(eid), "row_index": ri, "column_index": ci, "rowspan": 1, "colspan": cs}
                 for eid, ri, ci, cs in positions]
        self.packet = {"company_id": self.company, "document_id": self.document, "period_end": self.period,
                       "requested_period_label": "2023", "financial_currency": "USD", "financial_unit": "million",
                       "source_local_path": "source.html", "source_url": "https://example.invalid/lyra-2023",
                       "source_sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
                       "blocks": blocks, "tables": [{"id": "revenue-table", "block_id": "table",
                           "source_dom_path": source_item("table")["source_dom_path"], "cells": cells}]}
        self.packet_path = self.root / "source_packet.json"
        self.write_packet()
        self.skill_path = self.root / "SKILL.md"
        self.skill_text = "---\nname: synthetic-skill\ndescription: Independent test skill.\n---\nSKILL_UNIQUE_MARKER: Keep business and revenue separate.\n"
        self.skill_path.write_text(self.skill_text)
        self.draft = {"company_id": self.company, "document_id": self.packet["document_id"], "period_end": self.period,
                      "schema_version": "business-revenue-draft-v2", "relationship_absence": "unknown",
                      "summary": "Synthetic source-grounded candidate.",
                      "businesses": [{"id": "issuer", "name": "Lyra Tools", "kind": "company",
                          "description": "Tool and service supplier", "evidence_block_ids": ["business"]}],
                      "relationships": [], "unknowns": [], "revenue_charts": [{"id": "types", "title": "Revenue by type",
                          "denominator_label": "Total revenue", "chart_type": "donut", "total_cell_id": "total",
                          "unit_block_id": "unit", "currency_block_id": "currency", "period_header_cell_id": "header",
                          "parts": [{"id": "licenses", "label": "Licenses", "amount_cell_id": "a"},
                                    {"id": "services", "label": "Services", "amount_cell_id": "b"}],
                          "adjustments": [], "reported_subtotals": []}]}
        self.draft['businesses'][0]['claim_evidence'] = [
            dict(field=field, item_index=None, excerpts=[dict(block_id='business', quote=self.packet['blocks'][0]['text'])])
            for field in ('name', 'description')]
        self.response_text = json.dumps(self.draft)
        self.stop_reason = "end_turn"
        self.transport_error = False
        self.env = patch.dict(os.environ, {"AIHUBMIX_API_KEY": "offline-test-key"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def write_packet(self):
        self.packet_path.write_text(json.dumps(self.packet))

    def prepare(self, **overrides):
        options = dict(model="claude-sonnet-5-5", effort="high", max_tokens=3000, timeout_seconds=30)
        options.update(overrides)
        prepared = run.prepare(root=self.root, packet_path=self.packet_path, skill_path=self.skill_path,
            company_id=self.company, document_id=self.document, period_end=self.period,
            **options)
        prepared["native"]._client_factory = self.client_factory
        return prepared

    def client_factory(self, **kwargs):
        kwargs["transport"] = httpx.MockTransport(self.respond)
        client = httpx.AsyncClient(**kwargs)
        self.clients.append(client)
        return client

    def respond(self, request):
        self.requests.append(request)
        if self.transport_error:
            raise httpx.ConnectError("mock transport error", request=request)
        return httpx.Response(200, json={"id": "msg_fixture", "model": "claude-sonnet-5-5",
            "stop_reason": self.stop_reason, "usage": {"input_tokens": 120, "output_tokens": 80},
            "content": [{"type": "text", "text": self.response_text}]}, headers={"request-id": "req_fixture"})

    async def execute(self, prepared=None, *, name="run", budget="1"):
        return await run.execute(prepared or self.prepare(), root=self.root, output=self.root/name,
                                 observation_root=self.root/"observations", budget_limit_usd=budget)

    def test_prepare_freezes_real_skill_schema_and_only_explicit_source(self):
        prepared = self.prepare()
        body = json.loads(prepared["request"])
        self.assertIn(self.skill_text, body["system"])
        self.assertEqual(json.loads(body["messages"][0]["content"]), self.packet)
        self.assertEqual(prepared["manifest"]["skill_sha256"], hashlib.sha256(self.skill_path.read_bytes()).hexdigest())
        self.assertEqual(body["thinking"], {"type": "adaptive"})
        self.assertFalse(body["stream"])
        self.assertNotIn("temperature", body)
        self.assertNotIn("Structural example:", body["system"])
        self.assertEqual(prepared["manifest"]["implementation_sha256"], run.implementation_hashes())
        self.assertEqual(prepared['manifest']['output_contract_version'], 'business-revenue-draft-v2')
        self.assertEqual(self.requests, [])

    def test_stream_is_opt_in_and_frozen_request_cannot_change_after_preparation(self):
        default = self.prepare()
        nonstream = self.prepare(stream=False)
        streamed = self.prepare(stream=True)
        self.assertEqual(default["request"], nonstream["request"])
        original = json.loads(default["request"])
        streamed_body = json.loads(streamed["request"])
        self.assertIs(streamed_body.pop("stream"), True)
        self.assertIs(original.pop("stream"), False)
        self.assertEqual(streamed_body, original)
        self.assertNotEqual(default["manifest"]["request_sha256"], streamed["manifest"]["request_sha256"])
        for prepared, new_value in ((default, True), (streamed, False)):
            run.verify_prepared(prepared)
            prepared["native"].stream = new_value
            with self.assertRaisesRegex(ValueError, "prepared_request_changed"):
                run.verify_prepared(prepared)
        self.assertEqual(self.requests, [])

    def test_prepare_stream_accepts_explicit_600_second_timeout_and_captures_configuration(self):
        prepared = self.prepare(stream=True, timeout_seconds=600)
        run.verify_prepared(prepared)
        fields = prepared["native"].request_configuration(**prepared["kwargs"])["fields"]
        self.assertEqual(fields["stream"], {"value": True, "status": "explicit", "source": "http_request"})
        self.assertEqual(fields["timeout_seconds"], {"value": 600, "status": "explicit", "source": "http_request"})
        with self.assertRaisesRegex(ValueError, "timeout"):
            self.prepare(timeout_seconds=600)
        self.assertEqual(self.requests, [])

    def test_cli_stream_flag_is_explicit_and_preflight_makes_no_request(self):
        args = ["business-revenue", "--root", str(self.root), "--packet", str(self.packet_path),
                "--skill", str(self.skill_path), "--company-id", self.company,
                "--document-id", self.document, "--period-end", self.period,
                "--model", "claude-sonnet-5-5", "--effort", "high", "--max-tokens", "3000"]
        for enabled in (False, True):
            output = self.root / f"cli-stream-{enabled}.json"
            timeout = 600 if enabled else 30
            argv = [*args, "--timeout-seconds", str(timeout), "--preflight-output", str(output),
                    *(["--stream"] if enabled else [])]
            with patch("sys.argv", argv), patch("builtins.print"), patch.object(cli, "prepare", wraps=run.prepare) as mocked:
                cli.main()
            self.assertIs(mocked.call_args.kwargs["stream"], enabled)
            self.assertEqual(mocked.call_args.kwargs["timeout_seconds"], timeout)
            body = json.loads(output.with_suffix(".request.json").read_bytes())
            self.assertIs(body["stream"], enabled)
        self.assertEqual(self.requests, [])

    def test_explicit_legacy_request_preserves_frozen_sonnet_payload_bytes(self):
        frozen = PROJECT / "experiments/agent_design/2026-10-07-agent-business-revenue-v1/run-01"
        packet = json.loads((frozen / "source_packet.json").read_text())
        prepared = run.prepare(root=PROJECT, packet_path=frozen / "source_packet.json",
            skill_path=frozen / "skill.md", **{key: packet[key] for key in ("company_id", "document_id", "period_end")},
            model="claude-sonnet-5-5", effort="high", max_tokens=16000, timeout_seconds=300,
            contract_version='business-revenue-draft-v1')
        self.assertEqual(prepared["request"], (frozen / "request.json").read_bytes())
        run.verify_prepared(prepared)
        self.assertEqual(self.requests, [])

    async def test_compact_wire_is_explicit_lossless_and_keeps_full_packet_for_evidence(self):
        prepared = self.prepare(wire_mode='compact-v1')
        run.verify_prepared(prepared)
        wire = json.loads(prepared['kwargs']['input'])
        self.assertEqual(product_wire.expand_compact(wire), product_wire.semantic_projection(self.packet))
        self.assertEqual(prepared['packet'], self.packet)
        self.assertEqual(prepared['packet_raw'], self.packet_path.read_bytes())
        self.assertEqual(prepared['manifest']['source_wire_sha256'], run.digest(prepared['kwargs']['input'].encode()))
        self.assertIn(product_wire.INSTRUCTIONS, prepared['kwargs']['system_instructions'])
        result = await self.execute(prepared)
        self.assertEqual(result['status'], 'candidate')
        self.assertEqual((self.root/'run/source_packet.json').read_bytes(), self.packet_path.read_bytes())
        self.assertEqual((self.root/'run/source_wire.json').read_text(), prepared['kwargs']['input'])
        self.assertEqual(len(self.requests), 1)  # Mock transport; no provider call.

    def test_compact_wire_and_manifest_tampering_fail_before_call(self):
        for change in ('scope', 'text', 'mode', 'hash', 'missing_hash'):
            prepared = self.prepare(wire_mode='compact-v1')
            if change in ('scope', 'text'):
                body = json.loads(prepared['kwargs']['input'])
                if change == 'scope':
                    body['scope']['company_id'] = 'another-issuer'
                else:
                    body['tables'][0]['cells'][-1][1] = '999'
                prepared['kwargs']['input'] = json.dumps(body, ensure_ascii=False, separators=(',', ':'))
            elif change == 'mode':
                prepared['manifest']['source_wire_mode'] = 'full'
            elif change == 'hash':
                prepared['manifest']['source_wire_sha256'] = '0' * 64
            else:
                del prepared['manifest']['source_wire_sha256']
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'wire'):
                run.verify_prepared(prepared)
        self.assertEqual(self.requests, [])

    def test_packet_scope_original_source_and_cell_geometry_are_checked_before_call(self):
        cases = [
            (lambda p: p.update(company_id="other"), "caller_packet_scope"),
            (lambda p: p.update(period_end="2022-09-30"), "caller_packet_scope"),
            (lambda p: p.update(document_id="another-document"), "caller_packet_scope"),
            (lambda p: p.pop("financial_currency"), "explicit_usd_million"),
            (lambda p: p.update(financial_currency="EUR"), "explicit_usd_million"),
            (lambda p: p.update(financial_unit="billion"), "explicit_usd_million"),
            (lambda p: p.update(requested_period_label=""), "explicit_requested_period_label"),
            (lambda p: p.update(source_sha256="0" * 64), "source_hash_mismatch"),
            (lambda p: p["blocks"][0].update(source_dom_path="/html/body/missing"), "source_dom_missing"),
            (lambda p: p["tables"][0]["cells"][2].update(column_index=4), "geometry_mismatch"),
            (lambda p: p["tables"][0]["cells"][2].update(rowspan=2), "geometry_mismatch"),
            (lambda p: p["tables"][0]["cells"].pop(), "geometry_mismatch"),
            (lambda p: p["tables"][0].update(block_id="business"), "source_table_missing"),
            (lambda p: p["tables"][0]["cells"].append(dict(p["tables"][0]["cells"][0], id="duplicate-path")), "duplicate_source_cell_dom_path"),
        ]
        original = copy.deepcopy(self.packet)
        for mutate, message in cases:
            self.packet = copy.deepcopy(original)
            mutate(self.packet)
            self.write_packet()
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.prepare()
        self.assertEqual(self.requests, [])

    def test_optional_manifest_hash_and_source_identity_are_checked(self):
        path = self.root / "source-manifest.json"
        manifest = {"document_id": self.packet["document_id"], "period_end": self.period,
                    "source_url": self.packet["source_url"], "content_sha256": self.packet["source_sha256"],
                    "source_snapshot_id": "lyra-frozen", "company": "Lyra Tools Legal Name"}
        self.packet["source_snapshot_id"] = "lyra-frozen"
        def freeze(value):
            path.write_text(json.dumps(value))
            self.packet["source_manifest"] = {"local_path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            self.write_packet()
        freeze(manifest)
        self.prepare()
        for field in ("document_id", "period_end", "source_url", "content_sha256", "source_snapshot_id"):
            bad = dict(manifest, **{field: "wrong"})
            freeze(bad)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "source_manifest_(scope|snapshot)_mismatch"):
                self.prepare()
        freeze(manifest)
        path.write_text(path.read_text() + " ")
        with self.assertRaisesRegex(ValueError, "source_manifest_hash_mismatch"):
            self.prepare()

    async def test_real_runner_materializes_other_issuer_and_persists_call_and_trace(self):
        prepared = self.prepare()
        result = await self.execute(prepared)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0].content, prepared["request"])
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(result["budget"]["requests"], 1)
        self.assertEqual(result["costs"]["unknown_cost_requests"], 0)
        business = json.loads((self.root/"run/business_map.json").read_text())
        revenue = json.loads((self.root/"run/revenue.json").read_text())
        self.assertEqual(business["company_id"], self.company)
        self.assertEqual(business['schema_version'], 'business-map-v0.2')
        self.assertEqual(business['relationship_absence'], 'unknown')
        self.assertEqual(len(business['businesses'][0]['claim_evidence']), 2)
        self.assertEqual(business['evidence'][0]['company_id'], self.company)
        self.assertEqual(business["metadata"]["extraction_method"], "system_agent")
        self.assertEqual(business["metadata"]["period_end"], self.period)
        self.assertEqual([p["value"] for p in revenue["charts"][0]["parts"]], [60, 40])
        self.assertEqual((self.root/"run/skill.md").read_text(), self.skill_text)
        events = [json.loads(p.read_text()) for p in (self.root/"observations").glob("*/events/*.json")]
        self.assertTrue(any(e["type"] == "model_call.started" for e in events))
        self.assertTrue(any(e["type"] == "run.finished" for e in events))
        for name, fingerprint in result["artifacts_sha256"].items():
            self.assertEqual(fingerprint, hashlib.sha256((self.root/"run"/name).read_bytes()).hexdigest())
        visible = agent_runs_live.load_run(self.root/"observations", result["trace_id"], output_roots=(self.root,))
        self.assertEqual([step["action"] for step in visible["steps"]], [
            "核验冻结原文与加载 Skill", "Claude 选择业务与收入项目",
            "格式、范围、出处与金额勾稽校验", "生成业务与收入候选产物"])
        self.assertTrue(self.clients[0].is_closed)

    async def test_changed_prepared_request_or_skill_never_dispatches_and_saves_failure(self):
        for index, change in enumerate((lambda p: p["kwargs"].update(input='{"changed":true}'),
                                        lambda p: p.update(skill="changed Skill"),
                                        lambda p: p.update(request=b"changed request"),
                                        lambda p: p["manifest"].update(implementation_sha256={}))):
            prepared = self.prepare()
            change(prepared)
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, "prepared_"):
                await self.execute(prepared, name=f"rejected-{index}")
            result = json.loads((self.root/f"rejected-{index}/result.json").read_text())
            self.assertEqual(result["status"], "failed")
            self.assertIsNone(result["budget"])
        self.assertEqual(self.requests, [])

    async def test_source_changed_after_prepare_is_rechecked_before_budget_or_http(self):
        prepared = self.prepare()
        self.source.write_text(self.source.read_text() + "<!-- changed -->")
        with self.assertRaisesRegex(ValueError, "source_hash_mismatch"):
            await self.execute(prepared)
        result = json.loads((self.root/"run/result.json").read_text())
        self.assertIsNone(result["budget"])
        self.assertEqual(self.requests, [])

    async def test_insufficient_or_invalid_budget_has_zero_calls_and_saved_failure(self):
        with self.assertRaises(BudgetExceeded):
            await self.execute(budget="0.000001")
        result = json.loads((self.root/"run/result.json").read_text())
        self.assertEqual(result["budget"]["requests"], 0)
        self.assertEqual(result["costs"]["requests"], 0)
        with self.assertRaises(ValueError):
            await self.execute(name="invalid-budget", budget="0")
        invalid = json.loads((self.root/"invalid-budget/result.json").read_text())
        self.assertIsNone(invalid["budget"])
        self.assertEqual(self.requests, [])

    async def test_incomplete_or_invalid_answer_preserves_response_and_known_usage(self):
        for name, stop, text, error in (("truncated", "max_tokens", '{"partial":', ModelBehaviorError),
                                        ("invalid", "end_turn", '{"invalid":true}', ValueError)):
            self.stop_reason, self.response_text = stop, text
            with self.subTest(name=name), self.assertRaises(error):
                await self.execute(name=name)
            result = json.loads((self.root/name/"result.json").read_text())
            self.assertEqual(result["status"], "failed")
            self.assertEqual((self.root/name/"response.txt").read_text(), text)
            self.assertEqual(result["costs"]["requests"], 1)
            self.assertEqual(result["costs"]["unknown_cost_requests"], 0)
            self.assertFalse((self.root/name/"business_map.json").exists())
        self.assertEqual(len(self.requests), 2)

    async def test_new_execution_rejects_legacy_output_instead_of_silent_downgrade(self):
        legacy = copy.deepcopy(self.draft)
        legacy.pop('schema_version')
        legacy.pop('relationship_absence')
        legacy['businesses'][0].pop('claim_evidence')
        self.response_text = json.dumps(legacy)
        with self.assertRaisesRegex(ValueError, 'product_contract_version_mismatch'):
            await self.execute()
        self.assertFalse((self.root/'run/business_map.json').exists())
        self.assertEqual(len(self.requests), 1)

    async def test_transport_failure_preserves_unknown_cost_without_retry(self):
        self.transport_error = True
        with self.assertRaises(RuntimeError):
            await self.execute()
        result = json.loads((self.root/"run/result.json").read_text())
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(result["budget"]["unknown_requests"], 1)
        self.assertEqual(result["costs"]["unknown_cost_requests"], 1)
        self.assertTrue(self.clients[0].is_closed)

    async def test_output_and_observation_paths_fail_without_call(self):
        prepared = self.prepare()
        for output, observation in ((self.root/"run", None), (self.root, self.root/"observations"),
                                    (self.root/"run", self.root/"run/observations")):
            with self.subTest(output=output, observation=observation), self.assertRaises(ValueError):
                await run.execute(prepared, root=self.root, output=output, observation_root=observation, budget_limit_usd="1")
        self.assertEqual(self.requests, [])

    def test_preflight_snapshots_are_reviewable_idempotent_and_not_overwritten(self):
        prepared = self.prepare()
        target = self.root/"preflight.json"
        cli.save_preflight(prepared, target)
        paths = [target, self.root/"preflight.request.json", self.root/"preflight.skill.md", self.root/"preflight.output-schema.json"]
        before = {p: p.read_bytes() for p in paths}
        cli.save_preflight(prepared, target)
        self.assertEqual(before, {p: p.read_bytes() for p in paths})
        self.assertEqual((self.root/"preflight.request.json").read_bytes(), prepared["request"])
        changed = dict(prepared, skill="changed")
        with self.assertRaisesRegex(ValueError, "preflight_changed_use_new_path"):
            cli.save_preflight(changed, target)
        self.assertEqual(before, {p: p.read_bytes() for p in paths})
        self.assertEqual(self.requests, [])

    def test_selected_real_packet_passes_source_manifest_dom_and_geometry_only(self):
        path = PROJECT/"experiments/agent_design/2026-10-07-agent-business-revenue-v1/input/source_packet.json"
        packet = json.loads(path.read_text())
        raw = run.verify_packet(packet, PROJECT, **{k:packet[k] for k in ("company_id", "document_id", "period_end")})
        self.assertEqual(hashlib.sha256(raw).hexdigest(), packet["source_sha256"])
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
