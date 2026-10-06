# Uteki Data MCP：只读验收 v1

2026-10-05 后续进展：首轮消费者的 7 项 FY2023 数据库缺口已交由真实 Pro / Flash 选材与提取，形成新的候选数据库并完成原文核验，比较年度保留。[实际入库与审核登记核验](../experiments/architecture_baseline/2026-10-04-amd-tsmc-annual-v1/gap-completion-inputs-v1/registered-target-facts-acceptance.json)记录了 7 条目标事实及来源。新结果已在公司材料后台登记；本页描述的 `readonly-v1` 目录与历史消费者实验保持原样，新一轮 MCP 消费仍需显式选择新的目录版本。未采纳候选，不代表完整财报或全自动闭环验收。

用户在 2026-10-05 选择首轮 A：对外提供已有真实数据与原文，让不继承维护者讨论的 Codex 独立取数。此版交付是数据消费接口；查询期间不下载、不提取、不调用 DeepSeek、不写入事实、不改变审核或采纳状态。

## 本轮验收问题

输入是公司、年度材料范围、知识截止日与候选使用政策。外部调用者先发现已登记版本，再明确选择公司、数据版本和来源；不用知道本机目录、数据库文件或内部任务路径。

预期产出是：带期间、单位、出处和审核状态的事实；可定位的原文段落/表格；尚未覆盖的指标和处理缺口。

验收案例：截至 2026-10-04 的官方年度材料，比较 AMD 与台积电 FY2023 的营收、营业利润、经营现金流、现金购置固定资产、期末现金。先查数据库，缺项可读原文，但必须区分数据库事实与消费者本次阅读结果。未知公司、未覆盖年度、跨公司证据不得静默替换。内容正确性由独立原文答案核对，不能只看工具调用成功。

## 四个工具

| 工具 | 输入 | 输出与边界 |
|---|---|---|
| `discover_data` | 公司名/别名/代码、截止日；可选材料类型与报告期末日期区间 | 已登记版本、来源、可复制的 selection、入库/提取/审核状态。不是全市场公司目录，不自动选择最新版本。 |
| `get_data_schema` | selection + metrics/entities/periods/coverage/fields/examples | 指标定义、可见期间、实际样例与字段说明；分页。指标目录只代表已入库覆盖，不能据此断言原件未披露。 |
| `query_facts` | selection + 指标/实体/精确期间，或已登记公式 | 事实、数值单位、证据、逐条外围审核、缺口。自然语言 question 仅作任务上下文，不直接生成 SQL。 |
| `read_source` | selection + 原文 ID + outline/search/read/context/evidence 操作 | 目录、字面检索预览、完整段落/表格或证据；保留原始 URL、哈希与定位。预览不是完成阅读，超限显式报缺口。 |

selection 必须包含 `dataset_id`、`company_id`、`source_snapshot_ids`、`knowledge_cutoff`；`include_candidates` 默认 false，访问候选事实和原文需显式 true。没有记录时不补零，不推断未披露，也不换公司或期间。财年名称不能替代精确日期；从元数据、样例或原文取得日期，非日历财年使用 `basis=source`。

MCP 使用官方 Python SDK 2.2.0 的 stdio 传输，四个工具均声明只读。复用现有 `QueryDataPort.scoped()`，只执行受控参数化查询；未开放任意 SQL、本机路径、补提任务或调度。期间视图同时列出来源声明与已存记录的精确期间；两者均受相同范围限制。

`read_source` 的 read/context 默认返回 `compact`：表格包含 `cell_fields`，每个 `cells` 数组按该字段顺序解释；保留全部空单元格、行列位置、跨度及正文。可显式请求 `representation=full` 获取原单元格对象。两种表示都不截断正文，超过上限仍返回明确缺口。

## 冻结数据登记

主机启动时必须指定目录配置。本次配置为 [data-mcp-readonly-v1.json](../config/data-mcp-readonly-v1.json)，仅登记明确选择的 AMD / TSMC 验收资料，没有在共用代码里设公司、年度或数据路径默认值。

| 版本 | 当前结构化记录 | 原文读取 | 审核/采纳 |
|---|---:|---|---|
| AMD 年度原文库 v2 | 0 | 有 | 未完成财务提取，candidate |
| 台积电年度原文库 v2 | 0 | 有，含 20-F | 未完成财务提取，candidate |
| AMD FY2023 利润表批次 | 9 | 有 | 逐条外围审核保留，candidate |
| AMD FY2023 资产负债表批次 | 3 | 有 | 10 草稿、3 入库、12 诊断事件；逐条外围审核保留，candidate |

两次 AMD 提取分别登记，不自动合并为一个“完整财务包”。审核意见按记录、来源与输入哈希绑定；审核材料里的独立金标不提供给消费者。历史实现归档哈希声明不一致仍作为可复现性缺口返回，不修改原冻结文件。

`sources.stage_coverage` 是原文索引生成时的历史状态；`data_state.normalized_record_count` 才是所选数据版本与来源范围内当前的入库数。`complete` 只针对本次具体查询/目录页，不是整份财报完整性。

## 启动与调用

依赖：`uv sync --locked --extra data --extra mcp`。当前工作环境已有所需依赖，实际验收未重新安装依赖。

在仓库根目录启动 MCP server，供支持 stdio 的 MCP 客户端配置：

```bash
.venv/bin/python -m uteki.interfaces.data_mcp.server --catalog config/data-mcp-readonly-v1.json
```

仓库同时提供真实协议客户端，便于直接检查工具和保留审计：

```bash
.venv/bin/python -m uteki.interfaces.data_mcp.client \
  --catalog config/data-mcp-readonly-v1.json \
  --audit /tmp/uteki-mcp-new-session.jsonl
```

每行输入一个请求，例如：

```json
{"method":"tools/list"}
{"method":"tools/call","params":{"name":"discover_data","arguments":{"request":{"company_queries":["AMD","台积电"],"knowledge_cutoff":"2026-10-04","include_candidates":true,"period_end_from":"2023-01-01","period_end_to":"2023-12-31"}}}}
```

这是显式选择的验收示例；共用服务没有这些默认值。审计文件只创建新文件，不覆盖历史会话。客户端返回标准 MCP result，业务结果在 `structuredContent`；同时保留标准文本内容。

本轮未修改用户的全局 Codex MCP 配置。独立消费者通过协议客户端使用真正的 MCP 服务；这是新 Agent 的取数试验，不声称已经完成桌面插件安装或原生侧栏挂载。

## 证据与当前限制

- 81 项定向检查通过，涵盖只读协议、两公司独立合成数据、不同期间、候选限制、20-F 缺口诊断、版本/截止日/来源隔离、分页、哈希篡改、审核绑定及大表无损读取。
- [独立消费者验收记录](../experiments/data_agent_mcp/readonly-v1/README.md)单独保存输入、实现哈希、原始协议调用、回答和原文复核；工程测试数量不代表模型质量。
- 首版一个登记版本对应一家公司；多公司比较由消费者分别选择版本后汇总，不提供跨库 SQL。
- 检索仍为字面检索；未新增语义搜索、OCR、自动补提或新的数据提取能力。
- 原文索引有固定响应上限，超大的完整上下文会显式返回缺口，不能静默截断后声称完整阅读。
- 本轮目标是验证消费能力。仍需继续补齐 AMD/TSMC 结构化财务覆盖，再比较相同问题下供应商 MCP 的覆盖、准确性和成本。
