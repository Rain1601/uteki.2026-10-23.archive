"""Exit a real child process at a named synchronous tool checkpoint."""
import argparse
import json
import os
from pathlib import Path

from uteki.data_platform.catalog import Catalog
from uteki.data_platform.service import DataService


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    parser.add_argument('invocation',type=Path)
    parser.add_argument('phase')
    args=parser.parse_args()
    invocation=json.loads(args.invocation.read_bytes())
    def checkpoint(phase):
        if phase==args.phase:
            os._exit(73)
    with Catalog.open(args.root) as catalog:
        service=DataService(catalog)
        method=service.deliver if invocation.pop('method')=='deliver' else service.call
        result=method(**invocation,checkpoint=checkpoint)
    print(json.dumps(result))


if __name__=='__main__':
    main()
