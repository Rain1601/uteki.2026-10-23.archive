"""Isolated real Claude SDK/CLI worker, usable only with the loopback fixture."""
import asyncio
import json
from pathlib import Path
import sys

import claude_agent_sdk
from uteki.data_platform.agent.claude_runtime import run_offline
from uteki.data_platform.agent.profiles import load_profile
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.service import DataService


async def main():
    data_root,context,config_root,output=map(Path,sys.argv[1:])
    loaded=load_profile(config_root/'model-profiles/claude/fixture-query/query.json',config_root=config_root,
        kernel='claude',model_id='fixture/claude-query-v1',role='query')
    with Catalog.open(data_root) as catalog:
        async with asyncio.timeout(90):
            result=await run_offline(DataService(catalog),str(context),loaded,cwd=Path.cwd(),
                cli_path=Path(claude_agent_sdk.__file__).parent/'_bundled/claude',max_turns=12)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(status=result['status'],error=result['error'])))


if __name__=='__main__':asyncio.run(main())
