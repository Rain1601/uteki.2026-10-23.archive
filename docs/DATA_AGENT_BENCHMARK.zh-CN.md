# Data Agent benchmark v0.1

这套基准将 E1–E8 离线工程反例与三家公司 13 道真实模型题分开报告。它用于保留可复核的输入、运行证据与验收记录，不将单元测试通过数量转换成模型分数。

## 文件与边界

- `benchmarks/data_agent/v0.1/questions.json`：Alphabet、Microsoft、Amazon 各四题（数值、完整章节、混合、缺资料），加一题跨公司比较。每题固定自然语言问题、公司/市场、截止日、官方来源配置、含两端的 90 日更新窗口和拟议运行上限。具体来源与章节 ID 由被测 Agent 发现。
- `rubric.json`：独立评测规则。核对引用是否支持结论、原始数值与计算、范围/截止日、遗漏、全文读取范围、调用与成本。
- `review_template.json`：人工复核模板，初始均未运行。原文核对笔记、期望数值与人工判定只放评测侧，不放模型输入。
- `offline_suites.json`：E1–E8 到现有离线反例的显式方法映射。E1–E8 的工程验收条款已有完整映射，实际运行全部通过才能记 pass。E5/E8 已补上协调器与计费适配器的失败、取消、重跑反例。方法存在或映射完整本身不代表已执行通过。
- `scripts/run_data_agent_benchmark.py`：运行离线回归和汇总独立人工复核。没有模型或网络执行入口。

唯一模型输入导出函数是 `model_input(case)`，仅返回 `case.input`。不要将整个 benchmark 配置、rubric 或 review 文件作为提示词发送。问题中的 FY2025 必须从各公司来源解析真实财年，比较时保留各自期间，不能默认等于自然年。FY2027 的缺资料题要求识别截至日的实际披露可得性，不能以未来全年实际数、预测或另一年份替代。

三份来源配置的哈希固定在评测侧 `source_configuration_hashes`，runner 会拒绝配置漂移；更换官方来源或截止日时先建立并审核新版本。真实执行所需 SEC User-Agent 由调用方显式传入，不以修改已固定配置的方式补填。

## 运行

在仓库根目录执行：

```bash
.venv/bin/python scripts/run_data_agent_benchmark.py --output /tmp/data-agent-benchmark-run-001
.venv/bin/python scripts/run_data_agent_benchmark.py --suite E3 --suite E4 --case msft-mixed --output /tmp/data-agent-benchmark-run-002
.venv/bin/python scripts/run_data_agent_benchmark.py --skip-offline --reviews /tmp/review.json --output /tmp/data-agent-benchmark-review-001
.venv/bin/python -m unittest tests.unit.test_data_agent_benchmark
```

`--suite` 与 `--case` 可重复，分别筛选工程套件与真实题，不把离线合成测试冒充选中公司题的运行。默认全部。`--timeout` 指定每个离线命令的时间限制。输出目录必须尚不存在；历史结果不覆盖。

输出 `report.json` 与 `report.md`。机器结果保留配置哈希、每项实际命令、cwd、退出码、耗时与错误摘要；缺模块和显式跳过有原因。返回码为 1 表示所选工程检查或真实题底层判定有 fail；partial/not_run 不视为已通过，但不阻断创建报告。各题未知成本、调用或覆盖数保持 null，不能填零。runner 自己的模型调用恒为 0，与导入外部运行的调用消耗分开。

## 真实题的复核接口

本版不执行 13 道模型题。使用前必须确定 provider/model、累计请求上限、费用策略和失败后的继续规则；当前配置 `execution_authorized=false`，模型预算和 `cost_policy` 均未指定，任何人工填写的完整复核也不能使真实题通过。每题拟议上限不构成调用授权；历史 DeepSeek 46/48 不可复用或通过新目录重置。题目/上限或验收口径变化时新建版本，保留旧输入。

费用策略由已授权的版本显式声明：`record_only` 只记录费用，不要求 monetary cap；实际费用未知时保留 null 与 `cost_completeness=unknown`，不影响已满足其他条件的任务正确性。`block_at_limit` 则要求 `aggregate_cost_limit`，未知实际费用无法核实上限时保留 partial。两种策略均要求明确累计请求上限，重试和超时计入。当前配置没有启用任何执行授权。

复核者复制 `review_template.json`，逐题记录实际执行、帮助内容与各维度判定。状态如下：

| 状态 | 含义 |
|---|---|
| not_run | 没有提交已执行运行；离线缺组件也标此状态 |
| pass | 本层必需检查均通过；真实题还需完整产物、独立复核和请求/成本记录 |
| partial | 缺产物、未复核、部分覆盖或必需记录不完整 |
| fail | 必需项失败、产物损坏/错题、工程命令失败或超过请求上限 |
| assisted | 运行过程中人工提供了来源/章节位置、答案或修复中间产物；另保留 underlying_verdict，不计自主通过 |

真实题复核需要 `reviewer`、`reviewed_at`，每个必需 `checks` 项的 pass/partial/fail/not_reviewed、证据引用与笔记，及 `metrics`。单独填写 `origin=model` 或 `status=pass` 无效。

数值、章节、混合及比较题的 `result.status=partial` 封顶 partial，人工将 checks 全填 pass 也不能升级。缺资料题只有正常完成（`stop_reason=host_reference_checks_passed`）、所有缺口均为 `not_yet_occurred`，并通过独立 `gap_accuracy` 审核时，才允许把 partial 的取数结果判为成功识别预期缺口；获取失败、未读或其他混合缺口仍 partial。所有题至少须有一次实际成功模型请求，全部失败不能通过。

`run_dir` 指向独立运行目录；`manifest_sha256` 固定 `manifest.json`；manifest 的 `files` 必须包含 `request.json`、`config.json`、`result.json` 和模型调用证据。程序核对所有文件哈希、路径边界、原始自然语言问题与 `config.plan_origin=model`，同时要求 `model_call_evidence` 指向 manifest 已固定文件。T3 的通用运行产物尚不能直接满足下述评测绑定：wrapper 与 query 子目录各有职责，调用计费快照也不是评测累计台账。T4 须生成新的独立导出包；目前缺少绑定仍为 not_ready/partial，不能改写历史 manifest 或仅重命名字段使其通过。

额外必需的三份文件同样必须在 manifest 中固定：

- `benchmark-input.json`：必须与该题 `case.input` 完全一致，包括公司、截止日、来源窗口和限制。
- `benchmark-sources.json`：`configuration_artifacts` 将每个题目来源配置路径映射到运行内冻结的配置文件；哈希必须等于本基准固定值。`companies` 为含 symbol/market/company_id 的解析结果，集合须与题目及 `request.scope.company_ids` 匹配；`execution_scope` 必须等于运行请求 scope，含 snapshot_id/source_policy_id/include_candidates 等完整字段并通过 ExecutionScope 校验。`dataset_manifest` 指向运行内固定的数据集 manifest；其文件必须同时绑定到运行 manifest，所选 source ID 须唯一解析到同公司、截止日前的 sources.json 条目，且 raw_file/source_sha256/raw_file_sha256 与真实原件哈希一致。缺绑定为 not_ready，错误绑定为 fail；披露语义仍需独立复核。
- `model-usage.json`：包含与题目一致的 `limits`，实际 `steps`、`elapsed_seconds`、`cost_currency`、`attempts` 和 `cumulative_attempts` 数组。每次请求记录唯一 request_id、case_id、指向已固定调用证据的 evidence_path、provider/model、status（succeeded/failed/timed_out）、retry 布尔值、input_tokens/output_tokens、cost。`authorization` 必须含与基准相同的 benchmark_id、questions_sha256 和 model_budget；冻结 `config.json` 及所有调用的 provider/model 均须与授权一致。程序按唯一 request_id 去重、拒绝冲突负载、核实本题请求属于累计台账，再跨所有导入复核合并预算；`--case` 筛选展示不重置累计预算。请求、每次输出 token、总 token、步骤、耗时及阻断策略下费用越限均 fail；record_only 下未知费用独立记录。每题可选的 authorized_cost_limit 仅在阻断策略下生效，不能替代基准的累计上限。

复核者必须实际检查调用证据、重试/超时记录后才能填写 `model_calls_human_verified=true`。程序验证的是文件完整性，不能凭文件声明证明远程模型真实执行，报告明确标记 `human_reviewed_artifacts_verified`。人工针对实际执行提供帮助与事后独立评分是两回事，后者不自动标 assisted。

请求计数要求 `attempted = succeeded + failed + timed_out`，其中 failed 不含 timed_out，retry 是 attempted 的子集。费用未知时保留 null，可填写 `unknown_cost_reason`；不能冒充已知零费用。消耗指标取已固定台账，复核表手填消耗不能覆盖；引用核对数、数值正确数、正文必需/已读/未读块及遗漏项是独立人工指标，不从 `semantic_completeness=not_evaluated` 或 `evidence_ready` 自动推导。台账声明不是实际授权证明，复核者还须核对已有本轮授权、完整累计记录与调用真实性。

## 当前验收与后续

2026-09-24 T3 离线基准：[report.md](/tmp/uteki-data-agent-benchmark-v01-t3-20260924-01/report.md)、[机器结果](/tmp/uteki-data-agent-benchmark-v01-t3-20260924-01/report.json)。**E1–E8 全部 pass，57 条实际离线命令全部退出成功；13 道真实模型题仍全部 not_run，runner 模型调用 0。** 历史 T2 [稳定报告](/tmp/uteki-data-agent-benchmark-v01-stable/report.md) 保留其当时的 E5/E8 partial，不覆盖。报告为本机产物，换机器需新建运行；不能把链接或测试数量当作模型结果。

E5 新映射覆盖身份 403、获取与模型的有界重试/超时、无字面匹配不能解释为未披露、不支持解析及实际计数。E8 覆盖新增资料部分物化保持原 scope、准备/获取/模型取消后保留产物并关闭资源、重复准备不覆盖历史、累计额度耗尽与同资料重跑不重置账本。映射只声明工程行为，未验证真实模型选择、需求拆解和语义完整性。

获取器已支持显式 `annual_report_period`，按 SEC `reportDate` 精确选择旧年报。MSFT FY2025 已实际取得，实际原件和缺口见[本轮报告](../experiments/data_agent_query/company-coordinator-v1/README.md)。基线最新年报仍可能是 FY2026，不能拿较新 Business 替代 FY2025。真实准备与受控脚本仍不计入这里的 13 题。

本次 E6/E7 映射审查对应方案的验收条款如下；完整方法路径保存在配置中，历史首跑报告不改写：

| 套件 | 条款与实际断言 |
|---|---|
| E6 | 大目录与 schema 样例翻至末页不丢项；受控 planner 分页取得末页 `TAIL_REQUIRED`，摘录绑定原 scope、source、block 且 quote 属于原文；超大正文按字符回读；分别断言 `execution_limited=true/preview_truncated=false` 与相反组合，未读正文独立保留 |
| E7 | 旧快照 scope 和 v1/v2 证据回读保持稳定；错误 artifact/hash/scope/pointer/offset 和跨来源注册被拒绝；仅落盘或最后一轮未投递的正文不计已读，也不能用于摘录；重复正文页不增加 read_node 覆盖，重复目录及已读文本重叠前缀触发停滞；子字段与父页范围共享去重，query 内嵌 context 的投递也登记为已读 |

这些断言补齐了先前映射的缺项，因此 `acceptance_mapping_complete=true`；benchmark runner 会依据后续实际执行结果判定 pass/fail，而非沿用主线程口头测试结果。

T4 的下一步是补齐题目/来源/模型绑定导出和可追溯的累计逐请求台账：保留初始与最终 scope、所有授权 case 的调用 ID/证据、重试和超时；不能用累计汇总数字补造请求。当前 `estimated_usd` 是价目表估算，`actual_billed_usd` 未知，报告不得称为实际账单。AiHubMix 的 SDK 归一化 usage 未保留与 DeepSeek 相同的原始 usage 保证，使用前仍需补充验证。

完成这些离线前置后，在明确的新授权预算内先跑 MSFT 单题模型冒烟，再跑 13 题。之后独立核对原文、计算与遗漏，逐题报告 pass/partial/fail/assisted、缺口和消耗，不用平均分掩盖未运行项。
