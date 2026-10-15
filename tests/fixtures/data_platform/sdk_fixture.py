"""Scripted synthetic peer. These actions/answers never enter production code."""
from copy import deepcopy
import json
from pathlib import Path
import runpy

from agents import Model, ModelResponse, Usage
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText


def case():
    cls = runpy.run_path(str(Path(__file__).resolve().parents[2]/'unit/data_platform/test_queries.py'))['DataToolTests']
    value = cls()
    try:
        value.setUp()
        return value
    except BaseException:
        value.doCleanups()
        raise


class Script:
    def __init__(self, scenario='success'):
        self.scenario = scenario
        self.count = 0
        self.requests = []

    def next(self, outputs):
        step = self.count
        self.count += 1
        if self.scenario == 'free_text' or (self.scenario not in {'success','tool_error'} and step) or (self.scenario == 'tool_error' and step > 1):
            return None
        state = dict(satisfied=[], gaps=[dict(need_id='cash', missing='Read synthetic source and cash comparison')],
            next_action='find_assets', reason='Scripted synthetic step')
        if step == 0:
            state['plan_update'] = dict(base_version=0, needs=[dict(need_id='cash', description='Synthetic cash comparison and source', required=True)])
        tool, request = 'find_assets', dict(filters={})
        if self.scenario == 'invalid_arguments':
            return tool, dict(unexpected='invalid')
        if self.scenario == 'forged_delivery':
            tool = 'deliver'
            request = dict(needs=[dict(need_id='cash', status='supported', result_refs=[dict(run_id='run_00000000000000000000000000',operation_id='op_00000000000000000000000000',kind='record',item_id='invented')],gaps=[])])
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
                refs = [outputs[4]['items'][0]['result_ref'],outputs[6]['calculations'][0]['result_ref']]
                state.update(satisfied=[dict(need_id='cash',result_refs=refs)],gaps=[])
                tool, request = 'deliver', dict(needs=[dict(need_id='cash',status='supported',result_refs=refs,gaps=[])])
            else:
                return None
        state['next_action'] = tool if self.scenario != 'tool_error' else 'unknown-action'
        if self.scenario == 'tool_error':
            if step:
                tool,request='query_records',dict(asset_ref=reference,select={'concepts':['{https://example.com/taxonomy}Cash']})
            state['next_action']=tool
        result = tool, dict(request=request,state=state)
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
