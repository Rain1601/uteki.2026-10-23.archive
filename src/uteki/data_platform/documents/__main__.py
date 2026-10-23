"""Explicit local document storage CLI; never acquires sources or calls models."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from pydantic import ValidationError

from ..contracts.documents import BlockQuery, BlockRef, DocumentPackage
from ..content.store import ContentStoreError
from .store import DocumentStore, DocumentStoreError


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root',type=Path,required=True,help='existing absolute directory; never defaults to output/')
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('init')
    put=commands.add_parser('put-object');put.add_argument('--file',type=Path,required=True)
    publish=commands.add_parser('publish');publish.add_argument('--package',type=Path,required=True)
    publish.add_argument('--no-default',action='store_true')
    schema=commands.add_parser('schema');schema.add_argument('--parse-id',required=True)
    schema.add_argument('--without-directory',action='store_true')
    find=commands.add_parser('find')
    for key in ('entity-id','material-type','reporting-period','name','published-from','published-to'):
        find.add_argument('--'+key)
    find.add_argument('--entity-role',default='subject');find.add_argument('--limit',type=int,default=20);find.add_argument('--cursor')
    browse=commands.add_parser('browse');browse.add_argument('--parse-id',required=True)
    browse.add_argument('--parent-id');browse.add_argument('--limit',type=int,default=50);browse.add_argument('--cursor')
    query=commands.add_parser('query');query.add_argument('--request',type=Path,required=True);query.add_argument('--cursor')
    read=commands.add_parser('read');read.add_argument('--reference',type=Path,required=True)
    read.add_argument('--neighbors',type=int,default=0);read.add_argument('--without-context',action='store_true')
    section=commands.add_parser('section');section.add_argument('--parse-id',required=True)
    choice=section.add_mutually_exclusive_group(required=True)
    choice.add_argument('--node-id');choice.add_argument('--code-path')
    section.add_argument('--scope-node-id');section.add_argument('--direct-only',action='store_true')
    section.add_argument('--content-view',choices=('body','all'),default='body')
    passage=commands.add_parser('passage');passage.add_argument('--parse-id',required=True)
    choice=passage.add_mutually_exclusive_group(required=True)
    choice.add_argument('--path');choice.add_argument('--passage-id')
    for name in ('export','reindex'):
        cmd=commands.add_parser(name);cmd.add_argument('--parse-id',required=True)
    args=parser.parse_args(argv)
    try:
        opener=DocumentStore.initialize if args.command=='init' else DocumentStore.open
        with opener(args.data_root) as store:
            if args.command=='init':result={'status':'initialized','data_root':str(store.root)}
            elif args.command=='put-object':result=store.content.put_object(args.file.read_bytes()).model_dump(mode='json')
            elif args.command=='publish':result=store.publish(DocumentPackage.model_validate_json(args.package.read_bytes()),make_default=not args.no_default)
            elif args.command=='schema':result=store.get_schema(args.parse_id,include_directory=not args.without_directory)
            elif args.command=='find':result=store.find_materials(**{k:v for k,v in vars(args).items() if k not in ('command','data_root')})
            elif args.command=='browse':result=store.browse_directory(args.parse_id,parent_id=args.parent_id,limit=args.limit,cursor=args.cursor)
            elif args.command=='query':result=store.query_blocks(BlockQuery.model_validate_json(args.request.read_bytes()),cursor=args.cursor)
            elif args.command=='read':result=store.read_block(BlockRef.model_validate_json(args.reference.read_bytes()),neighbors=args.neighbors,include_context=not args.without_context)
            elif args.command=='section':result=store.read_section(args.parse_id,node_id=args.node_id,
                code_path=args.code_path,scope_node_id=args.scope_node_id,
                include_descendants=not args.direct_only,content_view=args.content_view)
            elif args.command=='passage':result=store.read_passage(args.parse_id,path=args.path,passage_id=args.passage_id)
            elif args.command=='export':result=store.export_package(args.parse_id).model_dump(mode='json')
            else:result=store.reindex(args.parse_id)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except sqlite3.Error as error:
        print(json.dumps(dict(status='error',code='DATABASE_ERROR',message=str(error)),ensure_ascii=False));return 1
    except (DocumentStoreError,ContentStoreError,ValidationError,ValueError,OSError) as error:
        print(json.dumps(dict(status='error',code=getattr(error,'code','INVALID_INPUT'),message=str(error),details=getattr(error,'details',None)),ensure_ascii=False));return 1


if __name__=='__main__':
    raise SystemExit(main())
