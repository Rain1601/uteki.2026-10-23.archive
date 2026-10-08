"""Retrieve and review Data evidence with at most three bounded follow-ups."""
import argparse
import asyncio
import json
from pathlib import Path

from uteki.agents.data_query.retrieval_cycle import run_retrieval_cycle, validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if args.check_only:
        validate(config, args.output)
        print('local_inputs_valid; no model calls or writes')
        return 0
    result = asyncio.run(run_retrieval_cycle(config, args.output))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['status'] == 'reviewed_data_ready' else 1


if __name__ == '__main__':
    raise SystemExit(main())
