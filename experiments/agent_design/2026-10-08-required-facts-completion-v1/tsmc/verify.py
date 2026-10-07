"""Independent source-cell review of this real two-table run; no model calls."""
import json
from pathlib import Path
from decimal import Decimal

import duckdb

from uteki.infrastructure.research_data.fact_completion import verify_completion_publication
from uteki.infrastructure.research_data.financial_records import digest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]


def main():
    run=HERE/'run-02'
    result=json.loads((run/'result.json').read_text())
    packet=json.loads((run/'packet.json').read_text())
    normalized=json.loads((run/'normalized.json').read_text())
    assert result['present_fact_count']==6 and result['unresolved_count']==0
    assert len(result['stages'])==4 and result['selected_batch_indexes']==[0,1]
    names=['packet.json','result.json','normalized.json','extraction.json','method-snapshot.json']
    for stage in result['stages']: names += [stage['path']+'/input.json',stage['path']+'/output.json']
    publication=verify_completion_publication(run,ROOT/'data/agent_observations',names)
    checks=[]
    for row in normalized['records']:
        raw=row['origin']['raw']
        label=raw['metric'].split(': ',1)[-1]
        candidates=[]
        for block in packet['blocks']:
            cells=(block.get('table') or {}).get('cells',[])
            for cell in cells:
                if cell['text']!=label: continue
                for value in cells:
                    if value['row']!=cell['row']: continue
                    text=value['text']
                    if text.startswith('(') and not text.endswith(')'):
                        close=next((c for c in cells if c['row']==value['row'] and c['column']==value['column']+value['colspan'] and c['text']==')'),None)
                        if close: text+=' '+close['text']
                    if text!=raw['value']: continue
                    years=[c for c in cells if c['text']==row['period']['end'][:4] and c['row']<cell['row'] and
                           c['column']<=value['column']<c['column']+c['colspan']]
                    currencies=[c for c in cells if c['text']=='NT$' and c['row']<cell['row'] and
                                c['column']<=value['column']<c['column']+c['colspan']]
                    if years and currencies: candidates.append((block,cell,value,text))
        assert len(candidates)==1
        block,label_cell,value_cell,text=candidates[0]
        parsed=Decimal(text.strip('() ').replace(',',''))*(-1 if text.startswith('(') else 1)
        assert parsed*1000000==Decimal(row['value_decimal']) and row['unit']=='TWD'
        refs=[normalized['evidence'][eid] for eid in (*row['evidence_ids'],*row['qualifier_evidence_ids'])]
        for ref in refs:
            source=next(b for b in packet['blocks'] if b['block_id']==ref['block_id'])
            assert source['text'][ref['source_start']:ref['source_end']]==ref['quote']
            assert digest(source['text'].encode())==ref['text_hash']
        assert any('(In Millions of New Taiwan Dollars or U.S. Dollars)' in ref['quote'] for ref in refs)
        if row['metric_id']=='capex_cash_payments':
            assert any('Acquisitions of:' in ref['quote'] for ref in refs)
            cells=block['table']['cells']
            hierarchy=[c for c in cells if c['column']==0 and c['row']<label_cell['row'] and c['text'].endswith(':')]
            assert max(hierarchy,key=lambda c:c['row'])['text']=='Acquisitions of:'
        checks.append({'record_id':row['record_id'],'metric_id':row['metric_id'],'period':row['period'],
            'raw_value':raw['value'],'value_decimal':row['value_decimal'],'unit':'TWD',
            'table':block['block_id'],'row':label_cell['row'],'column':value_cell['column'],
            'source_value_year_currency_scale_sign_and_quote':'passed'})
    db=duckdb.connect(str(run/'dataset/research.duckdb'),read_only=True)
    try:
        saved=dict(db.execute('SELECT record_id,value_decimal FROM observations').fetchall())
        assert saved=={r['record_id']:Decimal(r['value_decimal']) for r in normalized['records']}
    finally: db.close()
    baseline=json.loads((run/'initial-coverage.json').read_text())
    progress=[sum(i['status']=='candidate_present' for i in json.loads(p.read_text())['requirements'])
              for p in sorted(run.glob('coverage-*.json'))]
    assert all(i['status']=='not_extracted' for i in baseline['requirements']) and progress==[3,6]
    report={'kind':'real_two_table_completion_source_review','new_model_calls_in_review':0,
        'agent_run_trace_id':result['trace_id'],'requirements_progress':[0,*progress],
        'checks':checks,'sql_projection':'matched','original_publication':publication,
        'task_budget':result['budget'],'semantic_scope':'six selected source cells only',
        'whole_filing_and_accounting_framework':'not_evaluated',
        'batch_gap_boundary':'Original batch-local gap statements remain preserved; the opposite table was subsequently supplied and its three facts are now covered.'}
    (HERE/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'source_cell_checks':len(checks),'requirements_progress':[0,*progress],'task_budget':result['budget']}))


if __name__=='__main__':main()
