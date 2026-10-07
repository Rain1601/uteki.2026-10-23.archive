"""Recover singleton typed envelopes and derive citation indexes; no factual edits/API."""
import json,sys,copy,hashlib
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];sys.path.insert(0,str(ROOT/'src'))
from uteki.agents.business_map.product_contract import validate_draft
from uteki.agents.business_map.product_run import materialize
from uteki.agents.runtime.observation import observed_run,observed_step
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
parent=HERE/'run-05-completed';out=HERE/'completed-candidate-v1'
if out.exists():raise ValueError('frozen_output_already_exists')
request=read(parent/'request.json');payload=json.loads(request['messages'][0]['content']);packet=read(parent/'source_packet.json');assert payload['frozen_source_packet']==packet
fields=read(parent/'response.txt');assert set(fields)=={'description_excerpts','added_business','added_relationship','unknowns'}
protocol=[]
for key in ('added_business','added_relationship'):
 if isinstance(fields[key],list):
  assert len(fields[key])==1 and isinstance(fields[key][0],dict)
  fields[key]=fields[key][0];protocol.append({'field':key,'action':'unwrap one-element object list; no values changed'})
final=copy.deepcopy(payload['prior_candidate']);rows=fields['description_excerpts'];expected=set(payload['review_feedback']['description_nodes'])
assert {r['node_id'] for r in rows}==expected and len(rows)==len(expected)
for row in rows:
 node=next(n for n in final['businesses'] if n['id']==row['node_id']);claim=next(c for c in node['claim_evidence'] if c['field']=='description');claim['excerpts']=row['excerpts']
 node['evidence_block_ids']=list(dict.fromkeys(node['evidence_block_ids']+[e['block_id'] for e in row['excerpts']]))
added,edge=fields['added_business'],fields['added_relationship'];assert added['id'] not in {n['id'] for n in final['businesses']} and edge['source_id']==added['id'] and edge['target_id']=='search_news_ads'
final['businesses'].append(added);final['relationships'].append(edge);final['unknowns']=fields['unknowns']
for i,e in enumerate(final['relationships']):
 refs=list(dict.fromkeys(x['block_id'] for x in e['excerpts']))
 if set(e['evidence_block_ids'])!=set(refs):
  protocol.append({'relationship_index':i,'before':e['evidence_block_ids'],'after':refs,'action':'derive redundant reference index from unchanged excerpts'});e['evidence_block_ids']=refs
assert all(not n[k] for n in final['businesses'] for k in ('products_services','customers','monetization'))
draft=validate_draft(final,packet,expected_version='business-draft-v2')
with observed_run(output=out,kind='extraction',role='repairer',origin='typed_graph_protocol_recovery',observation_root=ROOT/'data/agent_observability/local',scope={'company_id':packet['company_id'],'period_end':packet['period_end'],'task_type':'business_map'},title='业务图补全字段物化（零模型调用）') as context:
 out.mkdir()
 with observed_step(context,1,phase='恢复单项对象并校验全部出处') as step:
  for name in ['source_packet.json','skill.md','request.json','output_schema.json','configuration.json','response.txt','response_metadata.json']:(out/name).write_bytes((parent/name).read_bytes())
  manifest={**read(parent/'manifest.json'),'trace_id':context.run_id,'parent_trace_id':read(parent/'result.json')['trace_id'],'actual_model_response_trace_id':read(parent/'result.json')['trace_id'],'protocol_recovery':'singleton envelope normalization and redundant citation-index derivation','model_calls_in_this_trace':0,'materialization_script_sha256':sha(Path(__file__)),'model_response_sha256':sha(parent/'response.txt')}
  save(out/'manifest.json',manifest);save(out/'draft.json',draft.model_dump());save(out/'field-completion.json',fields);save(out/'protocol-projection.json',protocol)
  counts=materialize(draft,packet,root=ROOT,output=out,manifest=manifest,trace_id=context.run_id)
  result={**manifest,'status':'candidate','validation':'passed','counts':counts,'semantic_acceptance':'not_evaluated','artifacts_sha256':{n:sha(out/n) for n in ['business_map.json','evidence.html']},'budget':{'estimated_spent_usd':'0','held_usd':'0','unknown_requests':0,'in_flight_requests':0,'requests':0,'actual_billed_usd':None}}
  save(out/'result.json',result)
  for name in ['business_map.json','evidence.html','protocol-projection.json']:step.publish(out/name)
print(json.dumps({'status':'candidate','counts':counts,'trace_id':context.run_id,'model_calls':0}))
