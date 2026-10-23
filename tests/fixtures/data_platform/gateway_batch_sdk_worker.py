"""One native SDK invocation within a frozen, shared synthetic gateway batch."""
import asyncio
from contextlib import ExitStack
import json
import os
from pathlib import Path
import runpy
import sys
import time
from unittest.mock import patch

from uteki.data_platform.application.tools import ToolExecution
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.contracts.common import CatalogError
from uteki.data_platform.service import DataService

spec=json.loads(Path(sys.argv[1]).read_text())
fixture=runpy.run_path(str(Path(__file__).with_name('gateway_peer.py')))


async def main():
    def checkpoint(phase):
        if phase==spec.get('stop_phase'):os._exit(89)
        if phase==spec.get('hold_phase'):
            Path(spec['held']).write_text(json.dumps(dict(boundary=phase)))
            time.sleep(120)
    with Catalog.open(Path(spec['root'])) as catalog,ExitStack() as stack:
        kernel=spec['kernel']
        if spec.get('tool_error'):
            original=ToolExecution.execute;injected=[]
            def fail_first(executor,operation_id):
                if executor.tool=='find_assets' and not injected:
                    injected.append(operation_id)
                    raise CatalogError('CAPABILITY_UNSUPPORTED','Controlled synthetic source tool error')
                return original(executor,operation_id)
            stack.enter_context(patch.object(ToolExecution,'execute',fail_first))
        if spec.get('withhold_billing'):
            if kernel=='openai':
                from uteki.data_platform.agent.providers.openrouter_evidence import record_response
                def withheld(*args,**kwargs):return record_response(*args,**kwargs,withhold_billing=True)
                stack.enter_context(patch('uteki.data_platform.agent.providers.gateway_http.record_response',side_effect=withheld))
            else:
                from uteki.data_platform.agent.providers.gateway_http import GatewayHTTP
                from uteki.infrastructure.run_budget import RequestRecoveryRequired
                stack.enter_context(patch.object(GatewayHTTP,'observe_bill',side_effect=RequestRecoveryRequired('Synthetic billing observation withheld')))
        if kernel=='claude':
            import claude_agent_sdk
            from uteki.data_platform.agent.claude_runtime import run_gateway
            options=dict(cwd=Path.cwd(),cli_path=Path(claude_agent_sdk.__file__).parent/'_bundled/claude')
        else:
            from uteki.data_platform.agent.openai_runtime import run_gateway
            options={}
        result=await run_gateway(DataService(catalog),spec['context_ref'],fixture['profile'](kernel),
            gateway_binding=spec['binding'],limits=spec['limits'],endpoint=spec['endpoint'],
            credential='uteki-synthetic-gateway',checkpoint=checkpoint,recover=spec.get('recover',False),**options)
    Path(spec['output']).write_text(json.dumps(result,indent=2)+'\n')


asyncio.run(main())
