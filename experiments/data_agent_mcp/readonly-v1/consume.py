"""Evaluation client: real MCP JSONL calls, with full protocol audit preserved.

This explicitly selected experiment binds a catalog. It contains no task answers,
source/block/record IDs, or direct query-service access. Each invocation starts
a new stdio connection. Returned structured content is displayed once.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
AUDIT = Path(__file__).parent / "protocol"
AUDIT.mkdir(exist_ok=True)
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
result = subprocess.run(
    [str(ROOT / ".venv/bin/python"), "-m", "uteki.interfaces.data_mcp.client",
     "--catalog", str(ROOT / "config/data-mcp-readonly-v1.json"),
     "--audit", str(AUDIT / (stamp + ".jsonl"))],
    input=sys.stdin.read(), text=True, capture_output=True, cwd=ROOT,
)
for line in result.stdout.splitlines():
    item = json.loads(line)
    response = item.get("result", {})
    if "structuredContent" in response:
        item = {"result": response["structuredContent"], "isError": response.get("isError", False)}
    print(json.dumps(item, ensure_ascii=False))
if result.returncode:
    print("MCP session failed; host audit retained.", file=sys.stderr)
raise SystemExit(result.returncode)
