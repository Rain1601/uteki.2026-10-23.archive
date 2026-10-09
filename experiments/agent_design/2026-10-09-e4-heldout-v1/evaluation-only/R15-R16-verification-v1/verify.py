"""Read-only real-history compatibility checks. Evaluation paths are explicit fixtures."""
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import sqlite3
from uteki.agents.data_query.answer_handoff import load_reviewed_data
from uteki.agents.data_query.question_coverage_review import validate_saved_question_review_repair
from uteki.domain.research_data.period_scope import explicit_periods, PERIOD_SCOPE_VERSION

ROOT = Path(__file__).resolve().parents[5]
EXPERIMENTS = ROOT/'experiments/agent_design'
def read(path): return json.loads(path.read_text())
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
paths = list(EXPERIMENTS.glob('2026-10-09-e*/runs/**/question-repair-input.json'))
tracked = set(paths)
for p in paths:
    tracked.update(p.parent/n for n in ('manifest.json','question-input.json','question-response-01.json'))
before = {str(p.relative_to(ROOT)):sha(p) for p in tracked}
transcripts=[]
for p in paths:
    manifest=read(p.parent/'manifest.json')['files']
    assert manifest[p.name] == sha(p)
    saved=read(p)
    validate_saved_question_review_repair(read(p.parent/'question-input.json'),
        read(p.parent/'question-response-01.json'), saved)
    transcripts.append({'path':str(p.relative_to(ROOT)), 'schema_version':saved['schema_version'],
                        'sha256':sha(p), 'exact_protocol_replay':'pass'})
consumers=[]
for sub,run in [('2026-10-09-e2-msft-10q-v1','E2-Q1-r3'),
                ('2026-10-09-e3-mixed-sources-v1','E3-V1-r2'),
                ('2026-10-09-e3-mixed-sources-v1','E3-M1-review-recovery-r2'),
                ('2026-10-09-e4-heldout-v1','E4-H1-r3'),
                ('2026-10-09-e4-heldout-v1','E4-H2-r2')]:
    p=EXPERIMENTS/sub/'runs'/run;r=read(p/'result.json');ref=r['final_review_ref']
    tracked.update((p/'manifest.json',p/'result.json'))
    for f in (p/'manifest.json',p/'result.json'):
        before[str(f.relative_to(ROOT))]=sha(f)
    load_reviewed_data(ref['path'], expected_scope=r['scope'],
                       expected_review_manifest_sha256=ref['manifest_sha256'])
    consumers.append({'run':run,'frozen_status':r['status'],'current_consumption':'pass'})
failures=[]
for run in ('E4-H1-r1','E4-H1-r2'):
    p=EXPERIMENTS/'2026-10-09-e4-heldout-v1/runs'/run
    review=p/'attempt-01/review-01';packet=read(review/'input.json')
    before[str((p/'manifest.json').relative_to(ROOT))]=sha(p/'manifest.json')
    before[str((p/'result.json').relative_to(ROOT))]=sha(p/'result.json')
    try:
        load_reviewed_data(review,expected_scope=packet['scope'],
                           expected_review_manifest_sha256=sha(review/'manifest.json'))
    except ValueError as error:
        failures.append({'run':run,'frozen_status':read(p/'result.json')['status'],
                         'current_consumption':'rejected','reason':str(error)})
    else: raise AssertionError('failed run became consumable: '+run)
assert all(sha(ROOT/p)==h for p,h in before.items())
mapping=[{'fiscal_year':2031,'fiscal_quarter':None,
          'period':{'kind':'year','start':'2031-01-01','end':'2031-12-31'}}]
period_cases=[]
for suffix,accepted in [('quality review',True),('question',True),('Q5',False),('Q0',False),('Q 5',False)]:
    text='FY2031 '+suffix
    periods=explicit_periods(text,fiscal_periods=mapping,require_fiscal_mapping=True)
    assert bool(periods)==accepted
    period_cases.append({'input':text,'accepted':accepted,'periods':[p.model_dump(mode='json') for p in periods]})
ledger=EXPERIMENTS/'2026-10-09-e2-msft-10q-v1/costs.sqlite'
with sqlite3.connect(ledger.as_uri()+'?mode=ro',uri=True) as c:
    rows=c.execute('select reserved,actual,state from reservations').fetchall()
    assert len(rows)==176 and all(state=='settled' and actual is not None for _,actual,state in rows)
    cost=sum((Decimal(actual) for _,actual,_ in rows),Decimal('0'))
    assert cost==Decimal('2.0569908')
    assert Decimal(c.execute('select usd from config').fetchone()[0])==3
result={'status':'pass','created_at':datetime.now(timezone.utc).isoformat(),
        'R15':{'transcripts':transcripts,'successful_consumption':consumers,'failed_runs_stay_rejected':failures,
               'new_repair_version':'question-review-protocol-repair-v2',
               'known_v1_variants':['original','scope','located'],
               'comparison':'full equality plus canonical JSON hash; no bool/integer or float/integer substitution'},
        'R16':{'period_scope_version':PERIOD_SCOPE_VERSION,'cases':period_cases},
        'historical_fingerprints_unchanged':before,
        'implementation_sha256':{p:sha(ROOT/p) for p in (
            'src/uteki/agents/data_query/question_coverage_review.py',
            'src/uteki/agents/data_query/answer_handoff.py','src/uteki/domain/research_data/period_scope.py')},
        'engineering_checks':{'R15_affected_modules':82,'R15_final_type_boundary_module':5,
                              'R16_affected_modules':76,'R16_final_version_module':14,
                              'note':'Overlapping rechecks; do not sum counts as unique tests.'},
        'api_calls_added':0,'shared_requests':176,'shared_estimated_usd':str(cost),
        'unknown_reserved_usd':'0','inflight':0,'hard_cap_usd':'3',
        'scope':'Engineering and read-only consumer replay; no new model evaluation or Analysis execution; no changed frozen standards/originals.'}
out=Path(__file__).with_name('result.json')
assert not out.exists()
out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print('PASS: 7 old transcripts; 5 successful consumers; 2 failures still blocked; original hashes and ledger unchanged; 0 API')
