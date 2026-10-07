# 结论

**同意先定义解析输出。** 两条问答成功不能证明解析层合格。

我的立场有四点：

- 原文包是唯一事实来源。
- `document.html` 只是从原文包确定性渲染出的阅读投影，不能作为引用根。
- 模型精编只能复用现有 narrative、EvidencePackage 和 SourceLocator 契约，在其上做增量，不另起业务身份。
- “稳定”不等于“正确”。验收必须同时包含独立的正确性检查。

以下“已实现”只指你给出的核查事实。“新增”均为建议，尚未存在。

---

## A. 产物定义

| 层 | 产品 | 最小字段 | 产出方 | 现状 | 验收 | 消费者 |
|---|---|---|---|---|---|---|
| 原文 | `source.json` | source_snapshot_id, sha256, form_type, company, report_period_end, available_at, origin_url | 冻结元数据 | 元数据已有；独立文件为新增 | 全部取自冻结材料，不推断；sha 可复算 | 全部 |
| 原文 | `blocks.jsonl` | 现有 SourceBlock 全字段；table 内嵌 TableStructure | 程序 | 已有 | text_hash 可复算；ordinal 连续；span≥1；坐标在 row/col 范围内 | Reader、渲染、定位 |
| 原文 | `containment.jsonl` | outer_block_id, inner_block_id, relation | 程序（由 dom_path 前缀推导） | **缺** | 对每个嵌套表可复算；用于去重 | 渲染、覆盖统计 |
| 原文 | `anchors.json` | anchor, dom_path, target_block_id | 程序 | 内存已有，导出为新增 | target 必须存在或带诊断 | 定位、目录 |
| 原文 | `assets.json` | asset_id, source_url, 包内相对 path, alt, dom_path, status | 程序 | 已有；需去掉对输出目录的绝对依赖 | 包内无绝对路径 | 渲染 |
| 导航 | `toc.json` | 现有 toc_entries 字段 | 程序 | 内存已有，导出为新增 | 与 anchors 交叉校验，冲突进入诊断 | index、Reader |
| 导航 | `index.json` | 现有 DocumentIndex | 程序 | 已有 | start/end block 存在；error 原样保留 | Reader outline |
| 导航 | `diagnostics.json` | code, severity, message, node_id 或 block_id, stage | 程序 | 部分已有，汇总为新增 | 不得丢弃已知 error | 人工审核、门禁 |
| 阅读 | `document.html` | 见 C1 | 程序渲染 | 新增 | 字节可复现；每个 block/cell 锚点唯一 | 人工 |
| 元 | `manifest.json` | package_id, export_schema_version, parser_version, params, 各文件 sha256、字节数、记录数 | 程序 | 新增 | 不含路径和运行时间 | 门禁、复用 |
| 业务 | 结构化事实 | 现有 ComputedScalar / 标准 adapter 映射 | 程序（adapter） | 已有 | 每值带 locator；未覆盖不得填 0 | 分析 Agent |
| 业务 | 精编文档 | 见 C2 | 模型 + 程序校验 | narrative 已有，模板为增量 | 每条陈述可解析回块或 cell | 分析 Agent、人工 |
| 业务 | BusinessMap / ResearchRecord | 现有契约 | 模型候选 → 采用 | 已有 | 采用状态与冻结版本 | 分析 Agent |

---

## B. 本轮必须落地 vs 后置

**本轮必须落地**

1. 导出 schema v0。新出口遇到未知 parser 版本必须拒绝，不改历史默认。
2. Canonical 序列化规范：
   - UTF-8，LF 换行，键排序，无多余空白。
   - jsonl 按 ordinal 排序。
   - 不使用浮点。
   - null 与“字段缺省”的规则写死。
3. 字符坐标定义。基于规范化 text，单位为 Unicode code point，左闭右开。
4. `package_id` 由 `source sha256 + parser_version + export_schema_version + canonical params` 哈希得到。block、cell 的全局引用统一为 `package_id + block_id [+ row, column]`。**不为 HTML、JSON、Markdown 各造一套 ID。**
5. `containment` 关系。否则覆盖率和渲染都会重复计数。
6. 确定性 locator 解析函数：输入 locator，返回规范化文本或单元格。这是新增内部函数，不冒充已有 `read_source`。
7. 补齐 anchors/toc/diagnostics 导出，并使用相对 asset 路径。

**可后置**

- 语义小节识别。
- 远处脚注链接。
- 表格角色判断（排版表 vs 数据表）。
- 列期间与单位理解。
- PDF、OCR、新闻、博客。
- 完整精编 schema。

**必要但缺失的语义，本轮只标 unknown，不猜**

- 表格是否为数据表。
- 列的会计期间与单位。
- 覆盖状态枚举。建议取值为 `covered / not_found_by_method / not_attempted / unresolved_error`。“一次搜索未命中”只能记为 `not_found_by_method`。

---

## C. 两份模板

### C1 标准原文阅读版 `document.html`（程序渲染）

**固定结构**

- 单文件、内嵌固定 CSS、无 JS、无外部资源。
- 每个文件头带 `renderer_version`。

**章节固定顺序**

1. `#identity`：来源身份、sha、package_id、parser/schema 版本。
2. `#diagnostics`：全部 error/warning，不折叠 error。
3. `#legal-outline`：只列 index 中已确认节点；unresolved 节点显式标红。
4. `#blocks`：按 ordinal 输出全部块。

**块级规则**

- 每块使用 `<div id="b-{block_id}" data-ordinal data-type data-text-hash>`。
- `heading_candidate` 渲染为带类名的 `<p>`，不用 `<h*>`，以区分“候选”与“确认目录”。
- `reported_page` 为空时显示“源页码：未知”。
- 图片显示“图片引用，未嵌入/未 OCR”。

**表格规则**

- 每个单元格使用 `<td id="c-{block_id}-r{r}-c{c}">`，保留 rowspan/colspan。
- 内层表在外层表内仅显示引用“已包含于 b-x”，避免内容重复。

**验收**

- 同一包渲染两次，字节相同。
- 每个 block_id 恰好出现一次 id。
- cell id 数等于 cell 总数。
- 不出现包外路径。

### C2 模型精编（复用 narrative + EvidencePackage，只做增量）

**增量只有四项**

- `template_version`：章节清单由版本化模板定义，不按公司硬编码。
- `kind` 枚举。
- `coverage[]`。
- `locator` 支持到 cell。

**示意（占位内容，非真实财务数据）**

```json
{
  "narrative_id": "nar-<hash>",
  "template_version": "filing-digest-v0",
  "parse_package_id": "pkg-<hash>",
  "status": "candidate",
  "coverage": [
    {"section_key": "risk_factors", "status": "covered", "index_node_id": "<node>"},
    {"section_key": "segment_info", "status": "unresolved_error", "diagnostic_code": "item_unresolved"}
  ],
  "statements": [
    {
      "statement_id": "st-001",
      "kind": "reported_fact",
      "text_zh": "<示例陈述>",
      "text_en": "<example>",
      "evidence": [
        {"package_id": "pkg-<hash>", "block_id": "<b>", "row": 3, "column": 2}
      ],
      "computation_ref": null
    },
    {
      "statement_id": "st-002",
      "kind": "inference",
      "text_zh": "<推断>",
      "depends_on": ["st-001"],
      "evidence": []
    }
  ],
  "gaps": [
    {"section_key": "segment_info", "reason": "目录未解析，未定位"}
  ]
}
```

**字段规则**

- `kind` 取值为 `reported_fact / management_claim / computed / inference`。
- `inference` 必须有 `depends_on`。
- `computed` 必须引用 ComputedScalar。
- Markdown 只是从该 JSON 的确定性投影。中英文共享 statement_id。

---

## D. 可复现的精确验收

| 层 | 定义 | 通过条件 |
|---|---|---|
| L1 程序重放 | 同一原件 sha、parser 版本、参数，导出到两个不同目录 | 两份 manifest 中全部文件 sha256 相同；同时记录 Python/lxml 版本。**跨 lxml 版本是否一致目前未知**，不承诺 |
| L2 格式稳定 | 校验 schema 与引用完整性 | 所有 id 引用可解析；hash 可复算；span 与坐标合法；HTML 渲染字节相同 |
| L3 语义稳定 | 同一输入下模型重跑 N 次（建议先 3 次） | 数值事实与其 locator 100% 一致，否则标记；陈述集合一致率、覆盖状态一致率先报告不设阈值，阈值待数据确定 |
| L4 冻结复用 | 已采用产物按 id 读取 | 返回 hash 不变；不触发重新生成 |

**如何发现“稳定地错”。稳定只证明重复，必须有独立检查：**

- **法定目录核对**：版本化的表单 Item 清单（10-K、20-F 各一份，来自表单规则，不来自样本公司），与 index 比对。
  - TSMC 0 item 应判“完整性不通过”。
  - AMD 的 anchor conflict 必须保留在诊断中。
- **人工抽样核对**：随机抽 block 与原 HTML 可见文本对照，抽 cell 核对行列与合并格。
- **文本覆盖率**：叶子块（去除 containment 重复后）的规范化文本，对比原文可见文本，统计缺失比例。
- **变异测试**：改动原件一个字符，相关 hash 必须变化。
- **算术核对**：对 adapter 已映射的指标做合计校验。
- **两道门禁分开**：“包有效”与“包完整”。带 error 的包可以有效，但不完整，不能被消费为“已覆盖”。

---

## E. PageIndex 分工

**SEC HTML：不用 SDK。** 只借鉴树形导航思路。现有 DocumentIndex 加 DOM anchor 已经更细。

**PDF：最小复用 `page_index_flash(pdf, summary=False, optimize=False)`。**

- 用途仅限导航产品：标题树加物理页范围。
- 不用 `submit_document`，因为它会加摘要。
- 不用 `chat`，因为它自带 Agent 循环。
- 模型循环仍由 Uteki 持有。
- 它的 node_id 不作为身份。映射时使用 `(title, 物理页范围, 包 id)`。
- 结论必须回到 Uteki 块。但 **Uteki 目前是否已有 PDF 块与 bbox 解析器，我不知道**，需要确认。若没有，PDF 的引用粒度就是当前缺口。

**源码核查支持到哪一步**：只读确认了该参数组合不调用模型，以及返回结构的形态。

**尚需的真实实验**

1. 安装固定 commit，断网运行，确认无模型调用。
2. 同一 PDF 跑两次，比较树是否一致。
3. 人工核对页范围。
4. 记录 MIT 许可声明。

AIHubMix 接 PageIndex SDK 尚未测试，但最小复用路径不依赖它。

---

## F. 三个优先动作

1. 冻结导出 schema v0：canonical 规范、package_id 规则、坐标定义、containment、locator 格式、未知版本拒绝。
2. 对 AMD 与 TSMC 各导出到两个目录，比对 manifest，跑 L2 检查与独立正确性检查，诊断原样保留，并出“有效/完整”两份结论。
3. 实现 HTML 渲染与 locator 解析函数，做人工抽样审计。之后才进入按契约的财务与业务消费案例。

## 对 Codex 草案的修正

1. **缺包级身份与 canonical 规范。** “路径与时间放包外”方向对，但未定义 package_id、序列化规则和逐文件 hash，跨目录一致无法判定。
2. **缺 containment。** 草案只说“保留可能重叠的说明”，不够，必须导出可计算的包含关系，否则覆盖率与渲染都会重复。
3. **`document.html` 定位要降级。** 它只是投影，引用根必须是 `package_id + block/cell`。否则会形成第二套身份。
4. **第 6 点缺正确性门禁。** 四层都在测“一致”，没有测“对”。需要补上表单目录核对、抽样审计、变异测试，以及“有效/完整”分离。
5. **第 5 点“暂未定 schema”可以接受，但需收窄。** 本轮只定 C2 的四项增量，不重建 narrative 与 evidence 契约。

**明确不知道的事项**

- 跨 lxml 版本的输出是否一致。
- Uteki 现有的 PDF 块解析能力。
- L3 一致率的合理阈值。