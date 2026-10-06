"""JSON command-line adapter shared by human and Agent clients."""
import argparse
import json
from pathlib import Path
import sys

import duckdb

from .query_dataset import build_dataset
from .query_service import QueryDataPort
from .evidence_packaging import build_evidence_package
from .agent_cli import register_agent_commands, run_agent_command


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="write a new JSON artifact; existing files are never overwritten")
    commands = parser.add_subparsers(dest="tool", required=True)
    register_agent_commands(commands)
    build = commands.add_parser("build")
    build.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[4])
    build.add_argument("--destination", type=Path, required=True)
    build.add_argument("--spec", type=Path, required=True, help="explicit hash-pinned build specification")
    for name in ("schema", "discover", "query", "evidence", "read"):
        tool = commands.add_parser(name)
        tool.add_argument("--dataset", type=Path, required=True)
        if name == "schema":
            tool.add_argument("--metric", action="append", default=[])
        elif name == "query":
            tool.add_argument("--request", type=Path, required=True)
        else:
            tool.add_argument("--as-of", required=True)
            tool.add_argument("--include-candidates", action="store_true")
            if name == "evidence":
                tool.add_argument("--id", action="append", required=True)
            elif name == "read":
                tool.add_argument("--source", required=True)
                tool.add_argument("--block", required=True)
    for name in ("schema", "discover", "query", "evidence", "context", "outline", "read", "search", "package"):
        tool = commands.add_parser("scoped-" + name, help="explicit source-scoped execution")
        tool.add_argument("--dataset", type=Path, required=True)
        tool.add_argument("--scope", type=Path, required=True, help="research-execution-v1 scope JSON")
        if name == "schema":
            tool.add_argument("--metric", action="append", default=[])
        elif name == "evidence":
            tool.add_argument("--id", action="append", required=True)
        elif name == "context":
            tool.add_argument("--source", required=True)
            tool.add_argument("--block", required=True)
        elif name != "discover":
            tool.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.out and args.out.exists():
            raise FileExistsError("output artifact exists")
        if args.tool not in {"build", "agent"} and args.out and args.out.resolve().is_relative_to(args.dataset.resolve()):
            raise ValueError("query outputs must be outside the immutable dataset")
        if args.tool == 'agent':
            if args.out:
                raise ValueError('agent commands use --output; inspect writes its JSON response to stdout')
            result = run_agent_command(args)
        elif args.tool == "build":
            result = build_dataset(args.repo, args.destination, spec=args.spec)
        else:
            with QueryDataPort(args.dataset) as port:
                if args.tool.startswith("scoped-"):
                    scoped = port.scoped(json.loads(args.scope.read_text()))
                    name = args.tool.removeprefix("scoped-")
                    if name == "schema":
                        result = scoped.get_schema(args.metric)
                    elif name == "discover":
                        result = scoped.discover_data()
                    elif name == "evidence":
                        result = scoped.get_evidence(args.id)
                    elif name == "context":
                        result = scoped.read_context(source_snapshot_id=args.source, block_id=args.block)
                    elif name == "package":
                        result = build_evidence_package(scoped, json.loads(args.request.read_text()))
                    else:
                        method = {"query": scoped.query_data, "outline": scoped.outline_source,
                                  "read": scoped.read_source, "search": scoped.search_source}[name]
                        result = method(json.loads(args.request.read_text()))
                elif args.tool == "schema":
                    result = port.get_schema(args.metric)
                elif args.tool == "discover":
                    result = port.discover_data(knowledge_cutoff=args.as_of, include_candidates=args.include_candidates)
                elif args.tool == "query":
                    result = port.query_data(json.loads(args.request.read_text()))
                elif args.tool == "evidence":
                    result = port.get_evidence(args.id, snapshot_id=port.snapshot_id, knowledge_cutoff=args.as_of,
                                               include_candidates=args.include_candidates)
                else:
                    result = port.read_context(source_snapshot_id=args.source, block_id=args.block, snapshot_id=port.snapshot_id,
                                               knowledge_cutoff=args.as_of, include_candidates=args.include_candidates)
        output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with args.out.open("x") as stream:
                stream.write(output)
        else:
            print(output, end="")
        if args.tool == 'agent' and args.agent_action == 'acquire':
            return 0 if result.get('status') == 'completed' else 2
        return 2 if args.tool == 'agent' and result.get('status') in {'failed', 'unavailable', 'cancelled'} else 0
    except (ValueError, KeyError, OSError, RuntimeError, duckdb.Error) as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
