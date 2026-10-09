"""Offline tool audit only; never input to a production Agent or model evaluation.

The four expected facts were independently read from the original income statement.
This fixture tests query grounding/read/handoff, not autonomous source selection.
"""
import asyncio
import json
from pathlib import Path

from uteki.agents.data_query.answer_handoff import prepare_review_packet
from uteki.agents.data_query.autonomous import AutonomousDataAgent
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.domain.research_data.period_scope import explicit_periods
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort


class ScriptedPlanner:
    plan_origin = 'scripted_fixture'

    def __init__(self, actions):
        self.actions = iter(actions)

    async def decide(self, packet):
        return next(self.actions)


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / 'preparation-v1/dataset'
EXPECTED = [
    ('quarter', '2025-01-01', '2025-03-31', '70066000000'),
    ('quarter', '2024-01-01', '2024-03-31', '61858000000'),
    ('ytd', '2024-07-01', '2025-03-31', '205283000000'),
    ('ytd', '2023-07-01', '2024-03-31', '180395000000'),
]


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def signature(record):
    p = record['period']
    return (p['kind'], p['start'], p['end'], record['value_decimal'])


def main():
    output = ROOT / 'evaluation-only/gates-v4'
    output.mkdir(exist_ok=False)
    question = ('以2025-05-31为资料可得截止日，提取 Microsoft 公司整体收入及原文单位、期间依据：'
                '单季度 2025-01-01 至 2025-03-31；单季度 2024-01-01 至 2024-03-31；'
                '累计期间 2024-07-01 至 2025-03-31；累计期间 2023-07-01 至 2024-03-31。')
    with QueryDataPort(DATASET) as owner:
        source, = owner.sources
        scope = ExecutionScope(snapshot_id=owner.snapshot_id, company_ids=(source['company_id'],),
            source_snapshot_ids=(source['source_snapshot_id'],), source_policy_id='local-frozen-v1',
            knowledge_cutoff='2025-05-31', include_candidates=True)
        port = owner.scoped(scope)
        periods = explicit_periods(question, require_fiscal_mapping=True, knowledge_cutoff=scope.knowledge_cutoff)
        assert len(periods) == 4
        plan = {'records': [{'entity_id': source['company_id'], 'metric_id': 'revenue',
                            'period': p.model_dump(mode='json'), 'value_kind': 'actual'} for p in periods]}
        headers = dict(query_id='quarter-gates', question=question, snapshot_id=scope.snapshot_id,
            source_policy_id=scope.source_policy_id, knowledge_cutoff=str(scope.knowledge_cutoff), include_candidates=True)
        schema, discovery = port.get_schema(), port.discover_data()
        save(output/'schema.json', schema)
        save(output/'discovery.json', discovery)
        coverage = [c for c in discovery['coverage'] if c['entity_id'] == source['company_id'] and c['metric_id'] == 'revenue']
        assert {(c['period_kind'], c['period_start'], c['period_end']) for c in coverage} == {e[:3] for e in EXPECTED}
        result = port.query_data({**headers, **plan})
        save(output/'typed-query.json', result)
        assert len(result['records']) == 16
        assert {signature(r) for r in result['records']} == set(EXPECTED)
        assert all(r['unit'] == 'USD' and r['dimensions'] == {} and r['available_at'] == '2025-04-30' for r in result['records'])
        assert all(s['status'] == 'matched' and s['occurrence_count'] == 4 for s in result['selections'])
        assert not result['computed_facts']
        # Reading by independently checked original location is a tool fixture,
        # not a production planner's source-navigation result.
        block = 'block-000032-4d792bdd'
        full = port.read_context(source_snapshot_id=source['source_snapshot_id'], block_id=block)
        compact = port.read_context(source_snapshot_id=source['source_snapshot_id'], block_id=block, representation='compact')
        save(output/'read-full.json', full)
        save(output/'read-compact.json', compact)
        assert full['status'] == compact['status'] == 'read'
        full_table = next(b for b in full['blocks'] if b['block_id'] == block)
        compact_table = next(b for b in compact['blocks'] if b['block_id'] == block)
        fields = compact_table['table']['cell_fields']
        restored = [dict(zip(fields, cell)) for cell in compact_table['table']['cells']]
        assert restored == full_table['table']['cells']
        assert full_table['text'] == compact_table['text']
        for printed in ('70,066', '61,858', '205,283', '180,395', 'In millions', 'Three Months', 'Nine Months'):
            assert printed in full_table['text'], printed
        # No wrong issuer, cutoff, or absent quarter may fall back to this data.
        try:
            port.query_data({**headers, 'records': [{**plan['records'][0], 'entity_id': 'unrelated-company'}]})
        except ValueError:
            pass
        else:
            raise AssertionError('wrong issuer accepted')
        missing = port.query_data({**headers, 'records': [{**plan['records'][0], 'period': {
            'kind': 'quarter', 'start': '2024-10-01', 'end': '2024-12-31'}}]})
        assert not missing['records']
        early_scope = scope.model_copy(update={'knowledge_cutoff': __import__('datetime').date(2025, 4, 29)})
        early = owner.scoped(early_scope)
        assert not early.discover_data()['coverage']
        assert early.read_context(source_snapshot_id=source['source_snapshot_id'], block_id=block)['status'] == 'not_available_at_cutoff'
        actions = [
            {'action': 'plan', 'reason': 'Offline fixture of explicitly declared dates.', 'requirements': [{
                'kind': 'query', 'requirement_id': 'quarter-and-cumulative-revenue', 'description': question, 'query': plan}]},
            {'action': 'query', 'requirement_ids': ['quarter-and-cumulative-revenue'], 'plan': plan},
            {'action': 'select_records', 'requirement_ids': ['quarter-and-cumulative-revenue'],
             'record_selection': {'record_ids': ['ev-' + digest({'kind': 'record', 'value': r,
                 'scope': scope.model_dump(mode='json')})[:24] for r in result['records']]},
             'reason': 'Offline fixture retains all equivalent occurrences to check original bindings.'},
            {'action': 'finish'},
        ]
        run = output/'scripted-query'
        fixture = asyncio.run(AutonomousDataAgent(owner, ScriptedPlanner(actions), purpose='analysis_evidence',
            limits={'max_steps': 4, 'max_packet_bytes': 640000, 'observation_bytes': 100000}).run(
                {'question': question, 'scope': scope.model_dump(mode='json')}, output=run))
        assert fixture['status'] == 'evidence_ready', fixture['trace']
        _verify_manifest(run)
        packet = prepare_review_packet(run, DATASET, expected_scope=scope, max_packet_bytes=1000000,
                                       source_delivery='query_evidence_v1')
        save(output/'review-packet.json', packet)
        assert packet['query_plan_origin'] == 'scripted_fixture'
        assert len(packet['facts']) == 16 and {signature(f['value']) for f in packet['facts']} == set(EXPECTED)
        assert not packet['query_gaps'] and not packet['program_gaps']
        original_blocks = {(d['source_snapshot_id'], b['block_id']): b
                           for d in packet['source_documents'] for b in d['blocks']}
        for fact in packet['facts']:
            assert fact['citations']
            for c in fact['citations']:
                assert c['source_snapshot_id'] == source['source_snapshot_id']
                text = original_blocks[(c['source_snapshot_id'], c['block_id'])]['text']
                assert c['quote'] == text[c['char_start']:c['char_end']]
                assert c['text_hash'] == digest(text.encode('utf-8'))
        summary = {'audit_version': 'e2-quarter-revenue-gates-v1', 'execution': 'scripted_tool_fixture',
            'model_calls': 0, 'http_requests': 0, 'api_cost_usd': '0', 'status': 'bounded_slice_passed',
            'dataset_manifest_sha256': digest((DATASET/'manifest.json').read_bytes()),
            'original_sha256': source['source_sha256'], 'expected_original_facts': [list(e) for e in EXPECTED],
            'unique_fact_count': 4, 'equivalent_occurrence_count': 16, 'occurrences_summed': False,
            'checks': ['exact kind/start/end and USD scale', 'scoped schema and discovery',
                       'four equivalent occurrences per query criterion', 'full/compact cells identical',
                       'wrong issuer and pre-publication cutoff rejected; absent quarter not substituted',
                       'autonomous host typed grounding and record selection (scripted decisions)',
                       'sealed run integrity and original citation replay'],
            'not_evaluated': ['autonomous model selection', 'semantic sufficiency or focus of final model delivery',
                              'entire quarterly filing', 'comparative fiscal-label mappings', 'unsupported concepts']}
        save(output/'audit.json', summary)
        print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
