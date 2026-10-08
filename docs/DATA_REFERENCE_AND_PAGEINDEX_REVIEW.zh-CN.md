# 精确证据目标与 PageIndex：现状和技术判断

> 进度更新：本文下面保留本轮实施前的审查快照。后续已重建两份冻结数据、修复列表/脚注/财年目录与指标说明，并贯通字符/单元格原件预览。系统自主取材与内容复核的六题矩阵及目录分页针对性复跑已独立验收通过；最新实际状态见 [完成计划](../experiments/agent_design/2026-10-09-data-agent-completion-v1/PLAN.zh-CN.md) 和 [真实 HTTP 定位检查](../experiments/agent_design/2026-10-09-data-agent-completion-v1/validation/source-preview-http.json)。后续确有模型调用；下文“未调用”仅指当时只读审查。未运行 PageIndex，仍不能声称与其做过实测对照。

## 实施前审查快照

2026-10-09。基于当前 Uteki 代码、已有真实材料、2026-10-07 PageIndex 调研及 Opus 审阅，并重新核对 PageIndex 官方文档。本轮没有运行 PageIndex，没有新增模型调用，没有实施新的检索路径。

## 用户目标

按问题获取足以支持回答的最小充分材料。每项有来源的事实或判断都能追溯到冻结原件版本中的具体段落、引文或表格位置，点击可查看、核对并高亮。多段共同支持一个结论时保留多处证据，不能强塞进一个块。推断明确列证据及推断性质；有引用不等于原文支持全部主张，也不保证现实事实已经独立验证。

结构化接口数据与原始文档数据可以并存。接口值需保留供应商、时间、口径和响应快照；接口未提供报告定位时，不能伪造对应财报段落。PDF、HTML、新闻和博客可以使用不同获取/检索器，但消费端看到一致的证据身份、精度与质量状态。

## 三层分工

```text
准备：冻结原文 → 忠实块/表格 + 稳定版本内定位 + 可选目录/摘要
检索：问题 → 范围筛选 → 关键词 / 目录树 / 其它召回 → 回读原文
证据：检查支持关系和必要上下文 → 绑定精确位置 → 点击定位、高亮
```

目录和摘要用于找材料，不可代替原文作为关键事实证据。可检索的目录不是精确证据成立的前提；即使只用关键词搜索，也仍需冻结原件、位置映射和引用核验。

## PageIndex 能解决哪些部分

| 需求 | 官方能力与边界 | 当前判断 |
|---|---|---|
| 复杂文档构建目录树 | 本地 Flash 从 PDF 结构建立树，再用模型做摘要/细化；Agent 读树并回读内容 | 与本项目导航目标直接相关，可作为候选组件 |
| 原文检索与引用 | 本地有页内容读取和页级引用；托管版另有块级引用 | 本地开箱精度不满足段落高亮全部要求；可以另加细定位，尚未接入验证 |
| 引用高亮 | 托管版可解析引用到 block/bbox，获取页面图，再用 `highlight_region` 标出块区域 | 官方给出了实现路径，不能说 PageIndex 只会生成目录；块区域也不必然等于句子或财务单元格 |
| 当前 SEC HTML | 官方本地 submit 接受 PDF；托管 submit 文档列 PDF/PPTX/Word | 当前 HTML 不能假设直接无损导入；不为比较而默认转 PDF 并抹掉 DOM/XBRL 优势 |
| 引用真实支持结论、没有漏证据 | 有定位/引用接口，不等于对所有任务的内容充分性保证 | 需要本项目独立证据评测 |

官方来源：[仓库与建树/检索](https://github.com/VectifyAI/PageIndex) · [输入和块读取](https://docs.pageindex.ai/sdk/documents) · [引用与高亮](https://docs.pageindex.ai/sdk/chat#highlight-the-cited-region) · [自有 Agent 集成](https://docs.pageindex.ai/sdk/agents)。PageIndex Cloud 指 PageIndex 托管服务，不是 Claude 模型。

官方 OSS benchmark 是 34 份 PDF 的 62 个正文事实问题，排除图表、表格、计算，以及本地 Flash 无法索引的文档。它能证明特定设置上的局部结果，不能证明我们的财报表格、业务取材、片段高亮或费用收益。[评测范围](https://github.com/VectifyAI/PageIndex-OSS-Benchmark)

## 我们目前在哪里

- 已有 HTML 原件冻结、块/表格位置、目录、hash 核对及范围约束。`DocumentReader.search` 是目录范围内按原文顺序的短语匹配，不是语义检索或成熟的多层主题树。
- 工作台 `source_preview` 能在冻结 HTML 的展示副本中定位并框出对应 DOM 块/整表，不改原件；当前入口只接 dataset/source/block，不能据此宣布句子或单元格精确高亮已经贯通。
- 直接模型提取的标准化记录包含经过核对的 `source_start/source_end`。通用证据包装读取的却是 `start/end`，尚有字段衔接问题；`SourceLocator` 多数精细定位字段可空，类型存在不代表每条引用都满足精度。
- 标准底稿 HTML 已输出 block 和 cell 锚点，但其存在不代表所有最终报告引用都会链接到它们；统一的“交付 → 冻结原文 → 精确高亮”验收仍未完成。
- 列表/脚注读取、历史财年目录及数据说明的既有缺陷继续存在。树索引不能自动修复这些输入和消费问题。

代码：[文档搜索](../src/uteki/agents/reading/document_reader.py:64) · [原件预览](../apps/review_workbench/pages/source_preview.py:157) · [精细证据坐标](../src/uteki/infrastructure/research_data/direct_normalization.py:271) · [证据包装](../src/uteki/infrastructure/research_data/evidence_packaging.py:54) · [底稿与单元格锚点](../src/uteki/infrastructure/document_sources/parsed_package.py:203)。

本轮运行 `tests.unit.test_workspace_source_preview`：13 项通过。它验证组件边界，包含已注册 AMD/TSMC 原件表格定位检查；不代表 Microsoft/Google 最终答案的端到端高亮已验收。未进行浏览器视觉检查。

## 哪些已经回答，哪些没有

| 问题 | 当前证据层级 |
|---|---|
| 目标是否清楚 | 清楚；目标是精确、充分、可核对的证据，不是必须使用某个索引产品 |
| PageIndex 是否相关 | 相关；官方实现覆盖建树、检索、引用，托管版还提供块区域高亮路径 |
| 我们的路径能否实现目标 | 有已有定位组件及测试支持其技术可行性；完整交付链路仍有缺口，不称已完成 |
| PageIndex 是否足够直接替代当前实现 | 尚未证明；输入格式、引用精度、范围约束、冻结原件和服务集成仍需验证 |
| 哪个更准、更快、更省 | 未回答：没有在本项目做同材料、同问题、同预算的对照 |

已有[2026-10-07 调研与讨论](../experiments/agent_design/2026-10-07-data-contract-pageindex-v1/DISCUSSION.zh-CN.md)及[Opus 意见](../experiments/agent_design/2026-10-07-data-contract-pageindex-v1/runs/opus55/answer.md)，不是本轮新顾问调用。此前调研不能改写成 PageIndex 实测通过。

## 路线比较与下一次评估

| 路线 | 合理价值（待业务实测） | 代价或风险 |
|---|---|---|
| 当前块目录 + 短语搜索 | 保留 HTML/XBRL 证据，工程成本较低 | 同义词、隐含主题、跨节取材可能漏；当前没有相关性排序 |
| 现有块上增加主题树/导航摘要 | 复用原文精度，可能减少模型反复找章节 | 建树成本、摘要遗漏/错误路由，需要搜索兜底；这叫借鉴方法，不是已接入 PageIndex |
| PageIndex SDK / Cloud | 复用现成建树、检索和引用工具 | 输入适配和证据映射；本地/托管能力不同，需分别测量 |

全文字符串扫描本身主要消耗 CPU，不等于全文输入模型的 token 开销。应分别计解析/建索引成本、工具延迟、模型实际输入、读取次数和无关材料量。索引能否省钱取决于复用次数及导航效果：总成本包括一次准备、所有查询与验证，不能只比较单轮输出 token。

**当前优先行动：先验收同一份材料的引用定位与上下文链路，确保检索返回的证据确实可消费。** 然后用 Microsoft / Google 已冻结材料对照当前短语搜索与增强目录导航；实际 PageIndex 若仅支持 PDF，另选经验证的同版官方 PDF，为所有对照路径使用一致输入，并将格式差异单列。不能把自建树结果冒称 PageIndex 结果。

对照冻结多类问题：单段事实、需要脚注的数字、跨节业务材料、无支持证据的问题。预期证据可有多个合法组合，独立审查且不喂给运行模型。首先检查来源/期间正确、必需证据齐全、引用支持且可定位；通过后比较冗余、费用、时延、重复运行稳定性。单个示范可检查接线，不代替正式多问题验收。
