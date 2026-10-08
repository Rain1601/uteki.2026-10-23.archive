"""Engineering checks over the two acquired originals, not model quality scores."""
from collections import defaultdict
from copy import deepcopy
import json
from pathlib import Path
from lxml import html

from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parents[1]


def main():
    dataset = HERE/'datasets/msft-two-annuals'
    source_runs = HERE/'acquisition/workspace/source-runs'
    first = json.loads((source_runs/'20261008T205046-a663c12323dd/manifest.json').read_text())
    second = json.loads((source_runs/'20261008T205136-4d90b9bab90e/manifest.json').read_text())
    assert first['requests'] == 3 and second['requests'] == 1
    assert {(d['source_id'], d['content_sha256'], d['path']) for d in first['documents']} == {
        (d['source_id'], d['content_sha256'], d['path']) for d in second['documents']}
    assert all(d['acquisition'] == 'reused_verified' for d in second['documents'])
    records = json.loads((dataset/'records.json').read_text())['rows']
    groups = defaultdict(list)
    for row in records:
        groups[(row['entity_id'], row['metric_id'], json.dumps(row['period'], sort_keys=True), row['value_kind'])].append(row)
    queries = []
    with QueryDataPort(dataset) as port:
        scope = {'snapshot_id': port.snapshot_id, 'company_ids': [first['company']['company_id']],
                 'source_snapshot_ids': [d['source_id'] for d in first['documents']],
                 'source_policy_id': 'local-frozen-v1', 'knowledge_cutoff': '2026-10-08', 'include_candidates': True}
        for key, rows in groups.items():
            if len({r['source_snapshot_id'] for r in rows}) < 2:
                continue
            request = {'query_id': 'foundation-'+str(len(queries)+1), 'snapshot_id': port.snapshot_id,
                       'knowledge_cutoff': scope['knowledge_cutoff'], 'include_candidates': True,
                       'records': [{'entity_id': key[0], 'metric_id': key[1],
                                    'period': json.loads(key[2]), 'value_kind': key[3]}]}
            result = port.scoped(scope).query_data(request)
            different_values = len({r['value_decimal'] for r in rows}) > 1
            statuses = [s['status'] for s in result['selections']]
            assert statuses == ['ambiguous' if different_values else 'matched']
            assert {r['record_id'] for r in result['records']} == {r['record_id'] for r in rows}
            per_source = []
            for source_id in scope['source_snapshot_ids']:
                narrowed = port.scoped({**scope, 'source_snapshot_ids': [source_id]}).query_data(request)
                assert all(r['source_snapshot_id'] == source_id for r in narrowed['records'])
                per_source.append({'source_snapshot_id': source_id,
                                   'statuses': [s['status'] for s in narrowed['selections']],
                                   'values': sorted({r['value_decimal'] for r in narrowed['records']})})
            queries.append({'request': request, 'statuses': statuses, 'occurrences': len(rows),
                            'records_retained': True, 'per_source': per_source})
        early = {**scope, 'knowledge_cutoff': '2024-12-31'}
        catalog = port.scoped(early).discover_data()
        assert {s['period_end'] for s in catalog['sources']} == {'2024-06-30'}
    old = ROOT/'experiments/agent_design/2026-10-09-data-agent-completion-v1/datasets/msft/raw/msft-2025-10k.html'
    new_source = next(d for d in first['documents'] if d['period_end'] == '2025-06-30')
    new = HERE/'acquisition/workspace'/new_source['path']
    def without_scripts(path):
        tree = html.document_fromstring(path.read_bytes())
        for script in tree.xpath('//script'):
            script.drop_tree()
        return html.tostring(tree)
    script_only_change = without_scripts(old) == without_scripts(new)
    assert script_only_change
    result = {'schema_version': 'e1-foundation-verification-v1', 'model_calls': 0,
              'kind': 'deterministic_engineering_checks_not_agent_evaluation',
              'repeat_acquisition': {'first_requests': first['requests'], 'repeat_requests': second['requests'],
                                     'verified_reused_documents': len(second['documents']), 'same_ids_hashes_paths': True},
              'cross_report_groups': len(queries),
              'equivalent_groups': sum(q['statuses'] == ['matched'] for q in queries),
              'conflicting_groups': sum(q['statuses'] == ['ambiguous'] for q in queries),
              'checks': queries,
              'cutoff_2024_12_31_sources': [s['source_snapshot_id'] for s in catalog['sources']],
              'fy2025_transport_decoration': {'old_raw_sha256': digest(old.read_bytes()),
                  'new_raw_sha256': digest(new.read_bytes()), 'old_bytes': old.stat().st_size, 'new_bytes': new.stat().st_size,
                  'dom_equal_after_removing_script_elements': script_only_change,
                  'raw_files_retained_unchanged': True,
                  'classification': 'transport_script_change_not_financial_restatement; comparison_diagnostic_only'},
              'limitations': ['No query reasoning or semantic completeness measured here',
                              'Conflicting numeric values need original context; no automatic restatement explanation',
                              'Script removal used only for diagnosis; originals and production hashes are not normalized']}
    with (HERE/'preparation/foundation-verification.json').open('x') as f:
        json.dump(result, f, ensure_ascii=False, indent=2); f.write('\n')
    print(json.dumps({k: result[k] for k in ('cross_report_groups','equivalent_groups','conflicting_groups')}))


if __name__ == '__main__':
    main()
