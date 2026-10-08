"""Pin evaluation questions and caller scope; no passage IDs or expected answers."""
from copy import deepcopy
import json
from pathlib import Path
from uteki.infrastructure.research_data.query_service import QueryDataPort
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
questions=[
 ('msft-business','msft','Microsoft 的 FY2025 10-K 披露了哪些报告分部，各自包括哪些主要业务？请提供足以回答的原始段落和完整的相关列举，保留必要限定。'),
 ('googl-business','googl','Alphabet 的 FY2025 10-K 披露了哪些报告分部，各自包括哪些主要业务？请提供足以回答的原始段落和完整的相关列举，保留必要限定。'),
 ('msft-revenue','msft','请从 Microsoft FY2025 10-K 获取 FY2025 与 FY2024 的公司总收入，保留单位、期间、会计口径与可核对的原文出处。'),
 ('googl-revenue','googl','请从 Alphabet FY2025 10-K 获取 FY2025 与 FY2024 的公司总收入，保留单位、期间、会计口径与可核对的原文出处。'),
 ('msft-cloud','msft','Microsoft FY2025 10-K 中 Microsoft Cloud、Intelligent Cloud 和 Azure and other cloud services 的披露口径有什么不同？请取得回答所需原始定义和收入披露材料，供分析 Agent 使用。'),
 ('googl-buyback','googl','Alphabet FY2025 10-K 对2025年股票回购金额和回购授权剩余额度有何披露？请提供相关表格和必要脚注，明确表中金额包含或不包含哪些成本。'),
]
model=dict(provider='aihubmix',model='claude-sonnet-5-5',reasoning_effort='high',max_tokens=4096,request_timeout=180,max_retries=0,budget_ledger=str(HERE/'costs.sqlite'),budget_usd=None,budget_policy='record_only',max_requests_total=None,allow_unknown_reservations=True)
(HERE/'configs').mkdir(exist_ok=True)
for name,symbol,question in questions:
    dataset=HERE/'datasets'/symbol
    port=QueryDataPort(dataset)
    sources=json.loads((dataset/'sources.json').read_text())
    sid=f'{symbol}-2025-10k'
    company={'msft':'sec-0000789019','googl':'sec-0001652044'}[symbol]
    config={'request':{'question':question,'purpose':'analysis_evidence','dataset':str(dataset), 'scope':dict(snapshot_id=port.snapshot_id,company_ids=[company],source_snapshot_ids=[sid],source_policy_id='local-frozen-v1',knowledge_cutoff='2026-10-09',include_candidates=True), 'limits':dict(max_steps=40,max_packet_bytes=120000,observation_bytes=24000,page_items=8,turn_timeout=240)}, 'planner':deepcopy(model),'worker':deepcopy(model),'reviewer':dict(model,max_tokens=12000),'credential_root':str(ROOT),'workspace':str(ROOT/'workspace'),'reviewer_max_request_bytes':220000,'max_review_packet_bytes':160000,'max_attempts':3}
    port.close()
    with (HERE/'configs'/f'{name}.json').open('x') as f:json.dump(config,f,ensure_ascii=False,indent=2)
with (HERE/'cases.json').open('x') as f:json.dump([{'case_id':n,'symbol':s,'question':q} for n,s,q in questions],f,ensure_ascii=False,indent=2)
