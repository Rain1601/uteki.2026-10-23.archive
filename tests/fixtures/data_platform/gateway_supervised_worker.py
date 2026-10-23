"""Synthetic fault worker; actual SDKs, with process-owned blocking faults."""
import asyncio
from contextlib import ExitStack
import json
from pathlib import Path
import runpy
import socket
import sys
import time
from unittest.mock import patch

from uteki.data_platform.catalog import Catalog
from uteki.data_platform.service import DataService

spec=json.loads(Path(sys.argv[1]).read_text())
fixture=runpy.run_path(str(Path(__file__).with_name('gateway_peer.py')))
root=Path(spec['root'])


async def main():
    def checkpoint(phase):
        if phase==spec.get('hold_phase'):
            (root/'blocked.json').write_text(json.dumps(dict(boundary=phase)))
            time.sleep(120)
    with Catalog.open(root) as catalog,ExitStack() as stack:
        if spec.get('block_dns'):
            original=socket.getaddrinfo
            def blocked(host,*args,**kwargs):
                if host=='127.0.0.1':
                    (root/'blocked.json').write_text(json.dumps(dict(boundary='getaddrinfo')))
                    time.sleep(120)
                return original(host,*args,**kwargs)
            stack.enter_context(patch.object(socket,'getaddrinfo',blocked))
        kernel=spec['kernel']
        if kernel=='claude':
            import claude_agent_sdk
            from uteki.data_platform.agent.claude_runtime import run_gateway
            options=dict(cwd=Path.cwd(),cli_path=Path(claude_agent_sdk.__file__).parent/'_bundled/claude')
        else:
            from uteki.data_platform.agent.openai_runtime import run_gateway
            options={}
        result=await run_gateway(DataService(catalog),spec['context_ref'],fixture['profile'](kernel),
            gateway_binding=spec['binding'],limits=spec['limits'],endpoint=spec['endpoint'],
            credential='uteki-synthetic-gateway',checkpoint=checkpoint,**options)
    Path(spec['output']).write_text(json.dumps(result,indent=2)+'\n')


asyncio.run(main())
