"""One USD 3 task boundary against the original cumulative E1 ledger."""
from decimal import Decimal
from pathlib import Path
import json,sqlite3
from uteki.agents.runtime.run_budget import RunBudget,BudgetExceeded
ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'output/figure-materials-20261012'
LEDGER=ROOT/'experiments/agent_design/2026-10-09-e1-benchmark-v1/costs.sqlite'
def state():
    with sqlite3.connect(LEDGER.as_uri()+'?mode=ro',uri=True) as db:
        rows={i:{'reserved':r,'actual':a,'state':s} for i,r,a,s in db.execute('select id,reserved,actual,state from reservations')}
        limit=db.execute('select usd from config').fetchone()[0]
    return {'limit':limit,'rows':rows,'occupied':str(sum((Decimal(v['actual'] if v['state']=='settled' else v['reserved']) for v in rows.values()),Decimal(0))), 'unknown':sorted(k for k,v in rows.items() if v['state']=='unknown')}
class TaskBudget(RunBudget):
    def __init__(self):
        path=BASE/'budget-baseline.json'
        if not path.exists():
            with path.open('x') as f:json.dump(state(),f,indent=2)
        self.baseline=json.loads(path.read_text())
        super().__init__(LEDGER,self.baseline['limit'],allow_unknown_reservations=True)
    def reserve(self,amount):
        current=state();old=self.baseline
        if current['limit']!=old['limit'] or current['unknown']!=old['unknown'] or any(current['rows'].get(k)!=v for k,v in old['rows'].items()):
            raise BudgetExceeded('Shared ledger changed or new unknown charges; reconcile before dispatch')
        if Decimal(current['occupied'])-Decimal(old['occupied'])+Decimal(str(amount))>Decimal('3'):
            raise BudgetExceeded('Figure materials task USD 3 boundary reached')
        return super().reserve(amount)
