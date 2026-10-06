# Data Agent 的 Prompt、Skill 与正式执行入口

2026-10-05 源码核对。用户要求：每次优化应作为可持续复用、可控、有明确版本的系统能力留下，不能依赖 Codex 在对话中临时补齐。

## 1. 三种职责

- **System Prompt**：该次模型调用的角色、任务边界、输出与证据规则。真正生效的是发给模型的文本和 schema，不是目录里存在一份文件。
- **Skill**：可被执行过程加载的专业方法和操作说明。它帮助模型选择步骤和工具，但不会仅因命名为 `SKILL.md` 就自动参与运行。
- **程序与工具**：执行下载、身份/哈希检查、解析、分批、引用定位、数据校验和数据库读写。稳定规则不必每次由模型重新推导。

固定方法和版本不等于固定答案。公司、年份、原文、模型产物与未解决项仍来自当前明确输入；同一模型也不保证每次输出完全相同。

### 已确认：谁维护、谁执行、怎样选择

用户于 2026-10-04 确认：**Codex 编写、评估和迭代 Uteki 的 Skill；Uteki 自己选择、加载、执行并反馈问题。** Codex 使用 Skill Creator 辅助编写，不表示 Uteki 依赖 Codex 的插件，也不表示 Uteki 已有自行创建 Skill 的 Agent。仓库中的应用 Skill 是交给 Uteki 运行时读取的专业方法。

首版选择规则为：**任务类型绑定默认方法，只允许选择该任务声明的方法，缺少能力则申请补充。** 默认配置可以包含多个允许的方法，但不得从全部 Skill 中任意选取，也不得遇到未知任务后改用最相近的提示词。模型配置仍按既有规则由工程固定，选择 Skill 不授予自主换模型权限。

具体例子：输入任务类型 `annual_financial_extraction`、明确公司/原件/截止/期间/指标范围 → [任务配置](../../config/data_tasks/annual-financial-v1.json)选择 `annual-financial-v2` → [方法配置](../../config/data_methods/annual-financial-v2.json)绑定 Skill、Prompt 与分批规则 → 宿主核对适用来源和版本 → 将真实文本交给提取模型。另一个公司的 10-K 仍使用这个方法；10-Q、财报精编或其他未支持任务不能静默复用它。配置声明支持 20-F 不等于台积电已通过效果验收。

运行必须保存任务类型、默认或显式选择的原因、选中方法、实际加载全文及 hash、最终 System Prompt。选择记录证明使用了哪套方法；结果质量仍由独立原文核验决定。修改方法产生新版本，历史任务继续引用原版本。

## 2. 当前实际参与情况

| 阶段 | 实际执行 | Prompt / Skill 参与 | 已成为正式能力的范围 |
|---|---|---|---|
| 获取原件 | 公司/范围配置 → SEC 发现、下载、核对与保存 | 独立获取 CLI 无模型；自主查询循环中的 acquire Skill 提供方法说明 | `agent acquire`、`prepare`、`refresh` 已有正式入口；AMD/TSMC 登记范围实跑通过 |
| 解析与索引 | 原件 → 段落、表格、目录、检索结构 | 解析器确定性执行；自主循环可读取 materialize Skill；独立 prepare 不自动调用模型 | 解析器与物化组件已进入系统；文档可检索不等于财务信息已完整提取 |
| 按问题查询取证 | 自主 Planner / Worker 选择阅读、查询与取证工具 | 正式自主循环有 System Prompt，真实加载 acquire/materialize/query 三个 Skill；内容与 hash 写入 `skills.json` | 查询循环已集成；它的 `extract` 动作不等于本轮专业年报直接抽取全过程 |
| 年报证据选择 | 全文块目录 → 来源绑定的选材计划 | 本轮 `run_extraction_v3.py` 使用专门 Planner System Prompt | 短引用协议在实验真实通过；尚未变成 prepare 的默认后续步骤 |
| 年报信息提取 | 已选原文 + 目录 + 任务 → 模型候选 | `agent extract-batch` 实际合成并加载应用 Skill 与专业 Prompt v2；主 `agent query` 新增 `financial_extract` 动作，按登记目录选择批次后调用同一入口 | 任务登记、主循环调用和候选交接已接入。全年报选材、跨运行续接、批次自动补齐与补提编排仍待完成；真实质量另见运行记录 |
| 规范化和 SQL 入库 | 候选 → 来源/格式/目录校验 → 新 DuckDB 候选快照 → 回读 | 程序负责参数化写入；不是让模型生成任意写库 SQL。查询链路中的 SQL 查询是另一项能力 | 通用直接提取已有写库与冻结机制；正式共享采纳、跨运行重述关系尚未完成 |
| 内容 Review 与修订 | 候选和原文 → 核验发现 → 新版本 | 现有 query 的模型核验与本轮 Codex 独立源复核分开。本轮原文对照、复核结论作为外部冻结产物登记 | 年报的自动内容 Review → 补读/重新提取 → 复审闭环未接成默认系统流程 |
| 财报精编 | 结构化忠实浓缩、正文/图表/引用 | 应有独立任务方法、输出 schema 与核验规则 | 当前只有已确认产物边界；旧 Analysis narrative 不能算新 Data 精编实现 |

源码入口：[`agent_cli.py`](../../src/uteki/infrastructure/research_data/agent_cli.py)、[`autonomous.py`](../../src/uteki/agents/data_query/autonomous.py)、[`autonomous_model.py`](../../src/uteki/agents/data_query/autonomous_model.py)、[`direct_extraction.py`](../../src/uteki/infrastructure/research_data/direct_extraction.py)、[`direct_normalization.py`](../../src/uteki/infrastructure/research_data/direct_normalization.py)。

现有方法：[acquire](../../skills/data-agent/acquire/SKILL.md)、[materialize](../../skills/data-agent/materialize/SKILL.md)、[query](../../skills/data-agent/query/SKILL.md)、新增的应用 [extract Skill](../../skills/data-agent/extract/SKILL.md)。专业年报 [Prompt v1](../../skills/data-agent/extract/references/annual-financial-extraction-v1.txt) 保留；[Prompt v2](../../skills/data-agent/extract/references/annual-financial-extraction-v2.txt)已从实验版本复制为方法配置绑定的资产。实际加载代码是 [`extraction_batches.py`](../../src/uteki/infrastructure/research_data/extraction_batches.py)，不依赖 Codex 自动发现 Skill 文件。

## 3. 已保存不等于已默认启用

本轮保留了原件/输入、候选、规范化结果、数据库、模型和 Prompt 配置、实际请求结果、用量、程序诊断与独立审阅，并以 manifest/hash 绑定。历史失败和新修订分别保存，因此本次优化与结果可以继续检查和复现；没有依赖聊天记忆来保存这些内容。

专业年报全文选材仍由实验运行器组织；显式选材后的单批执行已迁入正式模块。主 `agent query` 现可接收显式登记的 `financial_tasks`：宿主先校验公司、来源、截止日、数据版本和方法，冻结全部允许方法的真实文件；主模型根据表格原文摘录自主选批，调用 `financial_extract`。模型不能通过动作改写文件路径、模型或公司范围。

每个登记任务有明确的新批次数额，失败尝试也计入；成功重复请求在本次运行内复用并校验既有产物。上一运行的成功批次尚不自动接续。返回 `candidate_ready` 只说明候选已生成，不代表内容核验或正式采纳；新 DB 独立保存，查询中的原数据集和 scope 不被覆盖。主规划器和提取器分别固定模型、共用账本；提取器目前仅支持 `max_retries=0`，不支持的配置明确拒绝。

用户只输入公司、期间时，正式 prepare 仍不会自动串起整份年报的专业选材与提取。上述接入覆盖“已有冻结选材任务 → 主模型选表 → 方法执行 → 候选交接”，不能扩大为全年报自动处理已完成。具体参数见 [CLI 文档](../DATA_AGENT_CLI.zh-CN.md)。

本轮 `agent extract-batch` 的 16 项定向及受影响工程检查通过，包含两个独立合成公司、不同期间、默认与允许方法选择、真正发送的 Skill/Prompt、未知方法/跨任务拒绝、来源换版与失败留档。独立源码复核补查了方法身份/hash/版本与数据集二次读取绑定。这些是工程证据；真实模型结果单独记入[年报运行记录](../../experiments/architecture_baseline/2026-10-04-amd-tsmc-annual-v1/README.md)。当前一次任务使用一个方法，“申请补充”暂以明确失败/缺口交接，尚无自动新增 Skill 或多 Skill 组合执行。

正式入口真实验收已完成一次：`amd-fy2023-formal-batch-00-v1` 的任务 profile 默认选择 `annual-financial-v2`，使用 DeepSeek Flash/low；实际模型指令含 Skill 全文及专业 Prompt。输出 9 条草稿和 9 条 DB 候选，三项指标各三期匹配原文，程序未解决项为 0。独立审阅保留缺失附注与口径限定，10 个批次及 24 个未分配正文块仍待处理。这个结果证明了单批任务的选择、加载、执行和结果追踪，尚未证明全文完整或主 Agent 自主编排。查看[实际加载快照](../../experiments/architecture_baseline/2026-10-04-amd-tsmc-annual-v1/amd-fy2023-formal-batch-00-v1/method-snapshot.json)与[真实结果](http://127.0.0.1:8765/evaluation?dataset=amd-annual-v2&tab=records&source=source-291485b98a75d8cfabe47571&run=amd-fy2023-formal-batch-00-v1)。

## 4. 后续优化的完成标准

2026-10-05 主循环真实验收：`agent query` 的 Pro 模型根据登记目录自主选择资产负债表，调用默认方法的 Flash 提取器。6 次规划请求中含两次字段拒绝，1 次提取得到 10 条草稿和 3 条 DB 候选，保留 12 项程序诊断。独立复核确认 9 条数值受原文支持、1 条正确保留未知；仍有相邻表格数值拼接及债务/股本口径映射缺口。模型选择与执行已验证到这个范围，不能称为完整财务包通过。详见[本轮输入、Trace、结果与审核](../../experiments/architecture_baseline/2026-10-04-amd-tsmc-annual-v1/README.md)。

该轮还发现旧实现归档的同名路径冲突；历史文件保持不变，声明的代码 hash 与实际副本不一致已列为追溯限制。后续归档按完整包路径保存并以同一次读取计算 hash，离线检查已通过。

一项改进只有同时满足以下条件，才能标为“已纳入默认系统能力”：

1. 输入、输出、支持范围和失败行为明确；公司/期间/来源由显式输入绑定。
2. 正式执行入口实际加载指定版本的 Prompt/Skill/模型/策略，而不是依赖 Codex 手工构造临时流程；同一次运行保存实际生效配置。
3. 新旧版本可分别运行，历史输入和产物不覆盖；版本变更的原因、适用范围和检查结果可追溯。
4. 回归检查覆盖新公司/来源/期间及缺输入边界；真实模型验收与离线工程检查分别记录。独立答案不得反馈为提取输入。
5. 可从正式入口完整产生结果、缺口与审阅交接，前台读取保存产物。只读查看不触发模型，也不自动采纳候选。

近期接入顺序：先核验主 Agent 选择新表格并执行的方法与内容；再补齐全年报选材、批次续接/合并/去重、覆盖检查和内容 Review 修订。保留未通过项，不把单张报表成功推广为整份年报能力。财报精编另建对应方法，不复用投资判断 Prompt 冒充材料浓缩。

这是后续接入与验收的工程标准；本文件不宣称尚未接入的编排已经完成。
