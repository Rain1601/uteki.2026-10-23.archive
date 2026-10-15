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
    if args.phase=='index_head_visible':
        from uteki.data_platform.retrieval import index
        write_index=index.write_control
        def stop_index(path,*values,**options):
            write_index(path,*values,**options)
            os._exit(73)
        index.write_control=stop_index
    if args.phase=='context_control_pending':
        # Interrupt the real atomic writer after it creates its temporary file,
        # before linking the first control file. The durable intent is already
        # registered; the residual file must not be mistaken for committed state.
        from unittest.mock import patch
        from uteki.data_platform.application import session
        import tempfile
        write=session.write_control
        mkstemp=tempfile.mkstemp
        def stop_temporary(*values,**options):
            mkstemp(*values,**options)
            os._exit(73)
        def interrupted_write(path,*values,**options):
            if path.name=='creation.json':
                with patch.object(tempfile,'mkstemp',stop_temporary):
                    return write(path,*values,**options)
            return write(path,*values,**options)
        session.write_control=interrupted_write
    def checkpoint(phase):
        if phase==args.phase:
            os._exit(73)
    with Catalog.open(args.root) as catalog:
        service=DataService(catalog)
        method={'deliver':service.deliver,'clarify':service.clarify,'call':service.call,'create_context':service.create_context}[invocation.pop('method')]
        result=method(**invocation,checkpoint=checkpoint)
    print(json.dumps(result))


if __name__=='__main__':
    main()
