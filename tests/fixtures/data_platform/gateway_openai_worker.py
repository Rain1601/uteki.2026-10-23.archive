"""Owned process for gateway SDK continuation at exact durable boundaries."""
import asyncio
import json
import os
from pathlib import Path
import runpy
import sys

from uteki.data_platform.agent.openai_runtime import run_gateway
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.service import DataService

root,spec_path,phase=sys.argv[1:]
spec=json.loads(Path(spec_path).read_text())
fixture=runpy.run_path(str(Path(__file__).with_name('gateway_peer.py')))

def checkpoint(current):
    if current==phase:os._exit(89)

with Catalog.open(Path(root)) as catalog:
    result=asyncio.run(run_gateway(DataService(catalog),spec['context_ref'],fixture['profile']('openai'),
        gateway_binding=spec['binding'],limits=spec['limits'],endpoint=spec['endpoint'],
        credential='uteki-synthetic-gateway',checkpoint=checkpoint))
    (Path(root)/'unexpected-worker-result.json').write_text(json.dumps(result))
raise AssertionError('requested gateway checkpoint was not reached')
