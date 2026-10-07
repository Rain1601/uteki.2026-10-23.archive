"""Offline only: real Agents SDK over mock HTTP; no provider requests."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx2 as httpx
from openai import AsyncOpenAI

from scripts import smoke_aihubmix as smoke


class AiHubMixSmokeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.output = self.root / "probe"
        self.clients, self.requests = [], []
        self.enterContext(patch.dict("os.environ", {"AIHUBMIX_API_KEY": "offline-probe-key"}))
        self.credentials = self.enterContext(patch.object(smoke, "load_provider_key", return_value="offline_fixture"))

    def transport(self, handler):
        def factory(**kwargs):
            self.assertEqual(kwargs["max_retries"], 0)
            client = AsyncOpenAI(**kwargs,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
            self.clients.append(client)
            return client
        return self.enterContext(patch.object(smoke, "AsyncOpenAI", side_effect=factory))

    def execute(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = smoke.main(["--model", "gpt-5.4-mini", "--output-dir", str(self.output)])
        return status, json.loads(stdout.getvalue()), stdout.getvalue() + stderr.getvalue()

    def respond(self, request, *, call_tool=True, wrong_code=False):
        body = json.loads(request.content)
        self.requests.append(body)
        if call_tool and len(self.requests) == 1:
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "offline-tool", "type": "function",
                "function": {"name": "probe", "arguments": "{}"}}]}
            finish = "tool_calls"
        else:
            tool_results = [m["content"] for m in body["messages"] if m["role"] == "tool"]
            code = tool_results[-1] if tool_results and not wrong_code else "wrong-code"
            message = {"role": "assistant", "content": json.dumps({"code": code})}
            finish = "stop"
        return httpx.Response(200, json={"id": "offline-response", "object": "chat.completion",
            "created": 1, "model": "gpt-5.4-mini",
            "choices": [{"index": 0, "finish_reason": finish, "message": message}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})

    def test_missing_credential_stops_before_client_or_network(self):
        self.credentials.side_effect = ValueError("credential-secret-must-not-appear")
        client = self.transport(self.respond)
        status, report, captured = self.execute()
        self.assertEqual(status, 1)
        self.assertEqual(report["failure_stage"], "credentials")
        self.assertEqual(report["costs"]["requests"], 0)
        client.assert_not_called()
        self.assertFalse((self.output / "budget.sqlite").exists())
        self.assertNotIn("credential-secret", captured + (self.output / "result.json").read_text())

    def test_tool_and_structured_output_succeed_and_close_client(self):
        self.transport(self.respond)
        status, report, captured = self.execute()
        self.assertEqual(status, 0, report)
        self.assertTrue(report["success"])
        self.assertTrue(report["code_matches"])
        self.assertEqual(report["tool_call_count"], 1)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(report["costs"]["requests"], 2)
        self.assertEqual(report["budget"]["requests"], 2)
        self.assertEqual(report["costs"]["unknown_cost_requests"], 0)
        self.assertTrue(all(client.is_closed() for client in self.clients))
        self.assertEqual(self.requests[0]["response_format"]["type"], "json_schema")
        artifacts = "".join(p.read_text() for p in self.output.rglob("*.json"))
        self.assertNotIn("offline-probe-key", artifacts + captured)
        self.assertEqual(json.loads((self.output / "result.json").read_text()), report)

    def test_structured_output_without_tool_invocation_cannot_pass(self):
        self.transport(lambda request: self.respond(request, call_tool=False))
        status, report, _ = self.execute()
        self.assertEqual(status, 1)
        self.assertEqual(report["error_type"], "ToolNotCalled")
        self.assertEqual(report["tool_call_count"], 0)
        self.assertTrue(all(client.is_closed() for client in self.clients))

    def test_actual_tool_call_with_wrong_output_cannot_pass(self):
        self.transport(lambda request: self.respond(request, wrong_code=True))
        status, report, _ = self.execute()
        self.assertEqual(status, 1)
        self.assertEqual(report["error_type"], "OutputMismatch")
        self.assertTrue(report["tool_called"])
        self.assertFalse(report["code_matches"])

    def test_api_failure_is_redacted_recorded_and_nonzero(self):
        def fail(request):
            self.requests.append(request)
            return httpx.Response(401, json={"error": {"message": "raw-api-secret-must-not-appear",
                "type": "authentication_error", "code": "invalid_api_key"}})
        self.transport(fail)
        status, report, captured = self.execute()
        self.assertEqual(status, 1)
        self.assertEqual(report["error_type"], "AuthenticationError")
        self.assertEqual(report["http_status"], 401)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(report["costs"]["unknown_cost_requests"], 1)
        self.assertEqual(report["budget"]["unknown_requests"], 1)
        self.assertTrue(all(client.is_closed() for client in self.clients))
        artifacts = "".join(p.read_text() for p in self.output.rglob("*.json"))
        self.assertNotIn("raw-api-secret", captured + artifacts)
        self.assertNotIn("offline-probe-key", captured + artifacts)

    def test_existing_output_is_never_overwritten(self):
        self.output.mkdir()
        original = self.output / "result.json"
        original.write_text("preserve-this-run")
        client = self.transport(self.respond)
        status, report, _ = self.execute()
        self.assertEqual(status, 1)
        self.assertEqual(report["error_type"], "FileExistsError")
        self.assertEqual(original.read_text(), "preserve-this-run")
        self.credentials.assert_not_called()
        client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
