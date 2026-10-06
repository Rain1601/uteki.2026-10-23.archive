"""Real frozen company material through scripted tools; never a model benchmark.

Run from the repository with the installed local package. No expected financial
answer, company ID, source ID or chapter position is supplied to the planner.
"""
import argparse
import asyncio
import json
from pathlib import Path

from uteki.agents.data_query.coordinator import CompanyDataCoordinator, inspect_run


class ScriptedSmoke:
    plan_origin = 'scripted_fixture'

    def __init__(self, fiscal_year):
        self.fiscal_year = fiscal_year
        self.step = 0

    async def decide(self, packet):
        self.step += 1
        if self.step == 1:
            periods = [f for f in packet['catalog']['schema']['fiscal_periods']
                       if f['fiscal_year'] == self.fiscal_year and f['period']['kind'] == 'year']
            if len(periods) != 1:
                raise ValueError('smoke requires exactly one source-grounded annual period')
            fiscal, = periods
            self.source_id = fiscal['source_snapshot_id']
            self.query = {'records': [
                {'entity_id': fiscal['company_id'], 'metric_id': metric, 'period': fiscal['period']}
                for metric in ('revenue', 'operating_income')], 'calculations': [
                    {'formula_id': 'operating_margin', 'entity_id': fiscal['company_id'], 'periods': [fiscal['period']]}]}
            return {'action': 'plan', 'reason': 'Scripted numeric and source-reading integration check',
                    'requirements': [
                        {'requirement_id': 'financial', 'description': 'Revenue, operating income and margin',
                         'kind': 'query', 'query': self.query},
                        {'requirement_id': 'business', 'description': 'Business source excerpt'}]}
        if self.step == 2:
            return {'action': 'query', 'requirement_ids': ['financial'], 'plan': self.query}
        if self.step == 3:
            return {'action': 'outline_source', 'requirement_ids': ['business'],
                    'outline': {'source_snapshot_id': self.source_id}}
        if self.step == 4:
            nodes = [n for n in packet['observation']['result']['nodes']
                     if n['kind'] == 'item' and n.get('item_number') == '1']
            if len(nodes) != 1:
                return {'action': 'gap', 'requirement_ids': ['business'], 'reason': 'business_node_not_unique'}
            return {'action': 'read_source', 'requirement_ids': ['business'],
                    'read': {'source_snapshot_id': self.source_id, 'node_id': nodes[0]['node_id'], 'count': 12}}
        return {'action': 'finish'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared-run', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fiscal-year', type=int, required=True)
    args = parser.parse_args()
    request = {'question': f'Provide FY{args.fiscal_year} revenue and operating margin plus a Business source excerpt.',
               'prepared_run': str(args.prepared_run.resolve()), 'include_candidates': True,
               'limits': {'max_steps': 5}}
    result = asyncio.run(CompanyDataCoordinator(args.workspace).query(request,
        planner=ScriptedSmoke(args.fiscal_year), output=args.output))
    inspect_run(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'evidence_ready' else 2


if __name__ == '__main__':
    raise SystemExit(main())
