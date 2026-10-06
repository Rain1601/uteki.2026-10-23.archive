# Data / Analysis 真实 Agent 自主性审计

2026-10-04。范围：当前工作区代码、已保存真实运行及离线反例。当前工作区含未提交实现，本文不是某个 Git 提交或部署版本的认证。本轮没有调用模型、修改运行代码、重跑研究或删除历史实验。

用户确定的顺序：先检查真实系统中写死的业务判断与隐式假设，再完善 Data / Analysis；之后以 **AMD、台积电** 做新的研究和跨公司验收。持续监控规则放在后续讨论。

## 1. 结论与判定原则

| 能力 | 已有证据 | 尚不能宣称 |
| --- | --- | --- |
| Data | 当前主入口有真实模型逐轮规划、选择工具、读取原文、委派及接手；一条限定 GOOGL 任务通过内容核验 | 稳定完成同义问题；自主发现全部所需指标；自主决定如何分工；多公司通用效果 |
| Analysis | 当前 handoff 入口真实消费同范围已核验事实，生成有引用的限定解读 | 自主规划研究、执行补数请求、形成完整公司报告、独立研究审阅及修订闭环 |
| 工程后台 | 工作台 Demo 展示任务、运行、产物与评审的组织方式；旧评估页可查冻结产物 | 新 Demo 已连接真实任务执行或真实 Agent 配置 |

**固定结构不等于伪 Agent。** 保留身份、来源、期间、单位、权限、账本、公式、引用校验、失败记录及结构化输出；这些约束让模型行为可审查。需要剔除的是共享入口中的隐式业务范围、预埋答案和冒充通用能力的样本补丁。已确认的核心财务包是基础服务范围，可以保留；研究所需的额外事实应能按需发现、申请、核验。

自主性要逐项证明：会调用模型、会使用工具、会自主规划、会根据证据改计划、会完成研究，分别是不同能力。Trace 记录可观察的计划、动作理由、工具输入输出、修订和最终产物；不以展示模型内部推理作为验收条件。

## 2. 当前入口中优先处理的问题

| 编号 / 优先级 | 实际发现与影响 | 可达范围与处理建议 |
| --- | --- | --- |
| A01 / 高 | 缺少 `filing_selection` 时默认选择最新 10-K 及其后披露；系统替调用方决定材料范围 | `agent prepare`，以及带公司配置的 query 准备阶段可达。要求显式选择政策；缺失拒绝。显式选择“最新”的能力可保留。[采集实现](../../src/uteki/infrastructure/document_sources/company_acquisition.py) 第 228 行；[coordinator](../../src/uteki/agents/data_query/coordinator.py) 第 322 行 |
| A02 / 高 | 期间正则只理解有限语法，可能静默漏掉问题中的年份，然后拒绝模型正确提出的期间 | 当前 Autonomous query 可达。冻结原题解析出 2024、2025，改写题只得到 2025。保留范围隔离，改为明确期间输入或可确认的解析结果，不接受部分解析却当作完整 scope。[period_scope](../../src/uteki/domain/research_data/period_scope.py) 第 58 行；[grounded_query](../../src/uteki/agents/data_query/autonomous.py) 第 617–621 行 |
| A03 / 高 | Analysis 只执行一次无工具的解读；`missing_data_requests` 是输出字符串，尚未被调度执行 | 当前 Data→Review→Analysis 主链可达。需要真实的研究规划、补数返回、更新判断、独立审阅与作者修订；保留现有同范围交接校验。[data_consumer](../../src/uteki/agents/analysis/data_consumer.py) 第 32–65 行；[SDK 调用](../../src/uteki/agents/data_query/record_review_model.py) 第 181 行 |
| A04 / 中 | 系统提示词规定有 Worker 就委派，已有真实验收题还指定资本支出任务交给 Worker | 模型确实执行 delegate，但这只证明按既定分工执行，未证明自主选择分工。另设不指定委派对象/步骤的验收输入。[提示词](../../src/uteki/agents/data_query/autonomous.py) 第 44 行；[冻结题](../../experiments/architecture_baseline/2026-09-30-data-handoff-v1/input-v1.json) |
| A05 / 高 | 自动数值供给是有限 US-GAAP 映射；query Agent 的 `extract` 仅保存逐字引用，未连接独立 Direct Extractor 做按需新指标抽取 | 当前默认 materialize/query 可达。未知概念保留缺口是正确行为，但尚不能宣称通用财务抽取。需要显式能力声明及受审的数值补提入口。[基础指标](../../src/uteki/infrastructure/research_data/company_materialization.py) 第 51–67 行；[extract](../../src/uteki/agents/data_query/autonomous.py) 第 825 行 |

这里的优先级是后续工程建议，不代表本轮已修复。固定核验阶段与数据格式本身无需移除；应开放研究选择，并让选择经过明确的能力与证据边界。

## 3. 仍可执行的旧入口与样本适配器

| 编号 | 发现 | 处理边界 |
| --- | --- | --- |
| H01 | 旧 `DataQueryAgent` / `TaskPlan` 调用默认期间解析，无财年映射时 `FY2031` 会被解释为 2031-01-01～12-31 | 去掉隐式 FY→自然年转换。当前 Autonomous 路径已经要求公司财年映射，不能将旧入口问题混称全部主链都有。[旧 Agent](../../src/uteki/agents/data_query/agent.py) 第 78 行；[TaskPlan](../../src/uteki/domain/research_data/task_plan.py) 第 81 行 |
| H02 | `query_dataset.build_dataset` 无条件加载 Alphabet 试点指标目录，再合并通用目录，使通用构建多出 13 个试点指标 | 按显式 adapter 组装目录。这不会凭空生成数值，但会污染可选研究指标。**当前 coordinator 的 materialize 使用自身目录；本轮检查的真实 handoff 数据集只有 6 个通用指标，没有这 13 项。** [构建器](../../src/uteki/infrastructure/research_data/query_dataset.py) 第 120–123 行；[coordinator 使用的构建器](../../src/uteki/infrastructure/research_data/company_materialization.py) 第 297 行 |
| H03 | Alphabet 电话会 adapter 有固定语句对应的“超过一半”、60/40 比例、40 年措辞及未来投资构成记录等语义处理 | 已要求显式 adapter，并锁定公司和原文哈希；保留为历史受限适配器，不计入通用自主抽取成绩。没有发现其进入本次检查的真实 handoff 数据集。[adapter](../../src/uteki/infrastructure/research_data/adapters/alphabet_query.py) 第 85、129–177 行 |
| H04 | 旧 Analysis 比较 CLI 默认读取历史 manifest 和 Alphabet 固定题；Cloud 试点锁定公司、年份、指标及原文匹配规则 | 迁入具名实验配置，避免共享 API 缺 scope 时静默使用样本；保留历史结果。当前 handoff 不调用这些入口。Cloud 原文读取锁定来源，未发现固定财务答案替代读取。[比较入口](../../src/uteki/agents/analysis/analysis_comparison.py) 第 115 行；[Cloud](../../src/uteki/agents/analysis/cloud_analysis.py) 第 10 行 |
| H05 | 旧 `/analysis` 页面读取固定 Alphabet FY2025 原文，读取点未按当前 run 的原件哈希绑定 | 现有历史样本同源，但不能直接扩成通用查看器。应明确隔离历史页或按 run 读取并校验原件。[查看器](../../apps/review_workbench/pages/cloud_analysis.py) 第 41 行 |

历史年报 narrative 实验允许模型自主选择读取工具，但校验修复由程序固定编排；旧 team Reviewer 首次输入已含作者稿。它们可证明局部工具使用与实验效果，尚不满足“独立初判后对照报告”的目标。

## 4. 应保留的实现及本轮验证边界

- 注入 Planner 必须标明 `scripted_fixture`，模型 SDK 的 `client_factory` 注入路径也标记为 fixture；正式 Analysis 默认拒绝 fixture 交接。此结论限于这些模型执行入口，不覆盖材料获取 `fetch` 等其他注入点。见 [coordinator](../../src/uteki/agents/data_query/coordinator.py) 第 266–275 行和 [handoff](../../src/uteki/agents/data_query/answer_handoff.py) 第 384–386 行。
- Benchmark 输入导出只使用 `case.input`，不合并 rubric/review；但离线 benchmark runner 本身不会执行模型，不能把协议检查称为模型质量评测。见 [runner](../../scripts/run_data_agent_benchmark.py) 第 25–29 行。
- 引用哈希、公司隔离、单位与口径检查、注册公式计算均应保留。未在所检查的当前模型 query→review→analysis 链找到写死 GOOGL 标准财务答案的逻辑；这个结论不是全仓无硬编码的证明。
- 本轮用当前函数复现冻结原题/改写题期间差异，并复现旧入口 FY2031 默认自然年；离线截断采集调用确认缺 policy 默认值，未联网、未写采集产物；检查真实数据集指标目录，区分 H02 的构建器问题与已运行数据集。
- 已保存真实结果：Data 在限定 GOOGL 题上通过 7 条事实 / 6 项要求核验；Worker 达到步骤上限后由主角色接手；Analysis 内容仅部分通过。该链在容量修复后从冻结 query 续跑，非一次无中断完成。见 [真实运行评估](../../experiments/architecture_baseline/2026-09-30-data-handoff-v1/evaluation-v1.json)。
- 同义改写真实运行在四次模型决策后因无进展结束，未进入 Worker/原文搜索；Reviewer 判定需要修订，Analysis 未运行。见 [改写验收记录](../../experiments/architecture_baseline/2026-09-30-retrieval-acceptance-v1/README.md)。本轮核对保存结果和当前代码，未重新调用模型。
- 工作台页面是具名虚构 Demo，不能用其任务/配置展示验收真实 Agent。见 [Demo 边界](agent-workbench-v1/README.md)。

## 5. 下一步真实验收建议

1. **先排除隐式业务假设和样本污染。** 处理 A01/A02、H01/H02；将旧试点入口明确隔离。用独立合成材料验证缺 scope、另一家公司、不同期间及无跨公司引用；不新增预期答案补丁。
2. **验收真实 Data→Analysis 研究闭环。** 固定模型、Skill、代码及来源版本；只给公司、资料范围、问题和交付要求，不给答案、目标段落、关键词或强制委派步骤。模型选择研究计划、工具和补数；程序验证范围/证据，独立 Reviewer 审核，作者修订或明确保留缺口。实际输入中的人工引导必须记录，区分“辅助条件下完成”与“自主完成”。
3. **再进入 AMD、台积电及双公司比较。** 先从实际选定材料确认 form、taxonomy、币种、财年和期间长度；现有实现对 USD、US-GAAP、完整月界及部分 form 有限制，不能预设两家公司都直接适配。材料范围、研究问题/期间在运行前用固定选项确认。新的适配结果与未经调试的验收题分开，开发中看过的失败题不能再次称为未见样本。

真实通过需要同时满足：实际调用模型；关键事实来自本次读取并能回到原文；没有未披露的人工修答案或样本语义覆盖；缺证据时准确留缺口；更换措辞、公司与期间仍保持范围和事实正确；Analysis 能实际完成必要补数与审阅修订。单题成功和测试数量都不足以证明稳定质量，稳定性评测的题量与重复次数仍待运行前固定。

后续“把偶然变成固定”的具体落点建议是：模型发现值得长期追踪的因素，再沉淀为有来源、采集方法、频率、检查标准和变化触发条件的监控契约。可固定的是可重复检查的机制；投资判断继续根据新证据更新。具体指标和阈值本轮不预设。
