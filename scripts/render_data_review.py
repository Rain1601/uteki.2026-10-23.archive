"""Render a verified Data review as a local, inspectable HTML delivery."""
import argparse
import json
from pathlib import Path
from apps.review_workbench.pages.data_review_delivery import render_data_review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review-dir', required=True, type=Path)
    parser.add_argument('--review-manifest-sha256', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--dataset-key')
    parser.add_argument('--source-preview-base-url')
    args = parser.parse_args()
    result = render_data_review(args.review_dir, args.output,
        expected_manifest_sha256=args.review_manifest_sha256,
        dataset_key=args.dataset_key, source_preview_base_url=args.source_preview_base_url)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
