"""Actual CLI + production MCP assembly; synthetic tool bytes, loopback only."""
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

import claude_agent_sdk
from claude_agent_sdk import ClaudeSDKClient, ResultMessage
from uteki.data_platform.agent.claude_runtime import make_options
from uteki.data_platform.agent.binding import ENVELOPES, ToolBinding
from uteki.data_platform.agent.profiles import load_profile, LoadedProfile, Profile
from uteki.data_platform.contracts.common import canonical, digest


async def main():
    spec=json.loads(Path(sys.argv[1]).read_text())
    endpoint=urlsplit(os.environ['ANTHROPIC_BASE_URL'])
    if endpoint.scheme!='http' or endpoint.hostname!='127.0.0.1' or not endpoint.port:
        raise AssertionError('Only the explicit local synthetic peer is allowed')
    config=Path(spec['config'])
    loaded=load_profile(config/'model-profiles/claude/live-B-deepseek-claude/query.json',config_root=config,
                        kernel='claude',model_id='deepseek-flash',role='query')
    profile=LoadedProfile(Profile.model_validate_json(json.dumps(loaded.metadata() |
        {'mcp_max_result_chars':spec['threshold']})),loaded.text)
    output=canonical(spec['tool_output']).decode();calls=[]
    async def invoke(name, arguments, *, call_id):
        if name!='find_assets' or calls:raise AssertionError('Only one synthetic tool call is expected')
        calls.append(dict(name=name,arguments=arguments,output_sha256=digest(output.encode())))
        return output
    # Expose the production shared (non-document) tool projection; only tool bytes are synthetic.
    binding=SimpleNamespace(journal=None,terminal=None,invoke=invoke,events=[],envelopes=ENVELOPES,document_mode=False)
    binding.tool_schema=lambda name:ToolBinding.tool_schema(binding,name)
    binding.tool_description=lambda name:ToolBinding.tool_description(binding,name)
    options=make_options(profile,binding,cwd=Path.cwd(),
        cli_path=Path(claude_agent_sdk.__file__).parent/'_bundled/claude',max_turns=2,mode='gateway')
    events=[];seen=[];stderr=[];started=time.monotonic();failure=None
    options.stderr=stderr.append
    try:
        async with asyncio.timeout(40):
            async with ClaudeSDKClient(options=options) as client:
                await client.query('Synthetic output-forwarding test. Use the supplied local fixture.')
                async for event in client.receive_response():
                    seen.append(dict(type=type(event).__name__,subtype=getattr(event,'subtype',None),
                                     seconds=round(time.monotonic()-started,3)))
                    if isinstance(event,ResultMessage):events.append(asdict(event))
    except Exception as error:
        failure=type(error).__name__+': '+str(error)
        raise
    finally:
        Path(spec['output']).write_text(json.dumps(dict(calls=calls,result_events=events,
            seen=seen,stderr=stderr[-20:],failure=failure,real_model_calls=0)))


asyncio.run(main())
