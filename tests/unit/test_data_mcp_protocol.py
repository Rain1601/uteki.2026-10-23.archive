"""Protocol checks use an independent synthetic service, not financial gold data."""

from __future__ import annotations

import asyncio
import sys
import unittest
from unittest.mock import AsyncMock

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from uteki.interfaces.data_mcp.client import dispatch


_FIXTURE_SERVER = '''
import sys
import types
from pydantic import BaseModel, ConfigDict
from uteki.interfaces.data_mcp.server import create_server

class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company: str

module = types.ModuleType("uteki.interfaces.data_mcp.service")
for name in ("DiscoverRequest", "SchemaRequest", "FactsRequest", "SourceRequest"):
    setattr(module, name, Request)
sys.modules[module.__name__] = module

class Service:
    def discover_data(self, request):
        if request.company == "unknown":
            raise ValueError("unknown_company: select a registered company")
        return {"company": request.company, "read_only": True, "state": "candidate"}
    def get_data_schema(self, request):
        return {"company": request.company, "metrics": []}
    def query_facts(self, request):
        if request.company == "broken":
            raise RuntimeError("SECRET /private/host/data.sqlite")
        return {"company": request.company, "facts": [], "gap": "no_financial_coverage"}
    def read_source(self, request):
        return {"company": request.company, "text": "Synthetic source evidence"}

create_server(Service()).run(transport="stdio")
'''


class DataMCPProtocolTests(unittest.TestCase):
    def test_stdio_tools_are_typed_readonly_and_keep_company_scope(self):
        async def exercise():
            parameters = StdioServerParameters(command=sys.executable, args=["-c", _FIXTURE_SERVER])
            async with stdio_client(parameters) as streams:
                async with ClientSession(*streams, read_timeout_seconds=15) as session:
                    initialization = await session.initialize()
                    self.assertEqual(initialization.server_info.name, "uteki-data")
                    listed = await session.list_tools()
                    self.assertEqual({tool.name for tool in listed.tools}, {
                        "discover_data", "get_data_schema", "query_facts", "read_source",
                    })
                    for tool in listed.tools:
                        self.assertTrue(tool.annotations.read_only_hint)
                        self.assertFalse(tool.annotations.destructive_hint)
                        self.assertFalse(tool.annotations.open_world_hint)
                        self.assertEqual(tool.input_schema["required"], ["request"])
                    for company in ("Synthetic A", "Synthetic B"):
                        response = await dispatch(session, {
                            "method": "tools/call", "params": {
                                "name": "discover_data", "arguments": {"request": {"company": company}},
                            },
                        })
                        self.assertEqual(response["result"]["structuredContent"]["company"], company)
                        self.assertEqual(response["result"]["structuredContent"]["state"], "candidate")
                    missing = await session.call_tool("discover_data", {"request": {}})
                    self.assertTrue(missing.is_error)
                    extra = await session.call_tool("discover_data", {"request": {"company": "A", "path": "/private/data"}})
                    self.assertTrue(extra.is_error)
                    unknown = await session.call_tool("discover_data", {"request": {"company": "unknown"}})
                    self.assertTrue(unknown.is_error)
                    self.assertIn("unknown_company", str(unknown.content))
                    broken = await session.call_tool("query_facts", {"request": {"company": "broken"}})
                    self.assertTrue(broken.is_error)
                    self.assertIn("data_service_error", str(broken.content))
                    self.assertNotIn("SECRET", str(broken.content))
                    self.assertNotIn("/private/host", str(broken.content))
                    gap = await session.call_tool("query_facts", {"request": {"company": "Synthetic B"}})
                    self.assertFalse(gap.is_error)
                    self.assertEqual(gap.structured_content["facts"], [])
                    self.assertEqual(gap.structured_content["gap"], "no_financial_coverage")

        asyncio.run(exercise())

    def test_bridge_rejects_nonquery_methods_and_malformed_envelopes(self):
        async def exercise():
            session = AsyncMock(spec=ClientSession)
            commands = [
                [], {"method": "resources/read"}, {"method": "tools/list", "params": {"cursor": 5}},
                {"method": "tools/list", "path": "forbidden"},
                {"method": "tools/call", "params": {"name": "write_sql"}},
                {"method": "tools/call", "params": {"name": "read_source", "arguments": []}},
                {"method": "tools/call", "params": []},
            ]
            for command in commands:
                with self.subTest(command=command):
                    result = await dispatch(session, command)
                    self.assertEqual(result["error"]["code"], "invalid_request")
            session.call_tool.assert_not_called()
            session.list_tools.assert_not_called()

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
