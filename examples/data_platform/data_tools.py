"""Execute an explicit offline tool scenario and freeze a source-bound delivery.

The request contains registered context fields, a need plan, explicit tool
requests, and caller-selected delivery references. It contains no gold answers.
No network, SDK, model, company, period or data-root default is supplied.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from uteki.data_platform.catalog import Catalog
from uteki.data_platform.contracts.common import canonical
from uteki.data_platform.contracts.query import ReadPolicy, parse
from uteki.data_platform.service import DataService


def visible_results(value):
    if isinstance(value,dict):
        if 'result_ref' in value:
            yield value
        # Persisted responses use canonical object-key order. Traverse payload
        # fields in their semantic order so replay builds the identical request.
        order=('items','evidence','context_evidence','supporting_records','calculations')
        keys=[key for key in order if key in value]+sorted(set(value)-set(order))
        for key in keys:
            yield from visible_results(value[key])
    elif isinstance(value,list):
        for child in value:
            yield from visible_results(child)


def execute(catalog, request):
    policy = parse(ReadPolicy,request['read_policy'])
    administration = catalog.start_run(request['request_key']+':read-policy',purpose='register caller reviewed read policy',kind='read')
    if administration['status']=='running':
        catalog.register_policy(request['context']['source_policy_ref'],definition=policy.canonical_bytes().decode(),run_id=administration['run_id'])
        catalog.finish_run(administration['run_id'],status='completed')
    else:
        registered=catalog._get('policies','policy_ref',request['context']['source_policy_ref'])
        if json.loads(registered['payload'])['definition']!=policy.canonical_bytes().decode():
            raise ValueError('completed example policy registration differs from request')
    service = DataService(catalog)
    context = service.create_context(request['context'],request_key=request['request_key'])
    context_ref = context['context_ref']
    responses = {}
    for number,step in enumerate(request['steps']):
        state = dict(satisfied=[],gaps=[dict(need_id=n['need_id'],missing='Program scenario has not yet requested delivery',result_refs=[]) for n in request['needs']],
            next_action=step['tool'],reason=step['reason'])
        if number == 0:
            state['plan_update'] = dict(base_version=0,needs=request['needs'])
        response = service.call(context_ref,step['tool'],step['request'],state=state,request_key=request['request_key']+':'+step['id'])
        responses[step['id']] = response
        if response['status']=='error':
            return dict(status='failed',context=context,responses=responses,failed_step=step['id'],model_calls=0)
    needs = []
    for need in request['delivery_needs']:
        refs = []
        for selector in need['selectors']:
            matches = list(visible_results(responses[selector['step']]))
            matches = [v for v in matches if v['result_ref']['kind']==selector['kind']]
            if selector.get('calc_id') is not None:
                matches = [v for v in matches if v.get('calc_id')==selector['calc_id']]
            if not matches:
                raise ValueError('delivery selector has no actual returned result')
            refs.extend(v['result_ref'] for v in matches)
        refs = list({canonical(r):r for r in refs}.values())
        needs.append(dict(need_id=need['need_id'],status=need['status'],result_refs=refs,gaps=need['gaps'],note=need.get('note')))
    state = dict(next_action='deliver',reason='Caller requests delivery of these program-visible results',
        satisfied=[dict(need_id=n['need_id'],result_refs=n['result_refs']) for n in needs if n['status']=='supported'],
        gaps=[dict(need_id=n['need_id'],missing=n['gaps'][0],result_refs=n['result_refs']) for n in needs if n['status']!='supported'])
    delivery = service.deliver(context_ref,dict(needs=needs),state=state,request_key=request['request_key']+':delivery')
    return dict(status='completed',context=context,responses=responses,delivery=delivery,
        model_calls=0,autonomous_agent_evaluated=False,business_sufficiency_evaluated=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root',type=Path,required=True)
    parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        parser.error('output exists; retain it and choose a new path')
    request=json.loads(args.request.read_bytes())
    with Catalog.open(args.data_root) as catalog:
        result=execute(catalog,request)
    if result['status']=='completed':
        with Catalog.open(args.data_root) as catalog:
            restored=DataService(catalog).read_delivery(result['context']['context_ref'])
            if restored != result['delivery']['delivery']:
                raise ValueError('delivery changed after reopening')
        result['reopened']=True
    with args.output.open('x') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
    print(json.dumps(dict(status=result['status'],output=str(args.output),model_calls=0)))
    if result['status']!='completed':
        raise SystemExit(1)


if __name__=='__main__':
    main()
