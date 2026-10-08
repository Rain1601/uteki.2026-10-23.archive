"""Render a frozen independent benchmark reading page without model calls."""
import argparse
import json
from pathlib import Path

from apps.review_workbench.pages.evidence_benchmark import render_evidence_benchmark


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(render_evidence_benchmark(args.input, args.output), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
