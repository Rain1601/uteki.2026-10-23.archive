"""Explicit pilot inputs. Reviewer answers never enter the model request."""
import hashlib
import importlib.metadata
import json
from pathlib import Path

from uteki.agents.data_query.coordinator import inspect_run
from uteki.agents.runtime.call_costs import pricing_snapshot
from uteki.domain.research_data.company_agent import CompanyQueryInput

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]


def write(path, value):
    with path.open('x') as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    prepared = ROOT / 'prepare-amd'
    inspect_run(prepared)
    inputs = ROOT / 'inputs'
    inputs.mkdir(exist_ok=False)
    questions = {
        'cashflow-source': '请在已选择的 AMD FY2023 10-K 冻结原文中，提取合并现金流量表中 '
            'Net cash provided by operating activities 这一行的原文证据，同时提取该表 FY2023 与 '
            'FY2022 的列标题和表内单位说明。任务是原文表格证据提取，不要求数值入库或计算。'
            '请保留源文精确引文及片段定位，明确无法从已读取正文确认的内容。',
        'business-source': '根据已选择的 AMD FY2023 10-K，说明该公司有哪些可报告业务分部，'
            '以及每个分部的主要产品。说明 All Other 是否属于可报告分部。用中文回答，'
            '每项事实附已回读原文的精确引文及片段定位，区分报告事实与自己的推断。'
            '仅使用本次选择的冻结财报，不进行网页补证。',
    }
    for case, question in questions.items():
        request = {'prepared_run': str(prepared), 'include_candidates': True,
            'question': question, 'limits': {'max_steps': 18, 'turn_timeout': 240,
                'max_packet_bytes': 180000, 'observation_bytes': 24000}}
        CompanyQueryInput.model_validate(request)
        write(inputs / (case + '.json'), request)
    write(inputs / 'sonnet-high.json', {'provider': 'aihubmix', 'model': 'claude-sonnet-5-5',
        'reasoning_effort': 'high', 'max_tokens': 8192, 'request_timeout': 180, 'max_retries': 0,
        'budget_ledger': str(ROOT / 'shared-budget.sqlite'), 'budget_usd': '2',
        'budget_policy': 'enforced', 'max_requests_total': 40})
    write(inputs / 'pricing.json', pricing_snapshot('aihubmix', 'claude-sonnet-5-5'))
    files = sorted(inputs.glob('*.json')) + sorted((REPO / 'src/uteki').rglob('*.py')) + [Path(__file__)]
    write(inputs / 'manifest.json', {'schema_version': 'runtime-pilot-inputs-v1',
        'source_manifest_sha256': hashlib.sha256((prepared / 'manifest.json').read_bytes()).hexdigest(),
        'files': {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        'dependencies': {name: importlib.metadata.version(name)
            for name in ('openai-agents', 'pydantic', 'httpx2', 'lxml', 'duckdb')},
        'evaluation': 'review/oracle.json is withheld from every model request',
        'sequence': ['cashflow-source', 'business-source'],
        'budget_scope': 'both cases and any repairs share the same enforced ledger'})


if __name__ == '__main__':
    main()
