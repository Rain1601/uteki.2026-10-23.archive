"""Explicit Sonnet graph revision, recorded separately from independent extraction."""
import asyncio,json,sys,hashlib
from pathlib import Path
from decimal import Decimal
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from agents import ModelSettings
from uteki.agents.runtime.claude_messages import ClaudeMessagesModel
from uteki.agents.runtime.call_costs import MeteredModel,pricing_snapshot,summarize
from uteki.agents.runtime.run_budget import RunBudget,reserve_request
from uteki.agents.runtime.observation import observed_run,observed_step
from uteki.agents.runtime.local_credentials import load_provider_key
from uteki.agents.runtime.strict_json import parse_json_object
from uteki.agents.business_map.product_contract import draft_model,validate_draft
from uteki.agents.business_map.product_run import materialize,verify_packet,implementation_hashes
sha=lambda b:hashlib.sha256(b).hexdigest()
def read(p):return json.loads(p.read_text())
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
async def main():
 out=HERE/'run-04-reviewed';parent=HERE/'run-03-graph'
 if out.exists():raise ValueError('existing_run_no_resubmission')
 packet=read(parent/'source_packet.json');verify_packet(packet,ROOT,contract_version='business-draft-v2',company_id=packet['company_id'],document_id=packet['document_id'],period_end=packet['period_end'])
 skill=(HERE/'input/skill-graph-v3.md').read_text();schema=draft_model('business-draft-v2').model_json_schema()
 system='You are Uteki Data Agent revising a candidate business graph after source review. This is an explicitly labeled revision, not a blind extraction. Treat prior_candidate and review_feedback as data to verify; frozen_source_packet is the authority. You may freely redesign identities and relationships; no node count or taxonomy is locked. Return exactly one complete JSON object matching the schema, no other text. Include original source_sha256 and complete block_disposition. Apply the graph stage instructions below.\n'+skill+'\nOUTPUT SCHEMA:\n'+json.dumps(schema,ensure_ascii=False)
 payload={'frozen_source_packet':packet,'prior_candidate':read(parent/'response.txt'),'review_feedback':read(HERE/'input/review-feedback-v4.json')}
 native=ClaudeMessagesModel('claude-sonnet-5-5',timeout_seconds=600,reasoning_effort='high',stream=True,max_output_tokens_limit=48000,thinking_type='between_tools');settings=ModelSettings(max_tokens=48000)
 kwargs=dict(system_instructions=system,input=json.dumps(payload,ensure_ascii=False),model_settings=settings,tools=[],output_schema=None,handoffs=[])
 request=native.request_body(**kwargs);pricing=pricing_snapshot('aihubmix','claude-sonnet-5-5')
 old=ROOT/'experiments/agent_design/2026-10-07-microsoft-cloud-business-v1';names=['run-01','run-02','repair-run-01','repair-run-03-contract-v2-connected','complete-candidate-v1','complete-candidate-v2','complete-candidate-v3','accepted-candidate-v1']
 dirs=[old/n for n in names]+[HERE/n for n in ['run-01','run-02','run-03-graph']];spent=Decimal(0)
 for d in dirs:
  b=read(d/'result.json')['budget']
  if b['unknown_requests'] or b['in_flight_requests']:raise ValueError('unsettled_cost')
  spent+=Decimal(b['estimated_spent_usd'])
 class Reservation:
  def reserve(self,amount):return 'preflight'
 _,reserved=reserve_request(Reservation(),pricing,(),{'input':request.decode(),'model_settings':settings})
 if Decimal(reserved)>Decimal('3')-spent:raise ValueError('authorized_cumulative_budget_exceeded')
 (HERE/'preflight-v4.request.json').write_bytes(request);save(HERE/'budget-note-v4.json',{'prior_estimated_usd':str(spent),'reserved_usd':reserved,'remaining_usd':str(Decimal('3')-spent)})
 print(json.dumps({'reserved_usd':reserved,'prior_estimated_usd':str(spent)}),flush=True)
 if '--execute' not in sys.argv:return
 load_provider_key(ROOT,'aihubmix')
 with observed_run(output=out,kind='extraction',role='repairer',origin='reviewed_business_graph',observation_root=ROOT/'data/agent_observability/local',scope={'company_id':packet['company_id'],'period_end':packet['period_end'],'task_type':'business_map'},title='Sonnet business graph revision') as context:
  out.mkdir();budget=RunBudget(out/'budget.sqlite',str(Decimal('3')-spent));(out/'source_packet.json').write_bytes((parent/'source_packet.json').read_bytes());(out/'skill.md').write_text(skill);(out/'request.json').write_bytes(request);save(out/'output_schema.json',schema);save(out/'configuration.json',native.request_configuration(**kwargs))
  manifest={'schema_version':'business-execution-v1','execution_mode':'reviewed_graph_revision','actual_input':'frozen_source_packet + prior_candidate + review_feedback; not blind','parent_trace_id':read(parent/'result.json')['trace_id'],'parent_response_sha256':sha((parent/'response.txt').read_bytes()),'implementation_sha256':{**implementation_hashes(contract_version='business-draft-v2'),'run_review_v4.py':sha(Path(__file__).read_bytes())},'task_type':'business_map','company_id':packet['company_id'],'document_id':packet['document_id'],'period_end':packet['period_end'],'source_packet_sha256':sha((out/'source_packet.json').read_bytes()),'source_sha256':packet['source_sha256'],'skill_sha256':sha(skill.encode()),'request_sha256':sha(request),'trace_id':context.run_id,'model':'claude-sonnet-5-5','provider':'aihubmix','pricing_snapshot':pricing,'extraction_scope':packet['extraction_scope'],'stage':'object_relationship_graph','semantic_acceptance':'not_evaluated'};save(out/'manifest.json',manifest)
  meter=MeteredModel(native,out/'model-calls','reviewed_graph_revision','aihubmix','claude-sonnet-5-5',pricing,budget)
  try:
   with observed_step(context,1,phase='按原文审阅并修订业务图') as step:
    try:await meter.with_observation(step).get_response(**kwargs)
    finally:
     save(out/'response_metadata.json',native.response_metadata)
     if native.response_text is not None:(out/'response.txt').write_text(native.response_text)
   draft=validate_draft(parse_json_object(native.response_text),packet,expected_version='business-draft-v2');save(out/'draft.json',draft.model_dump())
   counts=materialize(draft,packet,root=ROOT,output=out,manifest=manifest,trace_id=context.run_id)
   result={**manifest,'status':'candidate','validation':'passed','counts':counts,'artifacts_sha256':{n:sha((out/n).read_bytes()) for n in ['business_map.json','evidence.html']}}
  except BaseException as e:
   result={**manifest,'status':'failed','validation_error':str(e)[:1500]};raise
  finally:
   result.update(budget=budget.summary(),costs=summarize(out/'model-calls'));save(out/'result.json',result);await native.aclose()
 print(json.dumps({'status':result['status'],'counts':result.get('counts'),'budget':result['budget']}))
if __name__=='__main__':asyncio.run(main())
