"""Offline evaluator probe. Gold is used only here, never by the runtime Agent.

This verifies prepared data and query boundaries, not model planning or selection.
"""
import argparse
from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path

from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort


def check(preparation, output):
    preparation, output = Path(preparation).resolve(), Path(output).resolve()
    if output.exists() or output.is_relative_to(preparation):
        raise ValueError('new evaluation output outside frozen preparation required')
    _verify_manifest(preparation)
    dataset = preparation / 'dataset'
    before = digest((dataset / 'manifest.json').read_bytes())
    scope = json.loads((preparation / 'scope.json').read_text())
    standard_path = Path(__file__).with_name('standard.v1.json')
    standard = json.loads(standard_path.read_text())
    checks, receipts = [], []
    with QueryDataPort(dataset) as owner:
        port = owner.scoped(scope)
        companies = {row['company_id'] for row in standard['mandatory']}
        assert set(scope['company_ids']) == companies
        assert {s['company_id'] for s in port.discover_data()['sources']} == companies
        for expected in standard['mandatory']:
            child = port.for_query_source(expected['source_snapshot_id'])
            schema = child.get_schema()
            mappings = [m['period'] for m in schema['fiscal_periods']
                        if m['company_id'] == expected['company_id']
                        and m['fiscal_year'] == expected['fiscal_year']]
            unique = {json.dumps(p, sort_keys=True): p for p in mappings}
            assert len(unique) == 1, 'missing or ambiguous source-bound fiscal mapping'
            period = next(iter(unique.values()))
            assert all(period[k] == v for k, v in expected['period'].items())
            request = {'query_id': expected['requirement_id'], 'question': 'Evaluator tool probe; no model',
                       **{k: scope[k] for k in ('snapshot_id', 'source_policy_id', 'knowledge_cutoff', 'include_candidates')},
                       'records': [{'entity_id': expected['company_id'], 'metric_id': 'revenue', 'period': period}]}
            result = child.query_data(request)
            assert result['records'], 'required prepared fact absent'
            for record in result['records']:
                assert record['entity_id'] == expected['company_id']
                assert record['source_snapshot_id'] == expected['source_snapshot_id']
                assert record['accounting_basis'] == 'reported_consolidated'
                assert record['unit'] == 'USD'
                assert Decimal(record['value_decimal']) == Decimal(expected['value_usd'])
                assert all(record['period'][k] == v for k, v in expected['period'].items())
                assert record['evidence_ids']
            assert all(ev['source_snapshot_id'] == expected['source_snapshot_id'] for ev in result['evidence'].values())
            other = next(c for c in companies if c != expected['company_id'])
            invalid = {**request, 'records': [{**request['records'][0], 'entity_id': other}]}
            try:
                child.query_data(invalid)
            except ValueError:
                pass
            else:
                raise AssertionError('single-source query accepted another company')
            receipts.append({'request': request, 'result': result})
            checks.append({'requirement_id': expected['requirement_id'], 'prepared_value_matches_original': True,
                           'own_fiscal_mapping': period, 'equivalent_occurrences': len(result['records']),
                           'other_company_rejected': True})
        early = (min(date.fromisoformat(s['available_at']) for s in port.sources) - timedelta(days=1)).isoformat()
        earlier = owner.scoped({**scope, 'knowledge_cutoff': early})
        assert earlier.discover_data()['sources'] == []
        assert earlier.get_schema()['fiscal_periods'] == []
    _verify_manifest(preparation)
    assert before == digest((dataset / 'manifest.json').read_bytes())
    output.mkdir(parents=True)
    (output / 'tool-receipts.json').write_text(json.dumps(receipts, ensure_ascii=False, indent=2) + '\n')
    result = {'schema_version': 'e5-prepared-query-check-v1', 'status': 'passed',
              'mode': 'scripted_evaluator_tool_probe_not_model_run', 'model_calls': 0,
              'standard_sha256': digest(standard_path.read_bytes()), 'dataset_manifest_sha256': before,
              'checks': checks, 'cutoff_hides_unavailable_sources_and_fiscal_metadata': True,
              'frozen_preparation_unchanged': True,
              'not_evaluated': ['model planning', 'model reading', 'model selection', 'model review', 'repeatability']}
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preparation', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.preparation, args.output), ensure_ascii=False, indent=2))
