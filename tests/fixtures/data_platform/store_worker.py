"""Process fault driver and runnable example; never imported by product code."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

from uteki.data_platform.content import ContentStore
from uteki.data_platform.contracts import InputManifest, MissingResource, ObjectRef, PresentResource


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['partial_write','before_link','after_link','put','read','example'])
    parser.add_argument('root',type=Path)
    parser.add_argument('--hex',default='')
    parser.add_argument('--ref')
    parser.add_argument('--barrier',type=Path)
    args=parser.parse_args()
    store=ContentStore(args.root)
    if args.mode=='example':
        main_ref=store.put_object(b'<html>synthetic report</html>')
        figure_ref=store.put_object(b'synthetic figure bytes')
        manifest=InputManifest(schema_version='uteki-input-manifest-v1', main=main_ref,
            main_source_url=None, resources=(
                PresentResource(status='present',resource_key='figure-1',source_url=None,object_ref=figure_ref),
                MissingResource(status='missing',resource_key='appendix',source_url=None,reason='not supplied'),
            ))
        reference=store.put_manifest(manifest)
        reopened=ContentStore(args.root)
        loaded=reopened.read_manifest(reference)
        assert reopened.read_object(loaded.main)==b'<html>synthetic report</html>'
        print(json.dumps({'manifest_ref':reference.model_dump(),'manifest':json.loads(loaded.canonical_bytes()),
                          'main_round_trip':True,'source_identity_verified':False}))
        return
    if args.mode=='read':
        print(store.read_object(ObjectRef.model_validate_json(args.ref)).hex())
        return
    if args.barrier:
        deadline=time.monotonic()+5
        while not args.barrier.exists():
            if time.monotonic()>deadline: raise TimeoutError('start barrier not released')
            time.sleep(0.01)
    raw=bytes.fromhex(args.hex)
    if args.mode=='partial_write':
        real_fdopen=os.fdopen
        class PartialWriter:
            def __init__(self,fd,mode): self.stream=real_fdopen(fd,mode)
            def __enter__(self): return self
            def __exit__(self,*args): return self.stream.__exit__(*args)
            def write(self,data):
                self.stream.write(data[:max(1,len(data)//2)])
                self.stream.flush()
                os._exit(73)
        with patch('uteki.data_platform.content.store.os.fdopen',side_effect=PartialWriter):
            store.put_object(raw)
    elif args.mode in {'before_link','after_link'}:
        real_link=os.link
        def crash(source,destination):
            if args.mode=='after_link': real_link(source,destination)
            os._exit(73)
        with patch('uteki.data_platform.content.store.os.link',side_effect=crash):
            store.put_object(raw)
    else:
        print(store.put_object(raw).model_dump_json())


if __name__=='__main__':
    main()
