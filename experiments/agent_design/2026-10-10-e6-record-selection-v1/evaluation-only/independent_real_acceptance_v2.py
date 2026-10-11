"""Independent raw-original/focus/prefix-tail audit; no API, no runtime changes."""
import argparse
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
from uteki.agents.data_query import answer_handoff as h,retrieval_cycle as cycle
from uteki.infrastructure.research_data.financial_records import digest

ROOT=Path(__file__).resolve().parents[4]
EXP=Path(__file__).resolve().parent.parent
OUTPUT=ROOT/'output/e6-record-selection-20261010-r1'
STANDARD=ROOT/'experiments/agent_design/2026-10-10-e6-material-scale-v1/evaluation-only/standard.v1.json'
read=lambda p:json.loads(p.read_bytes())
spec=importlib.util.spec_from_file_location('previous_independent_raw_audit',ROOT/'experiments/agent_design/2026-10-10-e6-source-citation-v1/evaluation-only/independent_real_audit.py')
rawaudit=importlib.util.module_from_spec(spec);spec.loader.exec_module(rawaudit)


def exact_body_exposure(packet,inputs):
    checks=[]
    for document in packet['source_documents']:
        for block in document['blocks']:
            matches=[]
            for path,turn in inputs:
                if any(item.get('source_snapshot_id')==document['source_snapshot_id'] and
                       item.get('block_id')==block['block_id'] and item.get('text')==block['text']
                       for item in turn.get('retained_body',{}).get('items',[])):
                    matches.append(str(path.relative_to(ROOT)))
            checks.append({'source_snapshot_id':document['source_snapshot_id'],'block_id':block['block_id'],
                'exact_original_text_exposed_to_real_tail_or_fresh_model':bool(matches),'first_input':matches[0] if matches else None})
    assert all(c['exact_original_text_exposed_to_real_tail_or_fresh_model'] for c in checks)
    return {'verdict':'pass','checks':checks,'boundary':'Full text actually supplied to a model-bound decision packet; model comprehension is independently assessed from delivered evidence, not claimed from exposure.'}


def semantic_focus(packet):
    # Evaluation-only original task semantics. Multiple equivalent origins permitted;
    # no unique accepted block ID or shortest-output threshold.
    checks=[];tables=[]
    for document in packet['source_documents']:
        for block in document['blocks']:
            text=block['text'];kind=block['type']
            if block.get('layout_role') or kind=='page_marker':
                checks.append({'source_snapshot_id':document['source_snapshot_id'],'block_id':block['block_id'],
                    'assessment':'bounded_layout','reason':'Frozen parser-labelled navigation layout. It supplies no optional score and is disclosed as overhead; do not count a layout table as an additional equivalent financial table.',
                    'layout_role':block.get('layout_role'),'text_characters':len(text)})
                continue
            if kind=='table':
                tables.append((document['source_snapshot_id'],block))
                assert ('Total revenue' in text or 'Revenues' in text or 'Total revenues' in text)
                assert 'Year Ended' in text
                assert '2025' in text and '2024' in text
                checks.append({'source_snapshot_id':document['source_snapshot_id'],'block_id':block['block_id'],
                    'assessment':'necessary','reason':'Company-wide income statement supplies both requested annual totals; remaining statement rows share the same indivisible table.'})
            else:
                short_heading=kind=='heading_candidate'
                units='in millions' in text.lower()
                entity=text.strip() in {'Alphabet Inc.','Microsoft Corporation'}
                layout=bool(block.get('layout_role')) or kind=='page_marker'
                assert short_heading or units or entity or layout, (block['block_id'],text)
                assert not ('disaggregated by geography' in text or 'Regions represent' in text)
                checks.append({'source_snapshot_id':document['source_snapshot_id'],'block_id':block['block_id'],
                    'assessment':'supporting_context' if not layout else 'bounded_layout','reason':'Statement/company/unit context retained; optional layout is disclosed separately.'})
    # This task needs just annual total revenues; an additional geographic/segment
    # total table is redundant when the income statement already covers both years.
    for sid in {d['source_snapshot_id'] for d in packet['source_documents']}:
        own=[b for source,b in tables if source==sid]
        assert len(own)==1,('Extra equivalent table requires independent semantic review',sid,len(own))
    return {'verdict':'pass','necessary_coverage_separate_from_focus':True,
        'table_count':len(tables),'block_count':len(checks),'checks':checks,
        'limits':'Task-specific raw-original independent acceptance; no preferred block or minimum-byte rule supplied to runtime. Broader tasks may legally require several tables.'}


def model_inputs(query,model):
    packets={digest(json.dumps(read(p),ensure_ascii=False)): (p,read(p)) for p in sorted(query.glob('turn-*/input.json'))}
    actual=[];seen=set();records=[]
    forbidden=('evaluation-only','standard.v1.json','independent-causal-audit','CAUSAL_AUDIT','"value_usd"','"mandatory"','source-response.json')
    for file in sorted(model.glob('decision-*-attempt-*.json')):
        decision=read(file);sha=decision['packet_sha256']
        assert sha in packets,('Model input not bound to runtime turn',file)
        path,packet=packets[sha]
        content=json.dumps(packet,ensure_ascii=False)
        assert not any(marker in content for marker in forbidden),('Evaluation leakage',file)
        assert 'review_feedback' not in packet,('Review feedback supplied to first attempt',path)
        for callref in decision['calls']:
            callfile=model/callref['path'];assert digest(callfile.read_bytes())==callref['sha256']
        if sha not in seen:actual.append((path,packet));seen.add(sha)
        records.append({'decision_record':str(file.relative_to(ROOT)),'query_input':str(path.relative_to(ROOT)),
            'packet_sha256':sha,'status':decision['status'],'role':decision['role'],'calls':decision['calls']})
    assert actual
    return actual,records


def run(case_id):
    case=next(c for c in read(EXP/'execution-matrix.v1.json')['cases'] if c['id']==case_id)
    root=OUTPUT/case_id/'run-r1'
    assert (root/'manifest.json').exists(),'Wait for sealed terminal run; do not assess a moving run.'
    before={str(p):digest(p.read_bytes()) for p in root.rglob('*') if p.is_file()}
    cycle._verify_manifest(root)
    result=read(root/'result.json');assert result['status']=='reviewed_data_ready',result['status']
    assert len(result['attempts'])==1,'Original no-recovery acceptance must not count a recovery as first-pass.'
    ref=result['final_review_ref'];review=Path(ref['path'])
    cycle._verify_manifest(review,ref['manifest_sha256'])
    packet=read(review/'input.json');query=Path(packet['query_ref']['path']);model=query.parent/'model'
    assessment,eligible=h.validate_saved_assessment(review,packet)
    review_result=read(review/'result.json')
    assert eligible and review_result['assessment']==assessment and review_result['status']=='reviewed'
    _,source_eligible=h._validate_source_assessment(packet,read(review/'source-response.json'))
    assert source_eligible
    independent={'raw_content':rawaudit.raw_content_check(packet),'source_protocol':{'legal':True,'eligible':source_eligible},
        'question_protocol_repair_attempted':review_result.get('question_protocol_repair_attempted',False),
        'source_protocol_repair_attempted':review_result.get('source_protocol_repair_attempted',False),
        'combined_assessment_eligible':eligible,'review_failures':review_result['failures']}
    try:
        loaded=h.load_reviewed_data(review,expected_scope=packet['scope'],expected_review_manifest_sha256=ref['manifest_sha256'])
    except ValueError as error:
        assert case.get('prefix') and str(error)=='scripted fixture cannot enter real Analysis',str(error)
        independent['strict_production_gate']={'result':'expected_fixture_rejection','message':str(error),'allow_fixture_used':False,'production_handoff_ready':False}
    else:
        assert not case.get('prefix'),'Controlled fixture unexpectedly crossed the production gate'
        independent['strict_production_gate']={'result':'passed','handoff_id':loaded['handoff_id'],'allow_fixture_used':False,'production_handoff_ready':True}
    freeze=read(EXP/'evaluation-only/execution-freeze.v1.json')
    standard_relative=str(STANDARD.relative_to(ROOT))
    assert freeze['files'][standard_relative]==digest(STANDARD.read_bytes())
    cfg=read(ROOT/case['config']);old=read(ROOT/'output/e6-repeatability-20261010-r1/R2/S1/run-r1/config.json')
    assert cfg['request']['question']==old['request']['question']
    assert cfg['request']['scope']==old['request']['scope']
    assert cfg['request']['limits']==old['request']['limits']
    actual,model_records=model_inputs(query,model)
    prefix_report=None
    if case.get('prefix'):
        prefix=read(ROOT/case['prefix'])['decisions'];n=len(prefix)
        original=ROOT/case['original_query_ref']
        origin=read(model/'controlled-prefix-origin.json')
        assert origin['not_fresh_autonomous_run'] and origin['prefix_decisions']==n
        assert origin['gold_or_review_feedback_supplied'] is False
        assert origin['original_max_steps_preserved']==cfg['request']['limits']['max_steps']
        assert len(list(model.glob('controlled-prefix-[0-9]*.json')))==n
        for ordinal,expected in enumerate(prefix,1):
            path=query/f'turn-{ordinal:03d}'
            assert read(path/'decision.json')==expected==read(original/f'turn-{ordinal:03d}/decision.json')
            control=read(model/f'controlled-prefix-{ordinal:04d}.json')
            assert control['model_call'] is False and control['decision']==expected
            assert control['current_packet_sha256']==digest(read(path/'input.json'))
        first=read(model/'first-real-tail-input.json')
        assert first==read(query/f'turn-{n+1:03d}/input.json')
        assert model_records[0]['query_input'].endswith(f'turn-{n+1:03d}/input.json')
        assert first['steps_remaining']==cfg['request']['limits']['max_steps']-n
        decision=read(query/f'turn-{n+1:03d}/decision.json')
        assert decision['action']=='select_records',decision['action']
        ids=decision['record_selection']['record_ids']
        candidates=first['record_candidate_index']['value']['candidates']
        selected=[r for r in candidates if r['evidence_id'] in ids]
        assert len(selected)==len(ids)
        anchors=[c for r in selected for c in r['citations'] if c['role']=='evidence_ids']
        assert all(c['block_id']=='block-000753-53762a3b' for c in anchors)
        assert 'ev-8fc3b75577bd953f6a0986f8' not in ids
        prefix_report={'prefix_decisions':n,'prefix_model_calls':0,'first_real_tail_turn':n+1,
            'steps_remaining_preserves_original_limit':first['steps_remaining'],
            'first_model_selection':ids,'first_model_citation_anchors':anchors,
            'wrong_original_occurrence_not_selected':True,'original_prefix_actions_equal':True,
            'gold_or_original_review_feedback_present':False,'not_fresh_end_to_end':True}
    else:
        assert not list(model.glob('controlled-prefix*'))
        assert model_records[0]['query_input'].endswith('turn-001/input.json')
    full=exact_body_exposure(packet,actual)
    focus=semantic_focus(packet)
    q=read(review/'question-response.json');assert q['question_coverage']=='complete'
    source_calls=len(list((review/'model/calls').glob('*-end.json')))
    question_calls=len(list((review/'question-model/calls').glob('*-end.json')))
    planner_calls=len(list((model/'calls').glob('*-end.json')))
    cost=sum((Decimal(read(p)['estimated_usd']) for p in root.rglob('calls/*-end.json')),Decimal(0))
    current={str(p):digest(p.read_bytes()) for p in root.rglob('*') if p.is_file()};assert before==current
    report={'schema_version':'e6-r2-independent-real-acceptance-v1','case_id':case_id,'api_calls':0,
        'operation':case['operation'],'frozen_standard_sha256':digest(STANDARD.read_bytes()),
        'sealed_run_manifest_sha256':digest((root/'manifest.json').read_bytes()),
        'raw_original_and_strict_review':independent,'prefix_tail_boundary':prefix_report,
        'actual_model_decision_inputs':model_records,'original_full_text_model_exposure':full,
        'independent_semantic_focus':focus,'run_files_unchanged':len(before),'independent_evaluation_helper_version':'v2: frozen layout role classified before structural table type; business standard unchanged','actual_api_call_breakdown':{'planner':planner_calls,'source_review':source_calls,'question_review':question_calls,'known_estimated_usd':str(cost)},'acceptance':'content_and_expected_gate_pass' if case.get('prefix') else 'fresh_full_handoff_pass'}
    dest=EXP/'evaluation-only'/f'{case_id}-acceptance.v1.json'
    with dest.open('x') as file:json.dump(report,file,ensure_ascii=False,indent=2);file.write('\n')
    print(json.dumps({'case':case_id,'acceptance':'pass','mandatory':'4/4','focus':'pass','block_count':focus['block_count'],
        'actual_model_decisions':len(actual),'prefix_decisions':prefix_report['prefix_decisions'] if prefix_report else 0,'report':str(dest.relative_to(ROOT))}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--case',required=True);run(parser.parse_args().case)
