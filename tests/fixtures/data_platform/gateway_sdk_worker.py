"""Owned native Claude CLI wire fixture; only an explicit loopback is accepted."""
import asyncio
from dataclasses import asdict, is_dataclass
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit


async def main(config_root, output):
    import claude_agent_sdk
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, PermissionResultDeny, create_sdk_mcp_server, tool
    from uteki.data_platform.agent.binding import DESCRIPTIONS, ENVELOPES
    from uteki.data_platform.agent.profiles import load_profile
    contract=json.loads((config_root/'gateway-contract.draft.v1.json').read_text())
    model=contract['model']['gateway_id']
    loaded=load_profile(config_root/'model-profiles/claude/deepseek-v4.1-flash/query.json',
        config_root=config_root,kernel='claude',model_id=model,role='query')
    endpoint=urlsplit(os.environ['ANTHROPIC_BASE_URL'])
    if endpoint.scheme!='http' or endpoint.hostname!='127.0.0.1' or not endpoint.port:
        raise AssertionError('only the explicit loopback gate is permitted')
    async def prohibited(*args,**kwargs):raise AssertionError('Wire fixture cannot execute business tools')
    async def deny(*args,**kwargs):return PermissionResultDeny(message='Wire fixture has no business execution')
    handlers=[tool(name,DESCRIPTIONS[name],schema.model_json_schema())(prohibited) for name,schema in ENVELOPES.items()]
    options=ClaudeAgentOptions(model=model,fallback_model=None,system_prompt=loaded.text,
        thinking={'type':'disabled'},effort=None,tools=[],allowed_tools=[],permission_mode='default',
        setting_sources=[],skills=[],plugins=[],strict_mcp_config=True,can_use_tool=deny,
        mcp_servers={'data':create_sdk_mcp_server('data',version='1.0.0',tools=handlers)},
        cwd=Path.cwd(),cli_path=Path(claude_agent_sdk.__file__).parent/'_bundled/claude',max_turns=1)
    events=[]
    async with asyncio.timeout(40):
        async with ClaudeSDKClient(options=options) as client:
            await client.query('Offline wire fixture only. Return the synthetic peer text; do not invoke tools.')
            async for event in client.receive_response():
                events.append(dict(type=type(event).__name__,data=asdict(event) if is_dataclass(event) else str(event)))
    output.write_text(json.dumps(dict(events=events,tool_handlers_executed=0),ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':asyncio.run(main(Path(sys.argv[1]),Path(sys.argv[2])))
