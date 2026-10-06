"""JSON-lines bridge to an actual Uteki MCP stdio session.

Usage: python -m uteki.interfaces.data_mcp.client --catalog CATALOG.json
Input: {"method":"tools/list"} or
       {"method":"tools/call","params":{"name":"discover_data","arguments":{"request":{...}}}}
Output: one {"result": <MCP result>} or {"error": {"code": ..., "message": ...}}
per input line. This bridge does not call Uteki services directly.
"""

from __future__ import annotations

import argparse
from contextlib import nullcontext
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, TextIO

import anyio
from mcp import ClientSession, types
from mcp.client.stdio import StdioServerParameters, stdio_client


ALLOWED_TOOLS = frozenset({"discover_data", "get_data_schema", "query_facts", "read_source"})


def _error(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def _audit(stream: TextIO | None, event: str, payload: Any) -> None:
    if stream is not None:
        stream.write(json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "payload": payload,
        }, ensure_ascii=False) + "\n")
        stream.flush()


async def dispatch(session: ClientSession, command: Any) -> dict[str, Any]:
    """Validate the bridge envelope; service/model schemas validate tool arguments."""
    if not isinstance(command, dict) or set(command) - {"method", "params"}:
        return _error("invalid_request", "Expected an object containing only method and params")
    method = command.get("method")
    params = command.get("params", {})
    if not isinstance(params, dict):
        return _error("invalid_request", "params must be an object")
    if method == "tools/list":
        if set(params) - {"cursor"} or ("cursor" in params and not isinstance(params["cursor"], str)):
            return _error("invalid_request", "tools/list accepts only an optional string cursor")
        result = await session.list_tools(params=types.PaginatedRequestParams(**params))
    elif method == "tools/call":
        if set(params) - {"name", "arguments"} or params.get("name") not in ALLOWED_TOOLS:
            return _error("invalid_request", "Select a tool returned by tools/list")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            return _error("invalid_request", "arguments must be an object")
        result = await session.call_tool(params["name"], arguments=arguments)
    else:
        return _error("invalid_request", "Only tools/list and tools/call are supported")
    return {"result": result.model_dump(mode="json", by_alias=True, exclude_none=True)}


async def run_bridge(catalog: Path, audit_stream: TextIO | None, timeout: float) -> int:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "uteki.interfaces.data_mcp.server", "--catalog", str(catalog.resolve())],
    )
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream, read_timeout_seconds=timeout) as session:
            initialized = await session.initialize()
            _audit(audit_stream, "initialize", initialized.model_dump(mode="json", by_alias=True, exclude_none=True))
            while True:
                line = await anyio.to_thread.run_sync(sys.stdin.readline)
                if not line:
                    break
                try:
                    command = json.loads(line)
                except json.JSONDecodeError:
                    output = _error("invalid_json", "Input must be a single JSON object per line")
                    _audit(audit_stream, "invalid_input", {"message": output["error"]["message"]})
                else:
                    _audit(audit_stream, "request", command)
                    try:
                        output = await dispatch(session, command)
                    except Exception:
                        output = _error("protocol_error", "MCP request failed or timed out; inspect the host's session")
                _audit(audit_stream, "response", output)
                print(json.dumps(output, ensure_ascii=False), flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--audit", type=Path, help="Create a new protocol trace; existing files are never overwritten")
    parser.add_argument("--timeout", type=float, default=120.0, help="Per-request timeout in seconds")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        with args.audit.open("x", encoding="utf-8") if args.audit else nullcontext(None) as audit_stream:
            return anyio.run(run_bridge, args.catalog, audit_stream, args.timeout)
    except Exception:
        print(
            "Uteki MCP client failed to start or the session ended unexpectedly. "
            "Check the explicit catalog and use a new audit filename.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
