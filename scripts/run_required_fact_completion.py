"""Run bounded required-fact completion from explicit frozen scope."""
import argparse
import asyncio
import json
from pathlib import Path

from uteki.infrastructure.research_data.fact_completion import complete_required_facts


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('dataset', 'job', 'output', 'task-profile', 'method-root', 'credentials-root', 'observation-root'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--budget-usd', required=True)
    parser.add_argument('--max-batches', type=int, required=True)
    parser.add_argument('--max-tokens', type=int, default=8000)
    parser.add_argument('--resume-failed-run', type=Path)
    args = parser.parse_args()
    values = vars(args)
    values['job'] = json.loads(args.job.read_text())
    result = asyncio.run(complete_required_facts(**values))
    print(json.dumps(result, ensure_ascii=False))
