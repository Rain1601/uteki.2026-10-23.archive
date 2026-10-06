"""Independent extraction scoring. Gold is evaluation-only and never imported by runners.

Numerical checks require independently reviewed record matching. Semantic fields,
qualifiers and completeness are adjudicated against sources, never keyword scored.
"""
from __future__ import annotations
import argparse, hashlib, json, re
from decimal import Decimal, InvalidOperation
from pathlib import Path

SCALES={'USD':Decimal(1),'USD_units':Decimal(1),'USD_millions':Decimal(10)**6,'USD_billions':Decimal(10)**9,'USD_thousands':Decimal(10)**3}
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def amount(value,unit):
    if unit not in SCALES or value is None:return None
    text=str(value).strip().replace(',','').replace('$','').replace('−','-')
    if text.startswith('(') and text.endswith(')'):text='-'+text[1:-1]
    if not re.fullmatch(r'-?\d+(?:\.\d+)?',text):return None
    try:return Decimal(text)*SCALES[unit]
    except InvalidOperation:return None

def evaluate(gold_path,outputs_path,review_path=None):
    gold=json.loads(Path(gold_path).read_text()); outputs=json.loads(Path(outputs_path).read_text())
    notes=json.loads(Path(review_path).read_text()) if review_path else {}
    if review_path and (notes.get('gold_sha256')!=sha(gold_path) or notes.get('outputs_sha256')!=sha(outputs_path)):
        raise ValueError('Independent review must bind exact gold and output bytes')
    cases=[]
    for case in gold['cases']:
        cid=case['case_id']; out=outputs.get('cases',{}).get(cid);note=notes.get('cases',{}).get(cid,{})
        if out is None:
            cases.append({'case_id':cid,'status':'missing_output','required_facts':len(case['facts'])});continue
        records=out.get('records',[]);ids=[r.get('draft_id') for r in records]
        if len(ids)!=len(set(ids)):raise ValueError('duplicate draft_id in '+cid)
        byid={r.get('draft_id'):r for r in records};facts=[];used=[]
        for fact in case['facts']:
            n=note.get('facts',{}).get(fact['fact_id'],{});rid=n.get('draft_id');record=byid.get(rid)
            if rid is not None:used.append(rid)
            expected_amount=amount(fact['value'],fact['unit'])
            if expected_amount is None:raise ValueError('invalid gold amount')
            numeric=(amount(record.get('value'),record.get('unit'))==expected_amount) if record else False
            semantic_fields=['metric','entity','period','value_relation','evidence']
            fields={k:n.get(k,'pending') for k in semantic_fields}
            semantic_pass=all(v=='pass' for v in fields.values()) and bool(n.get('explanation'))
            facts.append({'fact_id':fact['fact_id'],'draft_id':rid,'numeric_equivalent':numeric,
                          'semantic_fields':fields,'explanation':n.get('explanation'),
                          'status':'pass' if numeric and semantic_pass else 'fail' if n and (not numeric or 'fail' in fields.values()) else 'pending_review'})
        if len(used)!=len(set(used)):raise ValueError('one draft record cannot satisfy multiple atomic facts in '+cid)
        requirements=[]
        for requirement in case['semantic_requirements']:
            n=note.get('requirements',{}).get(requirement['requirement_id'],{})
            status=n.get('status','pending_review')
            if status=='pass' and not n.get('explanation'):status='pending_review'
            requirements.append({'requirement_id':requirement['requirement_id'],'status':status,'explanation':n.get('explanation')})
        extra=note.get('additional_records',{})
        extra_status=extra.get('status','pending_review')
        if extra_status=='pass' and (not extra.get('explanation') or set(extra.get('reviewed_draft_ids',[]))!=set(ids)-set(used)):
            extra_status='pending_review'
        states=[x['status'] for x in facts+requirements]+[extra_status]
        status='pass' if all(x=='pass' for x in states) else 'fail' if 'fail' in states else 'pending_independent_review'
        cases.append({'case_id':cid,'status':status,'facts':facts,'requirements':requirements,'additional_records_status':extra_status,
                      'observed_records':len(records),'required_facts':len(facts),'facts_passed':sum(x['status']=='pass' for x in facts)})
    return {'schema_version':'extraction-ab-independent-evaluation-v1','gold_sha256':sha(gold_path),'outputs_sha256':sha(outputs_path),
            'review_sha256':sha(review_path) if review_path else None,'cases':cases,
            'case_passes':sum(c['status']=='pass' for c in cases),'case_total':len(cases),
            'limitations':['Independent source review is required for record matching, semantic fields, qualifiers, unknown handling and extra-record precision.',
                          'Numeric equivalence does not establish metric, period, attribution or evidence correctness.',
                          'Gold covers explicitly requested facts within selected units, not full-document recall.']}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--gold',required=True);p.add_argument('--outputs',required=True);p.add_argument('--review');p.add_argument('--output',required=True);a=p.parse_args()
    result=evaluate(a.gold,a.outputs,a.review)
    with Path(a.output).open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps({'case_passes':result['case_passes'],'case_total':result['case_total']}))
if __name__=='__main__':main()
