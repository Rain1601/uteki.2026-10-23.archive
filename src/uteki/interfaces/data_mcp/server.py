"""Serve Uteki data through the official MCP SDK and stdio transport.

The host explicitly selects a catalog. Clients use opaque dataset/source IDs;
they cannot supply filesystem locations or invoke extraction through this server.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

from mcp import types
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError


TOOL_DESCRIPTIONS = {
    "discover_data": (
        "Find companies and frozen dataset versions in the host-selected catalog. "
        "Begin here to obtain IDs and inspect available periods, forms, candidate "
        "status and gaps. Registration does not imply complete or adopted data. "
        "Never infer a missing financial value as zero."
    ),
    "get_data_schema": (
        "Inspect the selected dataset's query schema, metric identifiers, units, "
        "fiscal periods and available sources before asking for financial facts. "
        "Observed metric coverage is not a promise of complete financial coverage."
    ),
    "query_facts": (
        "Read financial facts from an explicitly selected frozen dataset and scope. "
        "Preserve issuer, fiscal dates, units, currency, provenance, review/adoption "
        "status and missing-data diagnostics. Candidate facts must be requested "
        "explicitly; a successful query is not a financial verification."
    ),
    "read_source": (
        "Read original-source evidence within an explicitly selected dataset. "
        "Use the supported outline, search, context/read or evidence operation "
        "and returned source/block/evidence IDs. Search requires node_id and phrase; "
        "read requires node_id; context requires block_id; evidence requires evidence_ids. "
        "Compact table cells use positional cell_fields with no omitted cells. Honor pagination and report gaps; "
        "source text alone is not a verified or adopted financial record."
    ),
}


def create_server(service: Any) -> MCPServer:
    """Register typed service requests without adding hidden business defaults."""
    from .service import DiscoverRequest, FactsRequest, SchemaRequest, SourceRequest

    server = MCPServer(
        name="uteki-data",
        version="0.1.0",
        instructions=(
            "Uteki exposes existing frozen data and source evidence, read-only. "
            "Start with discover_data, inspect get_data_schema, then query_facts "
            "or read_source using returned IDs and explicit scope. Distinguish "
            "candidate, reviewed and adopted states. Missing coverage is a gap, "
            "never zero. No download, extraction, model call or SQL write is available."
        ),
        log_level="ERROR",
    )
    request_models = {
        "discover_data": DiscoverRequest,
        "get_data_schema": SchemaRequest,
        "query_facts": FactsRequest,
        "read_source": SourceRequest,
    }

    def make_handler(name: str, request_type: type[Any]) -> Any:
        async def handler(request: Any) -> dict[str, Any]:
            try:
                return getattr(service, name)(request)
            except ValueError as exc:
                raise ToolError(str(exc)) from None
            except Exception:
                raise ToolError(
                    "data_service_error: the selected data could not be read; "
                    "ask the host to inspect its registered artifacts"
                ) from None

        handler.__name__ = name
        handler.__annotations__ = {"request": request_type, "return": dict[str, Any]}
        return handler

    for name, request_type in request_models.items():
        server.add_tool(
            make_handler(name, request_type),
            name=name,
            description=TOOL_DESCRIPTIONS[name],
            structured_output=True,
            annotations=types.ToolAnnotations(
                read_only_hint=True,
                destructive_hint=False,
                idempotent_hint=True,
                open_world_hint=False,
            ),
        )
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True, type=Path, help="Explicit frozen-data catalog")
    args = parser.parse_args(argv)
    from .service import DataMCPService

    try:
        service = DataMCPService(args.catalog)
    except Exception:
        print(
            "Uteki MCP startup failed: the explicit catalog or its registered artifacts "
            "could not be validated. Inspect the catalog on the host.",
            file=sys.stderr,
        )
        return 2
    try:
        create_server(service).run(transport="stdio")
    finally:
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
