"""Real Claude CLI, local synthetic peer, named Skill and read-only checker only."""
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

import claude_agent_sdk
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow, PermissionResultDeny, ResultMessage


async def main():
    spec = json.loads(Path(sys.argv[1]).read_text())
    endpoint = urlsplit(os.environ['ANTHROPIC_BASE_URL'])
    if endpoint.scheme != 'http' or endpoint.hostname != '127.0.0.1':
        raise ValueError('This fixture is loopback only')
    async def permission(name, arguments, context):
        if name == 'Skill' and arguments.get('skill') == 'financial-data-query':
            return PermissionResultAllow(updated_input=arguments)
        if name == 'Bash' and arguments.get('command') == spec['command']:
            return PermissionResultAllow(updated_input=arguments)
        return PermissionResultDeny(message='Only the named skill and exact read-only fixture check are permitted')
    options = ClaudeAgentOptions(model='fixture/financial-skill',
        system_prompt='Offline SDK capability test. Load financial-data-query, then run the supplied read-only check. No other actions.',
        tools=['Skill', 'Bash'], skills=['financial-data-query'], setting_sources=['project'], plugins=[],
        strict_mcp_config=True, mcp_servers={}, permission_mode='default', can_use_tool=permission,
        cwd=Path.cwd(), cli_path=Path(claude_agent_sdk.__file__).parent/'_bundled/claude', max_turns=4)
    result = None
    async with asyncio.timeout(45), ClaudeSDKClient(options=options) as client:
        await client.query('Use financial-data-query to check the provided synthetic delivery: '+spec['command'])
        async for event in client.receive_response():
            if isinstance(event, ResultMessage):
                result = asdict(event)
    Path(spec['output']).write_text(json.dumps(dict(result=result, real_model_calls=0), ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
