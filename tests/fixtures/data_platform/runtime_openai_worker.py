"""Abrupt native Runner exit at a durable boundary; synthetic fixture only."""
import asyncio
from contextlib import nullcontext
from functools import partial
import json
import os
from pathlib import Path
import runpy
import sys
import time

from uteki.data_platform.agent.openai_runtime import run_offline
from uteki.data_platform.agent.profiles import load_profile
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.service import DataService
from uteki.data_platform.application.session import Session
from uteki.data_platform.application.run_budget import RunBudget


async def main():
    root,context,config,phase=sys.argv[1:5]
    acquisition=len(sys.argv)>5 and sys.argv[5]=='acquisition'
    recover=len(sys.argv)>5 and sys.argv[5]=='resume'
    skills=len(sys.argv)>5 and sys.argv[5]=='skill'
    config=Path(config)
    fixture=runpy.run_path(str(Path(__file__).with_name('sdk_fixture.py')))
    variant='fixture-skill-query' if skills else 'fixture-query'
    profile=load_profile(config/f'model-profiles/openai/{variant}/query.json',config_root=config,
        kernel='openai',model_id='fixture/openai-skill-query-v1' if skills else 'fixture/openai-query-v1',role='query')
    target, _, occurrence = phase.partition('@')
    seen = 0
    def checkpoint(point):
        nonlocal seen
        if point==target:
            seen += 1
            if seen==int(occurrence or '1'):
                if len(sys.argv)>5 and sys.argv[5]=='supervisor':
                    (Path(root)/'fixture-host-blocked').write_text(point)
                    time.sleep(120)
                os._exit(79)
    with Catalog.open(root) as catalog:
        scenario='free_text' if len(sys.argv)>5 and sys.argv[5]=='failure' else 'clarify' if phase.startswith('clarification_') else 'success'
        model=fixture['SkillScriptedModel' if skills else 'ScriptedModel'](scenario)
        if recover:
            data=Session(catalog,context).data
            ledger=RunBudget.open_existing(Path(root)/data['native_execution']['ledger_path'],'0',
                root_run_id=data['context']['root_run_id'])
            model.script.count=sum(r['stage']=='responded' for r in ledger.inspect_requests())
        if acquisition:model.script=fixture['AcquisitionScript'](json.loads((Path(root)/'fixture-acquisition.json').read_text()))
        with fixture['acquisition_host'](catalog) if acquisition else nullcontext(DataService(catalog)) as service:
            limits=json.loads(sys.argv[6]) if len(sys.argv)>6 else fixture['runtime_limits']()
            if len(sys.argv)>7 and sys.argv[7]=='service':
                host=DataService(catalog,acquisition_adapter=service.acquisition_adapter,query_runtime=partial(
                    run_offline,profile=profile,model=model,limits=limits,checkpoint=checkpoint))
                await host.run_query(context,recover=recover)
            else:
                await run_offline(service,context,profile,model=model,limits=limits,checkpoint=checkpoint,recover=recover)
    raise AssertionError('requested abrupt checkpoint was not reached')


if __name__=='__main__':asyncio.run(main())
