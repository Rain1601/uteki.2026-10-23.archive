"""Persist one synthetic Planner -> Worker -> Planner run; no model or network calls."""
import argparse
import asyncio
import json
from pathlib import Path

from uteki.agents.data_query.artifacts import write_new
from uteki.agents.data_query.coordinator import CompanyDataCoordinator, inspect_run
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort
from tests.unit.test_autonomous_data_agent import ScriptedPlanner, read
from tests.unit.test_scoped_query_service import make_scoped_dataset, year
from tests.unit.test_task_completion import attach_synthetic_quotes


async def run(output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    dataset = output / 'synthetic-dataset'
    dataset.mkdir()
    make_scoped_dataset(dataset)
    attach_synthetic_quotes(dataset)
    before = {str(p.relative_to(dataset)): digest(p.read_bytes()) for p in dataset.rglob('*') if p.is_file()}
    with QueryDataPort(dataset) as port:
        scope = {'snapshot_id': port.snapshot_id, 'company_ids': ['acme'],
                 'source_snapshot_ids': ['acme-annual'], 'source_policy_id': 'local-frozen-v1',
                 'knowledge_cutoff': '2032-05-01', 'include_candidates': True}
    query = {'calculations': [{'formula_id': 'operating_margin', 'entity_id': 'acme-services',
                               'periods': [year(2031)]}]}
    numeric = {'action': 'query', 'requirement_ids': ['numbers'], 'plan': query}
    parent = ScriptedPlanner([
        {'action': 'plan', 'reason': 'Explicit synthetic acceptance task, not a model-generated plan.',
         'requirements': [
             {'kind': 'read_node', 'requirement_id': 'business', 'description': 'Read the complete business section.',
              'source_id': 'acme-annual', 'node_id': 'business'},
             {'kind': 'query', 'requirement_id': 'numbers', 'description': 'Verify calendar year 2031 operating margin.', 'query': query}]},
        {'action': 'delegate', 'requirement_ids': ['business', 'numbers'],
         'delegation': {'instruction': 'Read the assigned section and retrieve the registered calculation with its citations.'}},
        read(), numeric, {'action': 'finish'},
    ])
    worker = ScriptedPlanner([read(), numeric, {'action': 'finish'}])
    result = await CompanyDataCoordinator(output / 'workspace').query(
        {'dataset': str(dataset), 'scope': scope,
         'question': 'Read the complete business section and verify operating margin for calendar year 2031.',
         'limits': {'max_steps': 8, 'max_worker_steps': 3}},
        planner=parent, worker_planner=worker, output=output / 'run')
    verified = inspect_run(output / 'run')
    stored = json.loads((output / 'run/query/result.json').read_text())
    resumed = parent.packets[2]
    assert result['status'] == 'evidence_ready', result
    assert resumed['observation']['status'] == 'worker_returned'
    assert all(not row['evidence_ids'] for row in resumed['coverage'])
    assert stored['decision_budget'] == {'limit': 8, 'used': 8}
    assert before == {str(p.relative_to(dataset)): digest(p.read_bytes()) for p in dataset.rglob('*') if p.is_file()}
    verification = {'decision_source': 'scripted_fixture', 'external_model_calls': 0,
        'network_calls': 0, 'dataset_unchanged': True, 'manifest_status': verified['status'],
        'parent_decisions': len(parent.packets), 'worker_decisions': len(worker.packets),
        'shared_decision_budget': stored['decision_budget'], 'parent_resumed': True,
        'worker_did_not_satisfy_parent_coverage': True, 'status': result['status'],
        'semantic_completeness': 'not_evaluated', 'model_quality': 'not_evaluated'}
    write_new(output / 'verification.json', verification)
    (output / 'README.md').write_text('''# Worker 委派离线样例

这是 synthetic Acme 数据和两个脚本角色的运行记录，外部模型／网络调用均为 0。

- 输入：显式公司、日历年 2031、来源快照、截止日期及候选数据权限；完整 Business 和营业利润率两个要求。
- 动作：主角色制定要求 → Worker 读取原文并调用注册公式 → 主角色收到带来源结果 → 主角色自行读取与核对 → 完成。
- 输出：主角色 5 次、Worker 3 次决策，共享上限 8 次；父子各自保存输入、动作、证据及哈希清单。
- 边界：子任务返回时，主角色的证据覆盖仍为空；主角色随后通过自己的工具满足完成条件。证据均为候选，无自动采纳。

`verification.json` 保存检查结果；`run/query/turn-002/worker-handoff.json` 保存交接；
`run/query/turn-002/worker/` 是子任务完整记录；`run/query/result.json` 是主任务结果。

本样例验证程序交接、范围和取证条件，不验证真实模型规划、投资研究质量或多模型成本优势。
''')
    write_new(output / 'manifest.json', {'files': {str(p.relative_to(output)): digest(p.read_bytes())
        for p in sorted(output.rglob('*')) if p.is_file()}})
    return verification


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.output)), ensure_ascii=False, indent=2))
