# Data 内容核验与 Analysis 交接：2026-09-30

状态：**真实 Data → 内容核验 → 限定 Analysis 交接已跑通；Analysis 内容部分通过，仍待修订。** 本目录不是完整投研报告或实际投资记录。用户直接回复“开始”后执行，当前没有待确认的运行审批。

需要人工查看内容时，先读[原文、解析结果与本题交付样本](../../../docs/design/data-agent-acceptance/README.zh-CN.md)。本次复用预先确定性生成的索引和候选财务库，没有重新全面抽取 10-K；该库中本份 10-K 的 111 条候选仅覆盖五类指标，不能当作完整核心财务包。本轮 7 条受审事实是 4 条既有数值＋3 条新叙述 claim。

## 本次真实结果

| 环节 | 实测结果 | 验收边界 |
| --- | --- | --- |
| Data Planner + Worker | 25 + 10 次真实调用；最终 evidence_ready，四项金额、两类用途和实际/预期区分正确 | Worker 达到步骤上限，主角色重新查询并完整读表后接手完成；不能说 Worker 自主核验通过 |
| 独立 Data 内容核验 | 1 次真实调用，7 条事实、6 项要求全部通过；原文引用校验通过 | 完整索引文本和表结构进入模型，2 张未读图片明确保留；图表位于股票表现章节，文本足够回答本题 |
| 限定 Analysis | 1 次真实调用，引用门槛通过，生成 7 条解释及数据补充请求 | 核心事实正确，但混淆“源数据未全局采纳”和“本任务已经核验”；重复要求核对已审事实，并提出部分超出本题的数据请求，内容仅部分通过 |

[机器可核查汇总](evaluation-v1.json)记录各角色调用、token、成本估算、运行 manifest 哈希及验收缺口。合计 **37 次真实调用，价格快照估算 1.91691576 美元**，不是供应商账单。

首次 [e2e-01](e2e-01/result.json) 在 Data 完成后，内容核验尚未发出请求便被固定的 400,000 字节请求体上限阻止。输入包约 1,577,403 字节；错误类型当时为 BudgetExceeded，实际原因是容量，不是金额超限。

修复为按角色显式配置请求体字节上限，默认仍为 400,000；本次 Reviewer 设为 2,500,000，Analysis 保持 400,000，超容量使用 RequestEnvelopeTooLarge。未删减原文，金额及共享请求政策保持原值。[DeepSeek 官方规格](https://api-docs.deepseek.com/quick_start/pricing/)于 2026-09-30 核对为所选模型提供 1M token 上下文；字节上限与 token 上下文分别约束，不能互相等同。

[e2e-02](e2e-02/result.json) 用外部固定的 query manifest 哈希续跑审阅及 Analysis，复用首轮取证，未再次调用 Planner/Worker。两次运行都保留，不能称为首轮无中断成功。最终仍是 candidate_pending_analysis_review / not_published；正式研究 Reviewer 尚未执行。

本次独立离线内容核对先从原文固定金额、用途类别及时间限定，再读取模型结果进行对照；没有把标准答案放进模型输入。该核对发现 Analysis 语义缺口，未擅自改写其冻结产物或正式核验状态。

## 本次增量

1. 读取已封存 query 的当前 active source_answer 及数值记录，绑定原问题、公司/期间/来源范围、数据集、答案与文件哈希。旧答案不替代当前答案；数值记录通过同一 scoped query 重取后逐字段核对。
2. 独立内容核验接收所选来源的全部索引文本、原表结构及显式非文本缺口。核验逐条事实、每个要求和原问题覆盖；不能用有效引文或作者自报完整替代内容判断。图片内容未读取；模型须明确判断文本是否足以回答本题，缺关键内容则阻断。
3. Analysis 调用前再次核验审阅 manifest 的外部固定哈希、上游来源、当前答案和内容结论。partial、未核验、漏答、被篡改或范围不符时不调用 Analysis。通过后只生成带事实引用的内部限定分析候选，仍待研究内容审阅，不发布完整公司报告。
4. 沿用共享费用账本，固定每个角色的模型和推理档位，保存实际模型输入、可见响应、成本与失败状态。取消发生在模型调用或关闭阶段时，先封存取消状态再抛出；不保存隐藏推理。

此处 Data 内容核验与正式研究 Reviewer 是两个环节。后者“先不看作者稿形成独立初判”及双语完整报告发布仍未在本次实现。当前试点要求完整交付才进入 Analysis；这不改变正式报告可表达正常未知的既定原则。核验发现遗漏后交付具体修订意见并停止，不自动无限重跑；作者再次研究与复审的有界调度仍待接入。

## 验证证据

- **66 项交接与审阅检查及 4 项入口配置离线检查通过**：新交接/拒绝路径、跨公司与期间的数值重取核对、审阅 SDK、已有 source_answer、记录审阅及语义审阅运行边界。合成材料和脚本角色证明接口与门槛，不证明真实模型能识别遗漏。
- [offline-preflight.json](offline-preflight.json)：用旧 run-06 检查真实材料的输入组装，取得 1 个来源的 1,338 个索引块、4 条数值记录，明确保留 2 个图片内容缺口。旧 run 仍是 limited，未重新审阅，不进入 Analysis。
- 另有 4 项入口检查覆盖四个角色的缺失/非法模型参数、未知模型及共享预算不一致，确认在任何模型调用、账本或运行目录写入前拒绝。
- 本地 `--check-only` 通过，只核对配置、数据及 scope，不调用模型、不创建 E2E 输出。
- 此前自动审批两次拒绝执行；用户随后直接回复“开始”，已取得本次执行批准。原先 0 次调用是执行前状态，现以本页真实结果为准。
- 容量修复的 37 项定向检查、入口与冻结 query 续跑的 8 项检查通过（与此前检查存在覆盖重叠，不累加为独立案例数）。验证完整大输入发送、超限前拦截、预算规则保持、篡改/错题拒绝及失败审阅不进入 Analysis。

```bash
PYTHONPATH=src:. .venv/bin/python -m unittest tests.unit.test_answer_handoff tests.unit.test_answer_handoff_records tests.unit.test_record_review_model tests.unit.test_autonomous_source_answer tests.unit.test_record_review_run tests.unit.test_semantic_review_run
PYTHONPATH=src:. .venv/bin/python -m unittest tests.unit.test_data_handoff_driver
PYTHONPATH=src:. .venv/bin/python -m unittest tests.unit.test_call_costs tests.unit.test_record_review_model tests.unit.test_narrative_reliability
```

## 已执行的真实任务与复现配置

[handoff-config-v1.json](handoff-config-v1.json) 显式沿用原 input-v1 的公开 Alphabet FY2025 10-K、冻结 dataset/scope 和研究问题；不使用 run-06 的人工评审补充题，也不输入标准答案。`input-v1.json` 是原取证配置的本次副本，仅换共享 ledger 路径。

| 角色 | 固定配置 |
| --- | --- |
| Data Planner | deepseek-v4-pro / high |
| Data Worker | deepseek-flash / low |
| Data 内容核验 | deepseek-v4-pro / high |
| 限定 Analysis | deepseek-v4-pro / high |

金额与共享请求政策保持 record_only、无金额上限和无共享请求总上限。执行有界：Data 合计最多 36 次决策、Worker 最多 10 步、无进展限制、每次调用与 Worker 超时继续生效；之后至多一次内容核验和一次 Analysis，各角色保留配置中的显式传输重试。没有自动模型切换或无限作者修订循环。

首轮命令如下，输出目录现已存在，不可覆盖：

```bash
PYTHONPATH=src .venv/bin/python scripts/run_data_handoff.py --config experiments/architecture_baseline/2026-09-30-data-handoff-v1/handoff-config-v1.json --output experiments/architecture_baseline/2026-09-30-data-handoff-v1/e2e-01
```

续跑使用 [handoff-config-v2.json](handoff-config-v2.json)，只新增 reviewer/analyst 请求体容量配置，所有模型、问题、资料、金额和步骤政策均沿用 v1：

```bash
PYTHONPATH=src .venv/bin/python scripts/run_data_handoff.py --config experiments/architecture_baseline/2026-09-30-data-handoff-v1/handoff-config-v2.json --output experiments/architecture_baseline/2026-09-30-data-handoff-v1/e2e-02 --query-run experiments/architecture_baseline/2026-09-30-data-handoff-v1/e2e-01/data-query/query --query-manifest-sha256 a96fa147866a60f59f400750380e05c4702a06cb5e1a313c7d68571cc829a294
```

运行只写入新的实验目录和目录外的共享成本账本，保留历史数据及运行。结果可能为 query 阻塞、内容核验退回或限定分析候选；命令成功也不表示完整公司报告、Manager 投资能力、稳定复现或跨公司研究质量通过。

## 后续验收

1. 先澄清 Analysis 交接中的任务核验状态与全局采纳状态，要求补充数据请求说明具体未解问题及其影响。现有 handoff 的 review 引用与 use=reviewed_for_this_task_only 不足以阻止实际模型误解；不能只靠 candidate 标签重开已验事实。
2. 改善 Worker 分页参数反馈、已读正文被回放容量挤出后的明确指针，以及重复读取后的回放顺序。已观察到主角色第一次读完表格后，再次把“本轮未回放”误当“从未交付”；不先靠放大步数掩盖问题。
3. 再接正式研究 Reviewer 的阶段隔离、作者修订及双语完整报告。当前仅一个限定问题通过数据内容核验，未证明稳定复现或跨公司研究质量；注册计算公式结果交接仍不支持。
