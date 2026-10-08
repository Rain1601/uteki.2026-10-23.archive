"""Render explicitly pinned Data retrieval cycles as a portable acceptance page."""
import argparse
import json
from pathlib import Path
from apps.review_workbench.pages.data_retrieval_suite import render_data_retrieval_suite


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(render_data_retrieval_suite(args.suite,args.output),ensure_ascii=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
