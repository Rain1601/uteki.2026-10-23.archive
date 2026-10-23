"""Isolated actual Claude CLI; local synthetic gateway only."""
import asyncio
from contextlib import ExitStack
import json
import os
from pathlib import Path
import runpy
import sys
from unittest.mock import patch

import claude_agent_sdk
from uteki.data_platform.agent.profiles import LoadedProfile, Profile
from uteki.data_platform.agent.claude_runtime import run_gateway
from uteki.data_platform.application.tools import ToolExecution
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.contracts.common import CatalogError
from uteki.data_platform.service import DataService

spec=json.loads(Path(sys.argv[1]).read_text())
fixture=runpy.run_path(str(Path(__file__).with_name('gateway_peer.py')))


async def main():
    loop=asyncio.get_running_loop();task=None;count={}
    selected=fixture['profile']('claude')
    if spec.get('profile_overrides'):
        selected=LoadedProfile(Profile.model_validate_json(json.dumps(selected.metadata() | spec['profile_overrides'])),
            selected.text,config_root=selected.config_root)
    def checkpoint(phase):
        count[phase]=count.get(phase,0)+1
        if phase==spec.get('stop_phase'):os._exit(89)
        if phase==spec.get('cancel_phase') and count[phase]==1:loop.call_soon(task.cancel)
    with Catalog.open(Path(spec['root'])) as catalog,ExitStack() as stack:
        if spec.get('tool_error'):
            original=ToolExecution.execute;injected=[]
            def fail_first(executor,operation_id):
                if executor.tool=='find_assets' and not injected:
                    injected.append(operation_id)
                    raise CatalogError('CAPABILITY_UNSUPPORTED','Controlled synthetic source tool error')
                return original(executor,operation_id)
            stack.enter_context(patch.object(ToolExecution,'execute',fail_first))
        task=asyncio.create_task(run_gateway(DataService(catalog),spec['context_ref'],selected,
            gateway_binding=spec['binding'],endpoint=spec['endpoint'],credential='uteki-synthetic-gateway',
            cwd=Path.cwd(),cli_path=Path(claude_agent_sdk.__file__).parent/'_bundled/claude',
            limits=spec['limits'],checkpoint=checkpoint,recover=spec.get('recover',False)))
        result=await task
        if spec.get('replay'):
            repeated=await run_gateway(DataService(catalog),spec['context_ref'],fixture['profile']('claude'),
                gateway_binding=spec['binding'],endpoint=spec['endpoint'],credential='uteki-synthetic-gateway',
                cwd=Path.cwd(),cli_path=Path(claude_agent_sdk.__file__).parent/'_bundled/claude',limits=spec['limits'])
            assert repeated==result
    Path(spec['output']).write_text(json.dumps(result,indent=2)+'\n')


asyncio.run(main())
