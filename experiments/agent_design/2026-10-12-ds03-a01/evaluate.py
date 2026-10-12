"""Independent offline checks; never imported or supplied to the acquisition model."""
import hashlib
import json
from pathlib import Path
from uteki.infrastructure.document_sources.official_discovery import _text
from uteki.agents.data_query.artifacts import write_new

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'output/ds03-a01-20261012'
CASES=[('TSM',BASE/'r2/tsm', ['TSMC 2025 Annual Report Website','2025 Financial Performance',
    'Consolidated revenue reached NT$3,809.05 billion']),
    ('MSFT',BASE/'msft-r2/msft',['Microsoft 2025 Annual Report','Microsoft Corporation',
    'INCOME STATEMENTS (In millions, except per share amounts) Year Ended June 30, 2025'])]

def sha(raw):return hashlib.sha256(raw).hexdigest()
def main():
    results=[]
    for company,path,quotes in CASES:
        report=json.loads((path/'source-run.json').read_bytes())
        task=json.loads((path/'input.json').read_bytes())['task']
        frontier=set(task['roots']);observed=set();errors=[]
        for actionfile in sorted(path.glob('turn-*-decision.json')):
            action=json.loads(actionfile.read_bytes())
            if action['action']!='acquire':continue
            arguments=action['arguments']['official'];assert arguments['url'] in frontier
            obs=json.loads(actionfile.with_name(actionfile.name.replace('-decision','-observation')).read_bytes())
            if obs['status']=='observed':
                observed.add(obs['page_url']);frontier.update(link['url'] for link in obs['links'])
            elif obs['status']=='gap':errors.append(obs)
        assert len(report['documents'])==1
        doc=report['documents'][0];raw=(BASE/'workspace'/doc['path']).read_bytes()
        assert sha(raw)==doc['content_sha256'];assert doc['source_url'] in observed
        text,_=_text(raw);assert all(q in text for q in quotes)
        assert doc['status']=='frozen_pending_review' and not doc['as_of_eligible'] and doc['available_at'] is None
        assert doc['transport']['http_status']==200
        usage=json.loads((path/'usage.json').read_bytes())['summary']['calls']
        results.append({'company':company,'verdict':'limited_acquisition_pass',
            'reviewer':'Codex independent inspection of archived original and discovery chain',
            'source_url':doc['source_url'],'final_url':doc['transport']['final_url'],
            'original_sha256':sha(raw),'evidence_quotes':quotes,'original_bytes':len(raw),
            'source_run_sha256':sha((path/'source-run.json').read_bytes()),
            'model_requests':usage['requests'],'estimated_usd':usage['known_estimated_usd'],
            'http_requests_including_redirects':report['requests'],'rejected_selections':len(errors),
            'scope':'One official HTML annual report or substantive annual-report part; no full financial-package acceptance',
            'remaining':['first_publication_unknown','no_historical_cutoff_adoption','no_long_term_stability'],
            'model_self_review':'selection reasons only; no separate model audit used as acceptance'})
    result={'schema':'ds03-a01-independent-review-v1','cases':results,
        'first_attempt':'APIConnectionError; 1 unknown request retained, no document; see original tsm-r1 and its usage',
        'source_run_metadata_correction':'TSM source-run model_calls=0 is incorrect; preserved unchanged. Usage establishes 5 real requests; corrected in subsequent MSFT run.'}
    write_new(BASE/'independent-review.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
