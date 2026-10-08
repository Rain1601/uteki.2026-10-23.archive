# 原始 10-K 到保存与消费数据：现有代码总览

> 进度更新：本文下面保留本轮实施前的审查快照。后续已重建两份冻结数据、修复列表/脚注/财年目录与指标说明，并贯通字符/单元格原件预览。系统自主取材与内容复核的六题矩阵及目录分页针对性复跑已独立验收通过；最新实际状态见 [完成计划](../experiments/agent_design/2026-10-09-data-agent-completion-v1/PLAN.zh-CN.md) 和 [真实 HTTP 定位检查](../experiments/agent_design/2026-10-09-data-agent-completion-v1/validation/source-preview-http.json)。后续确有模型调用；下文“未调用”仅指当时只读审查。未运行 PageIndex，仍不能声称与其做过实测对照。

## 实施前审查快照

2026-10-09，只读代码审查及既有产物检查；本轮未发起模型调用或新提取。范围是现有 Microsoft / Alphabet FY2025 SEC HTML 10-K。区分已实现组件、真实已有产物与尚未通过的整链路质量，不将所有组件画成已自动串联的工作流。

## 1. 原材料是什么

本轮是 SEC 原始 HTML 申报文件，包含正文、HTML 表格、目录链接、图片引用及内嵌 XBRL 标签。XBRL 是报告发布方附在数字上的机器可读标记，携带指标名、公司、期间、单位等上下文；不是模型后来补写的内容。

获取输入还有显式公司、报告形式、期间/截止日期及来源选择配置。原件保留 URL、字节 hash、形式、报告期、可获得日期与获取记录。现有两份材料已经存在，本轮没有重新在线下载。不能把这两份样例当作全部历史申报收齐。

入口：[prepare_sources](../src/uteki/infrastructure/document_sources/company_acquisition.py:267)；冻结数据构建：[materialize_sources](../src/uteki/infrastructure/research_data/company_materialization.py:273)。

## 2. 当前有两条生成结构化数据的路径

```text
已核验的原始 HTML
    │
    ├─ 程序解析正文、表格和目录 ─→ 可定位底稿＋索引＋Schema
    │
    └─ 程序读取支持的 XBRL 标签 ─→ 财务候选记录＋证据＋候选数据库
                                       （以上属于基础准备，不调用模型）

另行启动的模型提取任务：
冻结底稿＋明确任务/材料范围＋提示词/Skill＋输出 Schema
    → 模型返回提取候选
    → 程序校验、绑定证据、标准化
    → 新的候选记录/数据库快照＋未解决项＋运行日志

查询消费：
模型参考目录/说明规划读取 → 工具读取原文或执行类型化查询
    → 保存本次证据与查询快照 → 向下游交付材料
```

模型不直接持有数据库连接写表。模型返回内容；程序决定其是否符合协议、如何转换、存入哪个新快照、哪些内容保留为未解决候选。程序写文件本身不能用来判断是否有模型参与。

## 3. 实际保存哪些类型，如何使用

| 数据对象 | 保存形式 | 生成方式 | 消费方式与边界 |
|---|---|---|---|
| 原件与来源身份 | 原 HTML、`source.json` / `sources.json`、hash 与 manifest | 工程获取、核验、冻结 | 原文回查与范围验证；公司、期间、版本不能猜测 |
| 文本块和表格 | `blocks.jsonl`；块含类型、正文、位置；表格含行列/单元格 | HTML 结构解析，无模型 | 按块读取，保留表头/单位/脚注；当前上下文关联仍有缺陷 |
| 目录与定位 | `toc.json`、`index.json`、`anchors.json` | 程序识别报告结构、锚点、块范围 | `outline`、字符串搜索、原文定位；不是完整语义索引 |
| 图像资源说明 | `assets.json` | 程序收集引用 | 当前仅资源位置与状态，未提供 OCR / 视觉理解 |
| 结构化事实候选 | `records.json`、`evidence.json`、`metrics.json` | 基础路径从 XBRL 提取；另一条路径由模型提取后程序标准化 | 数值/事实带主体、期间、单位、口径、证据；必须辨别来源路径和 candidate 状态 |
| 可查询数据库 | `research.duckdb`、`schema.sql` | 程序把候选记录及来源投影到数据库 | 类型化查询编译成参数化 SQL；不是模型自由执行 SQL |
| 契约与数据说明 | 包内 `schemas/*.schema.json`、来源/指标/期间目录、capabilities、质量状态 | 类型定义导出及程序汇总 | Schema 说明格式；含义、覆盖、工具、限制说明尚不够充分 |
| 查询交付与过程 | `evidence-bundle.json`、`result.json`、`artifact-index.json`、逐步记录 | 模型决定操作，执行器读取并保存 | 是这次问题取到的材料，不是另一份自动完成的全报告数据集 |

JSON 是文件格式；正文、索引、财务事实、证据、运行日志是不同语义类型。`records.json` 和数据库 `observations` 往往是同一批候选的两种表示，不能重复算两套独立事实。Schema 及日志属于说明/运行信息，也不应与财务内容混为一类。

底稿及 Schema：[build_parsed_package](../src/uteki/infrastructure/document_sources/parsed_package.py:309)。数据库当前有 `observations`、`sources`、`evidence`、`metric_definitions` 四张表：[DDL](../src/uteki/infrastructure/research_data/query_dataset.py:24)。

## 4. 基础准备具体怎么处理

1. 校验公司、来源、原件字节 hash、截止日期和可获得日期；不在范围内的材料记录缺口。
2. 解析 HTML DOM，生成正文/标题/表格等块，保存原文路径和内容 hash，构建目录、定位锚点和索引；图片只保留引用。
3. 生成底稿 Schema、可阅读的 `document.html` 与校验清单。HTML 阅读页是程序渲染的原文底稿，不是模型生成的精编。
4. 读取内嵌 XBRL，匹配显式支持的标准指标，解析数值、符号、尺度、单位、期间及维度，核对公司并绑定原文块。
5. 将能支持的事实保存为候选记录和证据；不支持的概念或期间写入缺口。写入新的 DuckDB 快照，不宣布内容已采用。

代码：[HTML 入口](../src/uteki/infrastructure/research_data/company_materialization.py:87) · [XBRL 提取](../src/uteki/infrastructure/research_data/company_materialization.py:143) · [持久化](../src/uteki/infrastructure/research_data/company_materialization.py:360)。

真实产物：所选 Microsoft 底稿 1,401 块、102 条 XBRL 候选出现记录；Alphabet 1,338 块、111 条。两份实际记录均涉及收入、营业利润、净利润、经营现金流、购建固定资产现金支出五个指标 ID；同指标可能有多期间/维度/重复披露。这些数量不是五项指标的完整性证明，也不是去重后的已验收事实数。适配器未涵盖所有标准标签与公司自定义标签。

## 5. 模型提取具体怎么处理

当前有独立的直接提取及注册财务批次工具，不在每次 `materialize_sources` 时自动执行。

1. 任务显式绑定公司、source、截止日期、底稿 hash、任务指令及块范围，按所选版本的方法/Skill 准备提示和输出 Schema。
2. 模型接收原文、表格、任务及有关目录，返回结构化候选、证据引用和缺口。provider / model 取自运行配置；不是由 JSON 文件扩展名决定。
3. 程序检查协议、来源绑定和可支持的标准化，保存原始响应及每次提取结果。能标准化的成为记录；不能解释的保留 unresolved，不用隐式公司/期间/指标兜底。
4. 保存 `extraction.json`、`normalized.json` 及新的 `dataset/`，包括候选数据库、证据、覆盖与未解决项。旧底稿不被覆盖，新数据库也不会直接把基础金额重复叠加进去。
5. 在自主 Query 中，`financial_extract` 只允许调用已注册任务/批次，返回 candidate 回执；这不等于自动采纳或证明整份财务提取完整。

代码：[提取输入](../src/uteki/infrastructure/research_data/direct_extraction.py:27) · [模型调用与标准化](../src/uteki/infrastructure/research_data/direct_extraction.py:189) · [新快照](../src/uteki/infrastructure/research_data/direct_extraction.py:104) · [注册工具](../src/uteki/infrastructure/research_data/financial_tasks.py:40) · [Agent 调用](../src/uteki/agents/data_query/autonomous.py:1071)。

## 6. 精编、业务图与最终分析的位置

仓库另有模型加工入口：精编运行器输出带引文的 `brief.json`，再渲染 Markdown / HTML；业务图运行器输出业务候选，再由程序生成可视图。它们确实使用模型，但不属于基础解析时必然生成的产物。目前真实精编仅覆盖选定小节，不能说整份年报精编已完成。

按最新确认职责，业务图与分析报告属于下游 Analysis 产物；旧代码的 business_map / filing_brief 目录和历史入口仍在，并未因讨论就完成职责迁移。来源忠实的精编可作为可选数据加工任务，但不能代替原文，是否纳入当前首关需单独定义。本轮首关只验已选两份 10-K 的材料与基础数据质量。

代码：[精编模型及保存](../src/uteki/agents/filing_brief/run.py:183) · [业务图工作流](../src/uteki/agents/business_map/workflow.py:44)。

## 7. 尚不能宣称的能力

- 不是“丢入任意 10-K，就自动生成完整财务库、精编、业务图并全部通过”。现有是多个有范围约束的入口。
- 两条财务提取路径、模型运行结果和数据采纳状态必须可区别；模型提取存在不意味着已给这两份年报全量运行。
- 底稿字段合法、数据库能查、模型正常返回都不代替内容验收。
- Schema 已有，但指标释义、历史财年目录、脚注/列表读取和部分格式兼容仍有已确认缺口。

当前唯一下一步：按上述真实产物边界验收已选两份 10-K，先处理已复现的底稿及读取缺陷，再验模型提取和 Query 的最小充分材料。具体证据见[材料验收](../experiments/agent_design/2026-10-09-material-acquisition-audit-v1/README.zh-CN.md)。
