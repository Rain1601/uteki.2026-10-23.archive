"""Isolated real Claude SDK/CLI worker, usable only with the loopback fixture."""
import asyncio
from contextlib import ExitStack
from functools import partial
import json
import os
from pathlib import Path
import runpy
import sys
import time
from copy import deepcopy
from unittest.mock import patch

import claude_agent_sdk
from uteki.data_platform.agent.claude_runtime import run_offline
from uteki.data_platform.agent.profiles import load_profile
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.service import DataService


async def main():
    data_root,context,config_root,output=map(Path,sys.argv[1:5])
    options=json.loads(sys.argv[5]) if len(sys.argv)>5 else {}
    loaded=load_profile(config_root/'model-profiles/claude/fixture-query/query.json',config_root=config_root,
        kernel='claude',model_id='fixture/claude-query-v1',role='query')
    with Catalog.open(data_root) as catalog, ExitStack() as stack:
        service=DataService(catalog)
        if options.get('wire_fault') and options.get('recover'):
            from uteki.data_platform.agent.claude_state import ClaudeState
            original=ClaudeState.validate_request
            def altered(self,request):
                request=deepcopy(request)
                request['messages'].append(dict(role='assistant',content=[dict(type='text',text='Invented unsupported answer')]))
                return original(self,request)
            stack.enter_context(patch.object(ClaudeState,'validate_request',altered))
        if options.get('acquisition'):
            fixture=runpy.run_path(str(Path(__file__).with_name('sdk_fixture.py')))
            service=stack.enter_context(fixture['acquisition_host'](catalog))
        async with asyncio.timeout(90):
            running=None
            loop=asyncio.get_running_loop()
            occurrences={}
            def checkpoint(phase):
                occurrences[phase]=occurrences.get(phase,0)+1
                if phase==options.get('supervisor_at_phase'):
                    (data_root/'fixture-host-blocked').write_text(phase)
                    time.sleep(120)
                if options.get('stop_phase') in {phase,phase+'@'+str(occurrences[phase])}: os._exit(79)
                if options.get('cancel_phase') in {phase,phase+'@'+str(occurrences[phase])}:
                    loop.call_soon_threadsafe(running.cancel)
                    if options.get('repeat_cancel'):
                        loop.call_soon_threadsafe(running.cancel)
            kwargs=dict(cwd=Path.cwd(),cli_path=Path(claude_agent_sdk.__file__).parent/'_bundled/claude',
                limits=options.get('limits',dict(native_max_turns=12,max_model_requests=12,max_request_bytes=2000000,max_response_bytes=2000000)),
                checkpoint=checkpoint,recover=options.get('recover',False))
            async def invoke(service,context_ref):
                if options.get('service_entry'):
                    bound=partial(run_offline,profile=loaded,**{k:v for k,v in kwargs.items() if k!='recover'})
                    host=DataService(catalog,acquisition_adapter=service.acquisition_adapter,query_runtime=bound)
                    return await host.run_query(context_ref,recover=kwargs['recover'])
                return await run_offline(service,context_ref,loaded,**kwargs)
            running=asyncio.create_task(invoke(service,str(context)))
            result=await running
            if options.get('replay'):
                repeated=await invoke(service,str(context))
                result['fixture_replay_equal']=result==repeated
            if options.get('continue_answer'):
                parent=result
                service=DataService(catalog)
                request=deepcopy(service.inspect_context(str(context))['context']['request'])
                request.update(revises_context_ref=str(context),clarification_response=dict(
                    clarification_id=parent['clarification']['clarification']['clarification_id'],answer='Use the same scope.'))
                child=service.create_context(request,request_key='fixture-answer')
                result=await invoke(service,child['context_ref'])
                result['fixture_parent_result']=parent
                result['fixture_child_context_ref']=child['context_ref']
                result['fixture_child_state']=service.inspect_context(child['context_ref'])
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(status=result['status'],error=result['error'])))


if __name__=='__main__':asyncio.run(main())
