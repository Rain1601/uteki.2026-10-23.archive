# HTML 10-K：产物与读取约定

2026-10-08。当前支持范围是**显式选定的 HTML 10-K 原件及其冻结处理范围**。本约定说明产物是什么、怎么读取、哪些状态不能混淆；不表示整份报告的提取质量已经通过。

一个消费包应同时交付：产物、来源/输入范围、契约版本、运行记录、质量记录。不能只把一份 JSON 脱离这些文件交给下游。不同类型沿用已有契约，不增加一套重复的统一 JSON。

## 产物和消费者

| 产物 | 内容与范围 | 正式契约 | 读取方式 | 真实样例 |
|---|---|---|---|---|
| 标准底稿 | 原件身份、正文块、表格单元格、目录、定位、图片引用；覆盖所选原件，尚无模型语义整理 | `uteki-parsed-document-v1`；包内 `schemas/`；[SourceMetadata / Manifest](../src/uteki/infrastructure/document_sources/parsed_package.py) | 先 `verify_parsed_package` 核对整个包及指定来源，再用 `DocumentReader.outline/search/read`；`document.html` 阅读全文 | [Microsoft 完整底稿](../experiments/agent_design/2026-10-08-acquisition-reuse-v1/msft/dataset/indexes/msft-2025-10k/document.html) |
| 结构化事实 | 数值或陈述、主体、期间、币种/单位、口径、限定、逐条证据、原始写法；要求范围另见任务 | [ResearchRecord](../src/uteki/domain/research_data/query_contract.py)；当前例使用 `research-query-v0.5` 精确来源日期 | 验证记录及对应版本；用规范化结果的 evidence 读取引用，或读取候选 DuckDB / QueryResult。数据库 `observations` 不是 accepted 数据 | [AMD 真实 6 项事实及证据](../experiments/agent_design/2026-10-08-required-facts-completion-v1/run-03-normalized/normalized.json) |
| 精编文档 | 中英文共享内容 ID；重要性、归属、期间、限定、每项引文、每块处置及缺口 | [Brief / Task / Review](../src/uteki/agents/filing_brief/contract.py)，`filing-brief-v1` | 将明确选择的 packet、task、packet 文件 hash 传入 `validate_brief` / `consume.render`；生成双语 Markdown 与逐块原文 HTML | [真实精编阅读页](http://127.0.0.1:8769/docs/design/data-agent-acceptance/microsoft-filing-brief-v1/)；目前仅 Operating Segments 小节 |
| 业务图 | 业务节点、类型、关系方向、事实/推断/未知、逐字段引文、未决问题；收入维度单独处理 | [BusinessOnlyDraft](../src/uteki/agents/business_map/product_contract.py)，`business-draft-v2` → [BusinessMap](../src/uteki/domain/business_map/models.py)，`business-map-v0.2` | `validate_draft` 对所选 packet 验证；`business_map_from_dict` 读域模型；[mermaid](../src/uteki/presentation/business_map_view.py) 生成图，并保留 unknown 关系列表 | [真实 79 节点候选](../experiments/agent_design/2026-10-07-business-coverage-v1/run-09/revision/business_map.json)；graph-only，内容未通过 |

底稿内 `source` 说明哪份原件；`blocks` 保存正文/表格；`toc` 和 `index` 导航；`anchors` 定位原文；`assets` 只说明图片等资产的位置。它们是同一份底稿的部分，不是六份不同的业务结论。引用单个表格数字时仍须消费表头、单位、期间、行名与必要脚注。

## 消费时必须遵守的状态

| 状态 | 可以推出 | 不能推出 |
|---|---|---|
| 包/Schema 校验通过 | 文件匹配封存 hash，字段和引用位置符合对应协议 | 语义正确、无遗漏 |
| 模型执行成功 | 本次请求收到完整响应 | 内容已验收或已采用 |
| candidate | 可以展示、检查，并在明确允许候选时查询 | accepted / 可直接当结论 |
| 自检 pass | 对应候选 hash 的那次模型检查通过 | Codex 独立内容验收通过；新修订可继承旧审阅 |
| 每块都有处置 | 系统登记了输入块的处理方式 | 块内所有重要内容均被完整提取 |
| 未处理 / 不支持 / unknown | 存在明确缺口 | 未披露、零、没有关系或证明独立 |

字段表与业务质量分别验收。精编的实际 `Review` 必须绑定 `brief_sha256`；业务图展示页须同时保留运行及内容审阅状态。raw JSON 未携带某种状态时，读取同一运行的 `result/manifest` 和审阅记录，不能自动补为通过。

## 明确的支持限制

- 本轮契约验收范围是 HTML 10-K；PDF、20-F、电话会不用于本轮通过率。已有其他格式能力不因此被删除。
- 底稿图片仅有引用，未包含图片字节、OCR 或视觉解释。表格可被正确保存而尚未完成单位/脚注的语义归属；这些属于 03/04 的内容核验。
- 事实按显式期间协议读取：v0.3 日历期、v0.4 完整月份来源期、v0.5 精确来源日期。不能把旧版本读成新版本，不能推算未知财年、币种或会计准则。模型抽取能否得到完整正确事实属于 07。
- 精编契约可表达每块处置和未完成部分；现有真实运行入口仅验过完整选定小节。整文调度、章节合并、跨节重复与遗漏、整文质量属于 08，当前没有完成。
- 业务图当前真实运行明确为 `graph_only`。产品/客户/赚钱方式详细属性中的空数组表示这个阶段没有提取，不能读作公司没有该属性或原文未披露。提取这些属性与内容充分性属于 09。
- 包、packet、task、契约版本必须同时选定。底层 Schema 验证不代替原件 hash 与公司/期间核对。消费者先调用该产物的来源验证入口；不能只对任意拼接 JSON 验字段后称其来源可信。

## 05 与后续验收的分界

**05 的工程产物已具备：版本化格式、字段含义、显式范围、实际模型候选、读取/渲染入口、出处及质量状态约定。** [本轮离线核查](../experiments/agent_design/2026-10-08-html-10k-contract-audit-v1/verification.json)实际消费了三家公司完整 HTML 10-K 底稿，以及三类真实加工候选；并检查错公司、版本与不存在引文被拒绝。

这可以支持将 **05 标为“契约与消费完成（HTML 10-K 当前支持范围）”**。不能将其解释为 07/08/09 的业务内容通过，也不能声称三类加工已在三家公司各跑通。若未来新增产物字段或格式，应版本化扩展其契约，再由对应任务验内容。
