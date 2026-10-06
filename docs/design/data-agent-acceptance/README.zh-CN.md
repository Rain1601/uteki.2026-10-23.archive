# 这份 10-K 最后变成了什么？

2026-09-30 · 真实产物的只读验收样本。先看结果，再看结构、过程和未完成项。

**当前实际完成的是：在已经预处理的 Alphabet FY2025 10-K 上，查询并核对 4 条数字，新生成一个包含 3 条陈述的回答，再进行独立内容核验。尚未交付整份年报的完整研究数据包，约定的核心财务包也未补齐。**

材料身份：Alphabet Inc.；10-K；报告期末 2025-12-31；本地来源记录的可得日期 2026-02-05。本次只使用 `googl-2025-10k`；同库的 10-Q 不属于本题输入。

续读：[召回验收、不同措辞实测，以及公司／年份／材料类型／行业查询边界](retrieval-acceptance-2026-09-30.zh-CN.md)。

[冻结原件](../../../data/company_workspace/extraction_ab_v1/corpus/googl/dataset/raw/googl-2025-10k.html) · [SEC 原文](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000018/goog-20251231.htm) · [全部 111 条财务候选](GOOGL-2025-10K-financial-candidates.md) · [解析结构及完整目录](GOOGL-2025-10K-source-structure.md)

## 1. 先看本次交付的内容

### 四条数值记录

本题要求：核对 2024、2025 年合并经营现金流、购建固定资产现金支出，以及资本支出的主要用途。

| 指标 | 2024 全年 | 2025 全年 | 原文位置 | 本题内容核验 |
| --- | ---: | ---: | --- | --- |
| 经营活动提供的现金净额 | 125,299 | 164,713 | 第 52 页合并现金流量表 | 两条均支持 |
| 购建固定资产现金支出 | 52,535 | 91,447 | 同一现金流量表 | 两条均支持 |

表中单位为 **百万美元**，与原表单位相同。第二行展示支出幅度；原报表用括号表示流出。程序存储为美元，例如 `164,713 million USD → 164713000000 USD`。没有把补充披露中的非现金项目加进这四条记录。

这些数字来自此前已生成的 XBRL 候选记录，本次 Agent 负责查找、核对及组装证据，不能计作四条新发现的模型抽取。

### 三条叙述陈述

下表是原模型产物的中文阅读说明；原始英文 statement、时间标签与逐字引文均保留在[真实回答对象](../../../experiments/architecture_baseline/2026-09-30-data-handoff-v1/e2e-01/data-query/query/artifacts/art-822cbc74c0d7a586dda391d2d4c2e7cc.json)。

| 编号 | 保存了什么内容 | 时间属性 | 原文位置 | 本题内容核验 |
| --- | --- | --- | --- | --- |
| C1 | 主要用途有两类：技术基础设施（服务器、网络设备、数据中心土地、建筑施工和改善）；办公设施、新建开发项目、建筑改善 | 不限定单一年度；不是逐年金额分配 | 第 38 页，块 614–616 | 支持；两类齐全 |
| C2 | 2024、2025 年实际资本支出分别为 52.5、91.4 billion USD | 已报告实际数；叙述为取整披露 | 第 38 页，块 618 | 支持 |
| C3 | 预计 2026 年技术基础设施投入较 2025 年显著增加 | 前瞻预期，不能当作已经发生 | 第 38 页，块 618 | 支持 |

**本次新增的叙述产物是一个回答对象，里面有 3 个 claim。** 其中 C1 引用引导句和两个列表项，不是只抓到“AI”或“数据中心”两个词就算答完。

### 你可以亲自核对的一条内容

原文第 38 页先写主要类别引导句，再列两项。其中第二项原文是：

> •office facilities, ground-up development projects, and building improvements.

人工查看时，将它与 C1 对照：是否遗漏办公设施；是否擅自添加年度占比；是否把“用途类别”改写成“投资回报”。这是内容验收。引用 ID 存在、JSON 合法或测试通过，都不能替代这一步。

[原文块 616](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/indexes/googl-2025-10k/blocks.jsonl:616) · [对应候选回答](../../../experiments/architecture_baseline/2026-09-30-data-handoff-v1/e2e-01/data-query/query/artifacts/art-822cbc74c0d7a586dda391d2d4c2e7cc.json) · [独立模型审阅结论](../../../experiments/architecture_baseline/2026-09-30-data-handoff-v1/e2e-02/data-review/response.json)

## 2. “解析”目前包含三个不同层次

| 层次 | 真实产物长什么样 | 谁生成 | 此次是否新生成 |
| --- | --- | --- | --- |
| 文档结构 | 1,338 个原文块，保存段落、表格、列表、页码、定位；另有 28 个目录节点 | 程序解析 HTML | 否，复用已有冻结索引 |
| 可查询财务候选 | 本份 10-K 有 111 条记录，保存主体、指标、期间、数值、单位、口径与证据 | 程序映射已支持的 XBRL 标签并归一化 | 否，复用已有候选库 |
| 本题证据交付 | 4 条选定数字＋3 条叙述陈述＋原文证据＋逐项核验 | Data Planner/Worker 与独立 Reviewer | 是，本次实际运行 |

**结构解析不等于语义抽取；有若干候选记录不等于核心财务包完整；答完本题不等于整份 10-K 处理完成。**

原文结构包含 622 个段落、273 个标题候选、185 个 HTML table、148 个列表项、97 个页码块、11 个其他块、2 个图片引用。185 个 table 包含页眉、目录和空表，不是 185 张财务报表；图片内容尚未解析。详细拆分见[结构视图](GOOGL-2025-10K-source-structure.md)。

111 条财务候选只覆盖营收、净利润、营业利润、经营现金流和 PPE 现金支出五类指标，含多期间、维度与重复披露。现金、债务、股本等已确认核心财务包的其他部分尚未补齐。原文中有数据但当前适配器未映射，必须标为工程缺口，不能说公司没有披露。

### 数值记录的真实格式

以下为实际记录的字段节选，不是新拟造的输出示例：

```json
{
  "record_id": "obs-b8d3ac73ea8cbbe84ae10f92",
  "record_type": "metric",
  "entity_id": "sec-0001652044",
  "metric_id": "operating_cash_flow",
  "period": {"kind": "year", "start": "2025-01-01", "end": "2025-12-31"},
  "value_kind": "actual",
  "value_decimal": "164713000000",
  "unit": "USD",
  "accounting_basis": "reported_consolidated",
  "source_snapshot_id": "googl-2025-10k",
  "evidence_ids": ["ev-0028f0247cd624ef233825ab"],
  "status": "candidate"
}
```

[完整记录](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/records.json:1052)还保留 origin、XBRL concept/context、归一化说明等。[证据对象](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/evidence.json:692)保存原文 `164,713`、单位缩放、块 ID、HTML 定位及来源哈希。

### 叙述回答的真实格式

现有 `SourceAnswer` 将 `requirement_id` 与 `claims[]` 关联；每条 claim 保存：

| 字段 | 用途 | 本次 C3 的真实值或内容 |
| --- | --- | --- |
| statement | 模型提取的明确陈述 | 2026 年技术基础设施投资预计较 2025 年显著增加 |
| temporal_basis | 区分实际、未来及不限定年度 | `forward_looking` |
| period_context | 陈述适用的时间与上下文 | 2026 relative to 2025，10-K 第 38 页 |
| citations | 原文出处与连续逐字引文 | block-000618-45e1aa4d，原句以“In 2026, we expect…”开头 |

回答外围还保存覆盖声明、未解问题和版本。上表中文是展示解释，字段原值见原回答 JSON。它与数值记录是两种已有对象，目前还没有统一成对人完整可读的“每份材料数据包”。

## 3. 这次 Data Agent 实际经历了哪些环节

下图是本次执行过程，不是新的系统架构提案。

```mermaid
flowchart LR
    A[此前：原件解析与候选库] --> B[接收限定问题]
    B --> C[规划与委派 Worker]
    C --> D[主角色查数及读原文]
    D --> E[4 条数字与 3 条陈述]
    E --> F[独立内容核验]
    F --> G[限定 Analysis 候选]
```

| 实际阶段 | 发生了什么 | 可以检查的产物 |
| --- | --- | --- |
| 运行前准备 | 原件与索引、候选库已存在，使用确定性预处理 | [dataset manifest](../../../data/company_workspace/extraction_ab_v1/corpus/googl/dataset/manifest.json) |
| 主角色第 1–2 步 | 载入 query Skill，声明四项数值、一项原表核对、一项用途回答 | [实际计划](../../../experiments/architecture_baseline/2026-09-30-data-handoff-v1/e2e-01/data-query/query/turn-002/decision.json) |
| 第 3 步的 Worker | 查到两个 PPE 数值；出现参数/输出格式错误，在 10 步内未完成全部正文交付 | [Worker 结果](../../../experiments/architecture_baseline/2026-09-30-data-handoff-v1/e2e-01/data-query/query/turn-003/worker/result.json) |
| 主角色第 4–12 步 | 第 4 步读取被拒；第 5–8 步重查四项数值，第 9–12 步取得并读完原始现金流表 | [第 12 步交付反馈](../../../experiments/architecture_baseline/2026-09-30-data-handoff-v1/e2e-01/data-query/query/turn-012/feedback.json) |
| 主角色第 13–23 步 | 定位并读取资本支出段落；期间发生重复读表和分页误用 | [完整 25 步轨迹](../../../experiments/architecture_baseline/2026-09-30-data-handoff-v1/e2e-01/data-query/query/result.json) |
| 主角色第 24–25 步 | 保存 3 条陈述，封存本题证据包 | [第 24 步回答](../../../experiments/architecture_baseline/2026-09-30-data-handoff-v1/e2e-01/data-query/query/turn-024/decision.json) |
| 独立 Data Reviewer | 原问题、7 条事实、6 项要求及完整索引文本进入独立模型调用；逐项核验 | [审阅响应](../../../experiments/architecture_baseline/2026-09-30-data-handoff-v1/e2e-02/data-review/response.json) |
| Analysis | 消费通过核验的交付，生成分析候选；核验状态理解仍有错误 | [实际分析响应](../../../experiments/architecture_baseline/2026-09-30-data-handoff-v1/e2e-02/analysis/response.json) |

首轮 Reviewer 被本地请求体容量限制拦截；修复后通过固定 query 哈希续跑，未重做 Data。历史失败记录保留。完整工程记录见[本次实验](../../../experiments/architecture_baseline/2026-09-30-data-handoff-v1/README.md)。本样本展示可见动作和产物，不展示模型隐藏推理。

**Direct Extractor 本次没有运行。** 它是另一个已有实验入口，输出 records / relations / gaps；不能将其设计能力算作这次“按题查询＋叙述回答”的实际成果。

## 4. 谁在 Review，哪些状态需要分开看

| 检查者 | 本次实际做了什么 | 不能由此推出什么 |
| --- | --- | --- |
| 程序 | 检查字段、来源范围、文件哈希、引用原文及交接条件 | 无法仅凭这些判断类别是否遗漏或解释是否合理 |
| 独立 DeepSeek Reviewer | 实际执行一次内容审阅，7 facts / 6 requirements 全部支持 | 模型意见不是保证正确，也没有发布完整报告 |
| 当前 Codex 辅助复核 | 独立读取原文再对照结果；发现 Analysis 对核验/采纳状态的混淆 | 仍是 AI 辅助核对，不等于你已人工验收 |
| 用户人工验收 | 通过此样本比较原文、提取内容与核验意见 | 当前尚未记录你的内容验收结论 |

一条记录可以同时是：**本题程序校验通过、本题内容核验通过、源数据尚未全局采纳、没有对外发布**。因此原记录的 `candidate` 不能被解释成“这条数据从未被审过”。当前这些状态分布在不同文件中，统一展示尚未成为正式产品功能；这份样本将它们放到一起。

## 5. 输出规范与不同材料方法：建议及当前差距

已有 SourceBlock、ResearchRecord、SourceAnswer 和 Review schema，分别约束结构、数值、叙述与核验；缺少的是统一的材料交付和覆盖说明。建议先复用它们，固定下面六项可人工验收内容，而不另造一套巨型 JSON：

| 每份交付必须让人看到 | 至少包含什么 | 本样本情况 |
| --- | --- | --- |
| 材料身份与处理范围 | 公司、form、报告期间、版本、可得时点；全材料基线还是限定问题 | 已明确，属于限定问题 |
| 文档结构 | 目录、正文/表格/图片、解析异常、原文定位 | 已有；图片未解读、部分表格类型未验收 |
| 数值事实表 | 原文值和单位、标准值、期间、主体/维度、会计口径、actual/guidance、出处 | 已有部分指标，核心包未齐 |
| 叙述事实卡 | 陈述、归属、时间属性、限定语、引用；管理层预期不当作已实现事实 | 本题已有 3 条；不是全年报业务/风险包 |
| 覆盖与缺口 | 已处理、未处理、解析失败、未披露、语义未确认分别列出 | 本题有覆盖检查；整份材料的语义抽取覆盖账本尚未交付 |
| 核验与版本 | 程序检查、任务内容核验、全局采纳、人工验收分别显示；保存修订前后 | 底层部分已有，统一展示及修订流程待完善 |

关于 10-K／10-Q／8-K，**确实需要不同的处理重点；我的建议是共同 System Prompt＋按材料类型选择的版本化提取清单／Skill＋统一输出格式。** 独立三份完整 System Prompt 可以作为后续实验，但应先防止引用、时间与格式规则在三份提示词里漂移。

下面是处理重点建议，不是已经实现或通过验收的专属 prompt：

| 材料 | 方法差异建议 | 当前实现 |
| --- | --- | --- |
| 10-K | 年度基线：已确认的核心财务包；业务、风险等叙述内容按显式研究范围处理，记录覆盖 | 通用 query Skill；本题只做现金流和资本支出，未完整交付年度基线 |
| 10-Q | 明确单季、年初累计和时点数；关联年度基线及变化；不能机械套用年报期间 | 有部分解析/财务候选能力；尚无经本次验证的专属语义提取清单 |
| 8-K | 按事件、披露日期、涉及主体、相关 Item 和附件组织；业绩附件可含数字事实；不强行补成整套年报 | 本次未验收；不能仅换 prompt 就宣称采集、附件解析和事件格式已支持 |

材料结构依据：SEC 的 [10-K 表格说明](https://www.sec.gov/files/form10-k.pdf)、[10-Q 表格说明](https://www.sec.gov/files/form10-q.pdf)、[8-K 表格说明](https://www.sec.gov/files/form8-k.pdf)；上表是据此提出的 Uteki 处理建议。当前 Planner/Worker 使用共同系统提示词及 query Skill，没有按三种 form 选择已完成验收的专属模型抽取 prompt。

## 6. 接下来如何验收

先逐项核对本页的真实原文、四条数字和三条陈述；核对“这些就是我们要交付的数据对象”以及遗漏/多余信息。再补齐已确认的核心财务包，并用同样的可读交付形式验收另一份明确选定的 10-Q。8-K 先定义事件与附件交付规范，再准备真实样本。新方法和范围中确有取舍时，用选项确认；不重复询问已经确认的“核心财务包＋其他按需”。

**通过标准是产物可读、来源可核对、期间/口径正确、范围及缺口清楚。** 运行次数、测试数量和 schema 合法仅作为辅助证据。
