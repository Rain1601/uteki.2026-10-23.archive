"""At most two explicit native-schema probes; no business data or secret logs."""
import asyncio
from collections import Counter
from copy import deepcopy
import json
import os
from pathlib import Path
import time

from agents import ModelSettings
import httpx2 as httpx
from uteki.agents.data_query.autonomous import AutonomousDecision
from uteki.agents.runtime.local_credentials import load_provider_key
from uteki.agents.runtime.run_budget import RunBudget, reserve_request
from uteki.agents.runtime.call_costs import pricing_snapshot, estimate_anthropic_usage
from uteki.agents.runtime.claude_messages import ENDPOINT, _suppress_transport_logging, _numeric_usage
from uteki.infrastructure.research_data.financial_records import digest

ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parents[3]
REMOVED = {'minimum','maximum','exclusiveMinimum','exclusiveMaximum','multipleOf','minLength','maxLength',
           'maxItems','uniqueItems','if','then','else','not','discriminator'}


def transform(schema):
    removed = Counter()
    def walk(value):
        if isinstance(value,list):
            return [walk(v) for v in value]
        if not isinstance(value,dict):
            return value
        out = {}
        for key, val in value.items():
            if key in REMOVED or (key=='minItems' and val not in (0,1)):
                removed[key] += 1
                continue
            if key == 'pattern' and any(p in val for p in ('(?','\\b','\\B')):
                removed[key] += 1
                continue
            out[key] = walk(val)
        if out.get('type') == 'object':
            if out.get('additionalProperties') is not False:
                removed['open_object_closed'] += 1
            out['additionalProperties'] = False
        if out.get('allOf') and all(not v for v in out['allOf']):
            del out['allOf']
        return out
    return walk(schema), dict(removed)


def save(path, value):
    with path.open('x') as handle:
        json.dump(value,handle,ensure_ascii=False,indent=2)


async def one(name, schema, task, budget, pricing, key):
    folder = ROOT/name
    folder.mkdir(exist_ok=False)
    body = {'model':'claude-sonnet-5-5','max_tokens':1024,'stream':False,
        'thinking':{'type':'between_tools'},'output_config':{'effort':'high','format':{'type':'json_schema','schema':schema}},
        'system':'You are a stateless host decision component. This endpoint has no tools. Respond with one JSON object matching the supplied format; never use XML. No hidden reasoning is requested.',
        'messages':[{'role':'user','content':task}]}
    raw = json.dumps(body,ensure_ascii=False,separators=(',',':')).encode()
    save(folder/'request.json',body)
    token, reserved = reserve_request(budget,pricing,(),{'model_settings':ModelSettings(max_tokens=1024)},serialized_body=raw)
    receipt = {'schema_version':'native-json-probe-v1','probe':name,'request_sha256':digest(raw),
        'reservation_id':token,'reserved_usd':reserved,'budget_ledger':str(budget.path),'status':'started',
        'pricing_snapshot':pricing,'estimated_usd':None,'raw_usage':None,'hidden_thinking_saved':False}
    save(folder/'started.json',receipt)
    start=time.monotonic()
    try:
        with _suppress_transport_logging():
            async with httpx.AsyncClient(timeout=180,follow_redirects=False,trust_env=False,
                    transport=httpx.AsyncHTTPTransport(retries=0)) as client:
                response=await client.post(ENDPOINT,content=raw,headers={'x-api-key':key,
                    'anthropic-version':'2023-06-01','content-type':'application/json'})
        receipt['http_status']=response.status_code
        payload=response.json()
        usage,presence=_numeric_usage(payload.get('usage'))
        receipt.update(raw_usage=usage,usage_presence=presence)
        if presence=='reported': receipt['estimated_usd']=estimate_anthropic_usage(usage,pricing)
        if response.status_code!=200:
            error=payload.get('error',{})
            receipt.update(status='http_error',error_type=error.get('type'),
                error_message=str(error.get('message','')).replace(key,'[redacted]')[:2000])
        else:
            text=''.join(block.get('text','') for block in payload.get('content',[]) if block.get('type')=='text')
            save(folder/'visible-response.json',{'text':text})
            receipt.update(status='response_received',response_id=payload.get('id'),model=payload.get('model'),
                stop_reason=payload.get('stop_reason'),content_types=[b.get('type') for b in payload.get('content',[])])
            try:
                parsed=json.loads(text)
                if name=='simple':
                    assert set(parsed)=={'status','count'} and parsed['status']=='ok' and parsed['count']==2
                else:
                    AutonomousDecision.model_validate(parsed)
                receipt['local_validation']='passed'
            except Exception as error:
                receipt.update(local_validation='failed',validation_error_type=type(error).__name__)
    except Exception as error:
        receipt.update(status='transport_or_decode_failure',error_type=type(error).__name__)
    finally:
        budget.settle(token,receipt['estimated_usd'])
        receipt['elapsed_seconds']=round(time.monotonic()-start,3)
        save(folder/'receipt.json',receipt)
        save(folder/'manifest.json',{'files':{p.name:digest(p.read_bytes()) for p in folder.iterdir() if p.is_file()}})
    print(json.dumps(receipt,ensure_ascii=False),flush=True)
    return receipt


async def main():
    load_provider_key(REPOSITORY,'aihubmix')
    key=os.environ['AIHUBMIX_API_KEY']
    budget=RunBudget(ROOT.parent/'costs.sqlite',None,enforce=False,allow_unknown_reservations=True)
    pricing=pricing_snapshot('aihubmix','claude-sonnet-5-5')
    simple={'type':'object','properties':{'status':{'type':'string','enum':['ok']},'count':{'type':'integer'}},
        'required':['status','count'],'additionalProperties':False}
    first=await one('simple',simple,'Return status ok and count 2.',budget,pricing,key)
    if first.get('http_status')!=200 or first.get('local_validation')!='passed':
        return
    original=AutonomousDecision.model_json_schema()
    transformed,changes=transform(original)
    save(ROOT/'original-decision-schema.json',original)
    save(ROOT/'transformed-decision-schema.json',transformed)
    save(ROOT/'transform-report.json',{'changes':changes,'warning':'Compatibility probe only: closing open objects restricts allowed payloads; this is not a production schema transformation.'})
    await one('decision',transformed,'The only needed action now is discover_catalog. Return action discover_catalog and catalog {"kind":"sources"}; omit unrelated optional payloads. No source reading or tools are needed.',budget,pricing,key)


if __name__=='__main__': asyncio.run(main())
