"""Scripted synthetic peer. These actions/answers never enter production code."""
from copy import deepcopy
from contextlib import contextmanager
import json
from pathlib import Path
import runpy
from unittest.mock import patch

from agents import Model, ModelResponse, Usage
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText


def runtime_limits(**changes):
    return dict(native_max_turns=12, max_model_requests=12,
                max_request_bytes=2000000, max_response_bytes=2000000) | changes


def case():
    cls = runpy.run_path(str(Path(__file__).resolve().parents[2]/'unit/data_platform/test_queries.py'))['DataToolTests']
    value = cls()
    try:
        value.setUp()
        return value
    except BaseException:
        value.doCleanups()
        raise


def acquisition_case():
    cls=runpy.run_path(str(Path(__file__).resolve().parents[2]/'unit/data_platform/test_tool_acquisition.py'))['ToolAcquisitionTests']
    value=cls()
    try:
        value.setUp()
        service,context=value.service(lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError('host setup fetched')))
        value.service,value.context=service,context
        (value.root/'fixture-acquisition.json').write_text(json.dumps(dict(plan=value.plan,request=value.request,state=value.state)))
        return value
    except BaseException:
        value.doCleanups();raise


def progress(state):
    """Express a scripted full state as the model-facing delta; the host owns versions and next_action."""
    value = dict(reason=state['reason'], satisfied=deepcopy(state.get('satisfied', [])), gaps=deepcopy(state.get('gaps', [])))
    if state.get('plan_update'):
        value['add_needs'] = deepcopy(state['plan_update']['needs'])
    return value


def handle(item):
    return dict(handle=item['result_handle'])


class AcquisitionScript:
    def __init__(self, invocation):
        self.invocation=invocation;self.count=0

    def next(self, outputs):
        self.count+=1
        if self.count>1:return None
        return 'request_asset_update',dict(request=deepcopy(self.invocation['request']),state=progress(self.invocation['state']))


@contextmanager
def acquisition_host(catalog):
    from uteki.data_platform.connectors.updates import OfficialAcquisitionAdapter
    from uteki.data_platform.service import DataService
    import os
    invocation=json.loads((catalog.root/'fixture-acquisition.json').read_text())
    html=runpy.run_path(str(Path(__file__).with_name('html_fixture.py')))
    def fetch(url,**kwargs):
        assert url in {html['MAIN_URL'],html['IMAGE_URL']}
        path=catalog.root/'fixture-native-acquisition-requests.json'
        requests=json.loads(path.read_text()) if path.exists() else []
        requests.append(url)
        with path.open('w') as stream:
            json.dump(requests,stream);stream.flush();os.fsync(stream.fileno())
        return html['source']() if url==html['MAIN_URL'] else b'synthetic image'
    with patch('uteki.data_platform.connectors.official.resolve_sec_contact',return_value=('Synthetic test@example.com','synthetic_fixture')):
        yield DataService(catalog,acquisition_adapter=OfficialAcquisitionAdapter([invocation['plan']],settings_root=catalog.root,fetch=fetch))


def resolve_acquisition_worker(root, context_ref, action):
    """Resolve in a separately observed host worker; never restart the model."""
    import sys
    from uteki.data_platform.application.execution_clock import ObservedWorker
    from uteki.data_platform.catalog import Catalog
    value=json.loads((root/'fixture-acquisition.json').read_text())
    value.update(context_ref=context_ref,tool='request_asset_update',request_key='unused-original-key')
    invocation=root/'host-resolution-invocation.json';invocation.write_text(json.dumps(value))
    with (root/'host-resolution.log').open('w') as log:
        worker=ObservedWorker([sys.executable,'-I',str(Path(__file__).with_name('acquisition_resolution_worker.py')),
            str(root),str(invocation),action,'none'],cwd=root,env={'PATH':'/usr/bin:/bin'},stdout=log,stderr=log)
        observation=worker.wait(timeout=30)
    if observation['returncode']!=0:raise AssertionError((root/'host-resolution.log').read_text())
    with Catalog.open(root) as catalog:worker.record(catalog,context_ref)
    return dict(observation=observation,result=json.loads((root/'resolution-result.json').read_text()),
        process_cleanup=worker.cleanup)


class Script:
    def __init__(self, scenario='success'):
        self.scenario = scenario
        self.count = 0
        self.requests = []

    def next(self, outputs):
        step = self.count
        self.count += 1
        if self.scenario == 'repeat_discovery':
            # Identical discovery every turn: only the first response returns new metadata.
            delta = dict(reason='Repeat synthetic discovery', satisfied=[],
                gaps=[dict(need_id='cash', missing='Read synthetic source and cash comparison')])
            if step == 0:
                delta['add_needs'] = [dict(need_id='cash', description='Synthetic cash comparison and source', required=True)]
            result = 'find_assets', dict(request=dict(filters={}), state=delta)
            self.requests.append(deepcopy(result))
            return result
        if self.scenario == 'free_text' or (self.scenario not in {'success','tool_error','after_clarification'} and step) or (self.scenario == 'tool_error' and step > 1):
            return None
        state = dict(satisfied=[], gaps=[dict(need_id='cash', missing='Read synthetic source and cash comparison')],
            next_action='find_assets', reason='Scripted synthetic step')
        if step == 0 and self.scenario!='after_clarification':
            state['plan_update'] = dict(base_version=0, needs=[dict(need_id='cash', description='Synthetic cash comparison and source', required=True)])
        tool, request = 'find_assets', dict(filters={})
        if self.scenario=='clarify':
            state['next_action']='clarify'
            return 'clarify',dict(request=dict(question='Use the same explicit company and periods?',blocking_need_ids=['cash']),state=state)
        if self.scenario == 'invalid_arguments':
            return tool, dict(unexpected='invalid')
        if self.scenario == 'forged_delivery':
            tool = 'deliver'
            request = dict(needs=[dict(need_id='cash', status='supported', result_refs=[dict(handle='rr_0000000000000000')],gaps=[])])
        if step:
            reference = outputs[0]['items'][0]['asset_ref']
            if step == 1:
                tool, request = 'get_asset_schema', dict(asset_ref=reference, facets=['fields','concepts'])
            elif step == 2:
                tool, request = 'request_asset_update', dict(need_id='cash',action='process',process=dict(asset_ref=reference,capabilities=['text_search','records']),reason='Explicit synthetic indexing')
            elif step == 3:
                tool, request = 'search_asset', dict(asset_ref=reference,mode='text',text=dict(match='phrase',value='Exact source'))
            elif step == 4:
                tool, request = 'read_evidence', dict(asset_ref=reference,targets=[dict(block_id=outputs[3]['items'][0]['block_id'])])
            elif step == 5:
                tool, request = 'query_records', dict(asset_ref=reference,select=dict(concepts=['{https://example.com/taxonomy}Cash']))
            elif step == 6:
                # Choose an occurrence from each exact synthetic source period;
                # duplicate same-period disclosures are not summed.
                periods = {}
                for record in outputs[5]['items']:
                    periods.setdefault(record['period']['end'], record)
                records = [periods[k] for k in sorted(periods, reverse=True)]
                calc = dict(calc_id='growth',op='growth',operands=[dict(asset_ref=reference,record_selector=dict(record_id=r['record_id'])) for r in records],
                    output_unit='ratio',period_policy='distinct_nonoverlapping',comparison_basis='Synthetic matching entity/unit and annual periods')
                tool, request = 'query_records', dict(asset_ref=reference,select={'concepts':['{https://example.com/taxonomy}Cash']},calculations=[calc])
            elif step == 7:
                refs = [handle(outputs[4]['items'][0]),handle(outputs[6]['calculations'][0])]
                tool, request = 'deliver', dict(needs=[dict(need_id='cash',status='supported',result_refs=refs,gaps=[])])
            else:
                return None
        delta = progress(state)
        if self.scenario == 'tool_error' and step:
            # Schema-valid business error: records are queried before the asset is processed.
            tool,request='query_records',dict(asset_ref=reference,select={'concepts':['{https://example.com/taxonomy}Cash']})
        result = tool, (dict(request=request) if tool == 'deliver' else dict(request=request,state=delta))
        self.requests.append(deepcopy(result))
        return result


class ScriptedModel(Model):
    offline_fixture = True

    def __init__(self, scenario='success'):
        self.script = Script(scenario)
        self.inputs = []

    async def get_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs):
        self.inputs.append(deepcopy(input))
        outputs = [json.loads(i['output']) for i in input if isinstance(i,dict) and i.get('type')=='function_call_output']
        action = self.script.next(outputs)
        if action:
            name, arguments = action
            output=[ResponseFunctionToolCall(type='function_call',name=name,arguments=json.dumps(arguments),call_id='call-'+str(self.script.count),id='tool-'+str(self.script.count))]
        else:
            output=[ResponseOutputMessage(id='fixture-final',type='message',role='assistant',status='completed',content=[ResponseOutputText(type='output_text',text='Synthetic terminal text',annotations=[])])]
        return ModelResponse(output=output,usage=Usage(requests=1),response_id='fixture-'+str(self.script.count),raw_usage=None)

    async def stream_response(self,*args,**kwargs):
        raise NotImplementedError('This fixture checks non-streaming OpenAI Runner only')
        yield


class SkillScriptedModel(ScriptedModel):
    """Native Skill calls followed by the same Data tools, without real inference."""
    async def get_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, **kwargs):
        names = [i['name'] for i in input if isinstance(i,dict) and i.get('type')=='function_call']
        self.inputs.append(dict(system=system_instructions,input=deepcopy(input),tools=[t.name for t in tools]))
        outputs=[]
        for item in input:
            if not isinstance(item,dict) or item.get('type')!='function_call_output':continue
            try:value=json.loads(item['output'])
            except (ValueError,TypeError):continue
            if isinstance(value,dict) and value.get('status') in {'ok','partial','error'}:outputs.append(value)
        if 'load_skill' not in names:
            name,args='load_skill',dict(skill_name='financial-data-query')
            identity='skill-load'
        elif 'exec_command' not in names:
            name,args='exec_command',dict(cmd='cat .agents/financial-data-query/SKILL.md',max_output_tokens=12000)
            identity='skill-read'
        else:
            self.script.count=len(outputs)
            action=self.script.next(outputs)
            if action is None:raise AssertionError('script should stop through accepted deliver')
            name,args=action;identity='data-'+str(self.script.count)
        return ModelResponse(output=[ResponseFunctionToolCall(type='function_call',name=name,
            arguments=json.dumps(args),call_id=identity,id='tool-'+identity)],usage=Usage(requests=1),
            response_id='fixture-'+identity,raw_usage=None)
