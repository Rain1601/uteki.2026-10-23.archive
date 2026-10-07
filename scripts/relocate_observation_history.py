#!/usr/bin/env python3
"""Create/check an explicit machine-local relocation receipt, without API calls."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from uteki.agents.runtime.observation_relocation import RECEIPT_PATH, create_receipt
from uteki.agents.business_map.coverage_run import verify_published_artifacts


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('create','check'))
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--old-root',type=Path)
    parser.add_argument('--observation-root',default='data/agent_observability/local')
    parser.add_argument('--trace',action='append',help='Explicit trace IDs; otherwise all traces beneath old-root.')
    args=parser.parse_args();root=args.root.resolve();receipt_path=root/RECEIPT_PATH
    if args.action=='create':
        if args.old_root is None:parser.error('--old-root required for create')
        value=create_receipt(root=root,old_root=args.old_root,observation_root=root/args.observation_root,trace_ids=args.trace)
        receipt_path.parent.mkdir(parents=True,exist_ok=True)
        if not receipt_path.parent.resolve().is_relative_to(root):
            raise ValueError('relocation_receipt_directory_outside_repository')
        with receipt_path.open('x') as handle:json.dump(value,handle,ensure_ascii=False,indent=2);handle.write('\n')
        receipt_path.chmod(0o600)
    else:value=json.loads(receipt_path.read_text())
    try:
        verified=0
        for row in value['traces']:
            trace=row['trace_id'];obs=root/value['observation_root_relative'];stage=root/row['stage_relative']
            names=set()
            for path in sorted((obs/trace/'events').glob('*.json')):
                event=json.loads(path.read_text())
                if event.get('type')=='artifact.published' and event.get('data',{}).get('ref',{}).get('run_id')==trace:
                    names.add(event['data']['ref']['path'])
            if not names:raise ValueError('relocation_original_publications_missing: '+trace)
            verify_published_artifacts(root=root,observation_root=obs,stage=stage,trace_id=trace,relative_paths=sorted(names))
            verified+=len(names)
        print(json.dumps(dict(status='verified',traces=len(value['traces']),artifacts=verified,receipt=str(receipt_path),history_modified=False)))
    except BaseException:
        if args.action == 'create':
            receipt_path.unlink(missing_ok=True)
        raise

if __name__=='__main__':main()
