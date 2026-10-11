"""Read-only selected-occurrence counterfactual; no API and no artifact resealing."""
import json,hashlib,copy,tempfile
from pathlib import Path
from uteki.agents.data_query.answer_handoff import _query_evidence_documents
from uteki.agents.data_query.record_selection_navigation import candidate_index,selection_effect,navigation_page
from uteki.infrastructure.research_data.run_artifacts import ArtifactStore,json_size
from uteki.infrastructure.research_data.run_artifacts import load_evidence_bundle
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.infrastructure.research_data.query_service import QueryDataPort
base=Path(__file__).resolve().parents[4]
reports=[]
for rep in ('R2','R3'):
 root=base/'output/e6-repeatability-20261010-r1'/rep/'S1/run-r1'
 query=root/'attempt-01/data-query/query'
 cfg=json.loads((root/'config.json').read_text())
 result=json.loads((query/'result.json').read_text())
 bundle=load_evidence_bundle(query)
 evidence={x['evidence_id']:x for x in bundle['items']}
 selection_step, tail_step = ('016','014') if rep=='R2' else ('011','009')
 actual_input=json.loads((query/f'turn-{selection_step}/input.json').read_text())
 tail_feedback=json.loads((query/f'turn-{tail_step}/feedback.json').read_text())
 tail_items=tail_feedback['result']['items']
 correct_origin=next(x for x in tail_items if x['evidence_id']=='ev-230effd83877e641d55c9cd2')
 assert correct_origin['citations'][0]['block_id']=='block-000753-53762a3b'
 assert actual_input['record_origins']['returned_count']==15
 assert actual_input['record_origins']['total_count']==18
 assert not any(x['evidence_id']==correct_origin['evidence_id'] for x in actual_input['record_origins']['items'])
 assert correct_origin['evidence_id'] not in json.dumps(actual_input['observation'])
 assert actual_input['state_reads']==[]
 origin_projection={'first_page_count':15,'total_count':18,'correct_origin_index_one_based':18,
   'previous_tail_read_step':int(tail_step),'selection_step':int(selection_step),
   'correct_origin_returned_on_previous_tail':True,'correct_id_in_current_coverage':True,
   'correct_citation_mapping_missing_from_current_navigation_and_observation':True,
   'old_first_page_geography_origin_remains_visible':True,
   'interpretation':'The immutable tail remains available through cursor, but previously viewed tail mapping is absent from the current isolated model packet. Bare coverage ID is not a source location.'}
 before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
 scope=ExecutionScope.model_validate(result['active_scope'])
 coverage_map={r['requirement_id']:r for r in result['coverage']}
 origin_ref=tail_feedback['artifact']
 origins_list=json.loads((query/origin_ref['path']).read_text())
 origins_map={r['evidence_id']:r for r in origins_list}
 original_origins_hash=hashlib.sha256((query/origin_ref['path']).read_bytes()).hexdigest()
 choices=candidate_index(coverage_map,evidence,origins_map,scope.model_dump(mode='json'))
 selected={r['requirement_id']:r['selected_record_ids'] for r in result['coverage'] if r['kind']=='query'}
 selected_body={r['requirement_id']:r['selected_blocks'] for r in result['coverage'] if r['kind']=='source_evidence'}
 effect=selection_effect(coverage_map,evidence,origins_map,selected,selected_body)
 assert any(r['evidence_id']=='ev-230effd83877e641d55c9cd2' and
            r['citations'][0]['block_id']=='block-000753-53762a3b' for r in choices['candidates'])
 assert len(choices['candidates'])==18
 assert not any(k in json.dumps(choices) for k in ('preferred_occurrence','suggested_selection','expected_answer'))
 assert any(r['block_id']=='block-000924-9c4544a8' for r in effect['record_citation_anchors'])
 assert not any(r['block_id']=='block-000924-9c4544a8' for r in effect['explicit_source_blocks'])
 assert any(r['block_id']=='block-000924-9c4544a8' and r['introduced_by']==['record_citation']
            for r in effect['combined_anchor_blocks'])
 with tempfile.TemporaryDirectory(prefix='e6-r2-independent-navigation-') as tmp:
  store=ArtifactStore(tmp)
  projected=navigation_page(store,'record-candidate-index',choices,scope=scope,step=int(selection_step),max_bytes=12000)
  shown=projected['value']
  correct_visible='ev-230effd83877e641d55c9cd2' in json.dumps(shown.get('candidates',[]))
  candidates_complete=shown.get('candidates')==choices['candidates'] and shown.get('criteria')==choices['criteria'] and shown.get('record_semantics')==choices['record_semantics'] and shown.get('query_scopes')==choices['query_scopes']
  if not candidates_complete or not correct_visible:
   failure={'schema_version':'independent-candidate-projection-probe-v1','case':rep+'-S1','api_calls':0,'metadata_bytes':json_size(choices),'budget_bytes':12000,'complete':projected['complete'],'correct_candidate_visible':correct_visible,'reads':projected['reads']}
   target=Path(__file__).with_name('independent-candidate-projection-failure.v1.json')
   if not target.exists():target.write_text(json.dumps(failure,ensure_ascii=False,indent=2))
  assert candidates_complete and correct_visible
  if not projected['complete']:
   assert projected['reads'] and all(r.get('pointer')=='/source_blocks' for r in projected['reads'])
  for row in choices['candidates']:
   original=evidence[row['evidence_id']]['value']
   fields=choices['record_semantics'][row['semantics_index']]
   assert all(original[k]==v for k,v in fields.items())
   for cit in row['citations']:
    old=next(c for c in origins_map[row['evidence_id']]['citations'] if c['citation_id']==cit['citation_id'])
    assert all(old[k]==v for k,v in cit.items())
  effect_projected=navigation_page(store,'record-selection-effect',effect,scope=scope,step=int(selection_step),max_bytes=12000)
  assert effect_projected['complete']
  saved_projection={'schema_version':'independent-runtime-navigation-projection-v1','case':rep+'-S1','api_calls':0,'inputs':'Original badselection and original immutable evidence; production navigation helpers, original 12000-byte budget.', 'candidate_artifact_value':choices,'candidate_model_projection':projected,'selection_effect_artifact_value':effect,'selection_effect_model_projection':effect_projected}
  Path(__file__).with_name(f'catalog-projection-{rep}-S1.v1.json').write_text(json.dumps(saved_projection,ensure_ascii=False,indent=2))
 assert original_origins_hash==hashlib.sha256((query/origin_ref['path']).read_bytes()).hexdigest()
 catalog_audit={'candidate_count':18,'metadata_bytes':json_size(choices),
   'runtime_budget_bytes':12000,'projection_complete':projected['complete'],'complete_candidates_criteria_semantics':candidates_complete,'projection_omissions':projected['reads'],
   'income_fy24_candidate_visible_without_tail_read':correct_visible,
   'old_wrong_record_selection_remains_selected':True,
   'geography_anchor_introduced_only_by_record_selection':True,
   'no_preferred_choice_or_gold':True,'unchanged_original_origin_artifact':True,
   'source_body_reading_established':projected['source_body_reading_established'],
   'selection_effect_complete':effect_projected['complete']}
 coverage=copy.deepcopy(result['coverage'])
 wrong='ev-8fc3b75577bd953f6a0986f8';correct='ev-230effd83877e641d55c9cd2'
 old=evidence[wrong]['value'];new=evidence[correct]['value']
 same_fields=['entity_id','metric_id','period','value_decimal','value_kind','unit','source_snapshot_id']
 assert all(old[k]==new[k] for k in same_fields)
 assert old['evidence_ids'] !=new['evidence_ids']
 for row in coverage:
  if wrong in row.get('selected_record_ids',[]):
   assert correct in row['evidence_ids']
   row['selected_record_ids']=[correct if x==wrong else x for x in row['selected_record_ids']]
 with QueryDataPort(Path(cfg['request']['dataset'])) as port:
  scoped=port.scoped(scope)
  original=_query_evidence_documents(scoped,scope,bundle,result['coverage'],240000,result['delivery_schema_version'])
  changed=_query_evidence_documents(scoped,scope,bundle,coverage,240000,result['delivery_schema_version'])
 def ids(docs):return [[d['source_snapshot_id'],[b['block_id'] for b in d['blocks']]] for d in docs]
 after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
 assert before==after
 reports.append({'case':rep+'-S1','new_catalog_audit':catalog_audit,'navigation_projection':origin_projection,'same_fact_fields':same_fields,'old_record':wrong,'alternate_returned_record':correct,'fact_values_equal':True,'citations_not_rewritten':True,'source_evidence_selection_unchanged':True,'baseline_original_blocks':ids(original),'counterfactual_original_blocks':ids(changed),'original_files_unchanged_count':len(before),'interpretation':'Only in-memory occurrence selection changed. Engineering assembly counterfactual, not new Agent run or content acceptance.'})
Path(__file__).with_name('independent-causal-audit.v2.json').write_text(json.dumps({'schema_version':'e6-r2-readonly-causal-counterfactual-v1','api_calls':0,'reports':reports},ensure_ascii=False,indent=2))
print(json.dumps(reports,ensure_ascii=False,indent=2))
