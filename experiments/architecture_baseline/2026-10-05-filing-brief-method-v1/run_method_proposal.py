"""One real design response through Uteki's existing metered model adapter.

An explicit experiment, not a filing-brief agent or production task binding.
No annual-report extraction, tool browsing, adoption or database ingestion.
"""
import asyncio
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel
from uteki.agents.data_query.record_review_model import SdkRecordReviewer
from uteki.agents.runtime.run_budget import RunBudget

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / 'experiments/architecture_baseline/2026-10-04-amd-tsmc-annual-v1/model-config-v2.json'
PROMPT = '''你是 Uteki 数据处理方法的设计者。请独立回答提供的问题，专业、具体、可实施，允许提出比任务描述更好的建议。提供的背景用于确定产品边界，不是财报原始证据。不要声称已读取链接、已提取年报或已完成系统实现。不要编造公司数值。你没有拿到另一位参与者的答案。请用中文在 answer_markdown 中给出完整方案，并列出尚未确定的问题。只返回符合给定 schema 的 JSON。'''


class Proposal(BaseModel):
    answer_markdown: str
    uncertainties: list[str]


async def main():
    cfg = json.loads(CONFIG_PATH.read_text())
    packet = json.loads((HERE / 'common-input.json').read_text())
    teacher = HERE / 'codex-proposal.md'
    model_output = HERE / 'deepseek-method-proposal'
    if model_output.exists():
        raise FileExistsError('Existing experiment output; do not overwrite or rerun silently')
    manifest = {
        'evaluation_kind': 'method_design_only',
        'runtime_adapter': 'SdkRecordReviewer',
        'not_a_filing_brief_execution': True,
        'common_input_sha256': hashlib.sha256((HERE / 'common-input.json').read_bytes()).hexdigest(),
        'codex_pre_response_sha256': hashlib.sha256(teacher.read_bytes()).hexdigest(),
        'model_config_path': str(CONFIG_PATH.relative_to(ROOT)),
        'model_config_sha256': hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest(),
        'provider': cfg['provider'], 'model': cfg['planner_model'],
        'reasoning_effort': cfg['planner_reasoning_effort'],
        'comparison_limits': ['Codex current conversation has additional history', 'No annual report has been independently extracted in this experiment'],
        'request_policy': 'one design request; no automatic retries',
        'cost_policy': 'existing record-only shared ledger; no user cost ceiling',
        'status': 'started',
    }
    with (HERE / 'manifest.json').open('x') as file:
        json.dump(manifest, file, ensure_ascii=False, indent=2)
    budget = RunBudget(cfg['budget_ledger'], cfg['budget_usd'], enforce=cfg['enforce_cost'])
    reviewer = None
    try:
        reviewer = SdkRecordReviewer(cfg['provider'], cfg['planner_model'], budget=budget,
            max_requests_total=cfg['max_requests_total'], output=model_output,
            credentials_root=ROOT, prompt=PROMPT, output_schema=Proposal,
            max_tokens=cfg['planner_max_tokens'], request_timeout=cfg['request_timeout'],
            max_retries=0, reasoning_effort=cfg['planner_reasoning_effort'],
            max_request_bytes=cfg['max_request_bytes'])
        result = await reviewer.review(packet)
        with (HERE / 'system-proposal.md').open('x') as file:
            file.write('# Uteki 模型侧独立方法提案\n\n')
            file.write('范围：通过现有计量与记录适配器进行的方法设计调用；尚非正式材料精编执行。\n\n')
            file.write(result['answer_markdown'])
            file.write('\n\n待确定：\n' + '\n'.join('- ' + item for item in result['uncertainties']) + '\n')
        manifest['status'] = 'model_response_saved'
    except BaseException as error:
        manifest.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        if reviewer is not None:
            await reviewer.aclose()
        (HERE / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'status': manifest['status'], 'provider': cfg['provider'], 'model': cfg['planner_model'], 'output': str(model_output)}, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
