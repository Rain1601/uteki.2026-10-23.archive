# 原材料 → 索引 → 读取上下文：工程复核

**结论：文字没有丢失，不等于 Agent 能收到完整的阅读单元。所选真实底稿中确认了列表拆散、脚注未随表返回，以及 compact 读取与交接复核不兼容三个具体问题。建议先修这些前置问题，再解释模型 benchmark 的优劣。**

本轮只读原件、解析文件和代码，没有模型调用、网络请求或修复。精确输入路径、SHA-256、原文 DOM 路径、逐块文字、实际读取返回值和代码哈希均在 [material-probes.json](material-probes.json)。JSON 内包含原文文本，仅用于项目内核查。

## 输入边界：本轮读取的是 v0.1.11，不是旧核查的 v0.1.12

| 样本 | 本轮明确选择的数据集 | 实际解析包 | 来源 SHA-256 |
|---|---|---|---|
| Microsoft FY2025 | `experiments/agent_design/2026-10-08-acquisition-reuse-v1/msft/dataset` | `indexes/msft-2025-10k` | `0edfaac937bf7042c8cf7901924ccb9cc291ccfab92f83dd0b689b7912089bf6` |
| Alphabet FY2025 | `experiments/agent_design/2026-10-08-acquisition-reuse-v1/googl/dataset` | `indexes/googl-2025-10k` | `c2f6301004f35411a20611c14ff01d80a85c0bcbab6053c80d8cc7f6fc747161` |
| AMD FY2023 | `experiments/agent_design/2026-10-08-acquisition-reuse-v1/amd/preparation/dataset` | `indexes/source-291485b98a75d8cfabe47571` | `47955f5d3d309e40c53ac7243dc955c8c1b594605fa938db1b5c411aaf2aa808` |

三个本轮包的 `index.parser_version` 都是 `sec-source-blocks-v0.1.11`。此前 [逐节覆盖核查](../2026-10-08-tenk-section-coverage-v1/README.zh-CN.md) 使用 `2026-10-07-foundation-parallel-v1/parser/packages/{msft,googl,amd}` 的 v0.1.12。JSON 逐项比较了 index 和 blocks 字节哈希。**不能把此前 18,155 段匹配的结果直接当作本轮三个运行包的哈希验收。**

本轮针对下面每个例子，从冻结 HTML 重新构建 DOM，以解析块保存的 `dom_path` 定位原始元素，对规范化原始文字和块文字作比较，所有所列块均匹配。三个所选原件的实际 SHA-256 与来源元数据一致，原件及包在检查前后未变。

## 1. Microsoft 的列表符号与列表正文被拆开，读取失去父级关系

优先级：高。证据编号：`M1`。

Microsoft 所选底稿全部 114 个 `list_item` 块都是单独的 `•`；正文另存为 `paragraph`。在 Item 1：

| 行号 / block 序号 | 类型 | 原文功能 | `read(count=1)` 实际返回 |
|---|---|---|---|
| 117 | heading_candidate | Intelligent Cloud | 117、118、119 |
| 118 | paragraph | 说明本分部及 `This segment primarily comprises:` | 117、118、119 |
| 119 | list_item | `•` | 117、118、119 |
| 120 | paragraph | Server products and cloud services；含 Azure、GitHub、Nuance 等 | 120 |
| 121 | list_item | `•` | 121 |
| 122 | paragraph | Enterprise and partner services | 122 |

原文 DOM `/html/body/div[18]/div[1]` 下，`span` 是符号，兄弟 `div` 是正文；第二个条目使用同样结构。读取分部标题只能得到标题、介绍和一个空符号；直接命中 Server products 的正文又收不到分部介绍及第二个条目。

这不是“原文没写清”，也不是模型能力的独立证据。它是阅读上下文构建缺陷：[`reading_groups.py`](../../../src/uteki/agents/reading/reading_groups.py) 第 7–12 行将符号块认作完整条目，第 68–85 行遇到实际正文 paragraph 就结束列表。

拟议修复边界：依据原 DOM 结构恢复符号与正文的关联，再构建列表阅读组。保留原 block ID/引用；不得把 Microsoft 的业务答案写入规则。必须验证从父级介绍、任意条目正文正向/反向读取都保留相同列表结构。

## 2. Microsoft 与 Alphabet 的“脚注标记 + 单独解释块”未随主表返回

优先级：高。证据编号：`M2`、`G1`、`G2`。

| 样本与原件页码 | 主表及实际返回 | 明确遗漏的相邻原文 |
|---|---|---|
| Microsoft p84，地域收入 | 主表 1219，仅返回 1218–1219 | 1220 `(a)`；1221 解释 United States 包括 OEM 和部分跨国组织账单，原因是这些业务性质及地域归属难以确定 |
| Microsoft p81，股票奖励 | 主表 1166，仅返回 1165–1166 | 1167 `(a)`；1168 解释包含按目标授予及高于目标的 PSU 调整 |
| Alphabet p78，回购 | 主表 1155，仅返回 1154–1155 | 1156 `(1)`；1157 `Shares repurchased include any unsettled repurchases.` |
| Alphabet p81，每股收益 | 主表 1176，仅返回 1174–1176 | 1177 `(1)`；1178 `Not applicable for consolidated net income per share.` |

表格中的标记与后续说明均在原件中存在。块没有丢失，但读取主表时不返回这些说明。单独读取说明，也不会反向带回主表。

原因：`reading_groups.py` 第 130–139 行只接纳“paragraph 自身以受支持标记开头”或结构合格的脚注表。上述标记被解析为 `other`，正文另存为 `other` 或 `paragraph`；另有 `(a)` 不在当前数字标记表达式中。不能把单纯标记匹配自动视为财务语义验收，但这几处同一 DOM 容器中的直接脚注结构已可确认。

既有修复没有失效：本轮同时复核 AMD FY2023 客户集中度表 804/805，仍同时返回 `* Less than 10%`；Alphabet 1306/1307 仍返回紧邻 `Note:` 脚注表。证据是 `A1-control` 和 `G3-control`。旧表格形态脚注修复覆盖的结构比上述 split-marker 情形窄。

## 3. Microsoft 两张投资表可以 compact 读取，却无法通过新的有界交接复核

优先级：中，属于确定的接口不一致。证据编号：`M3-951`、`M3-955`。

Microsoft 投资组成表 `block-000951-2eb3b147`（p64）及 `block-000955-924eb6b3`：

- 同一个范围和同一块，`read_context(representation='full')` 返回 `context_too_large`、零块。
- `representation='compact'` 均成功，返回保留全部单元格的约 42 KB 响应。
- 原始 DocumentReader 阅读单元约 112 KB。膨胀主要来自重复单元格字段，而非必须发整章。`query_service.py` 的返回上限是 80,000 字节。
- 当前 `answer_handoff.py` 第 181 行重开原文时固定使用默认 full。即使 Data 已成功取得 compact 内容，交接仍失败。

本轮用实际返回的 compact 内容构造内存 bundle，直接调用有界取证辅助函数；显式容量给到 1,000,000 字节，仍得到 `ValueError: query evidence original context unavailable: context_too_large`。这是离线接口探针，不是模型执行或完整自主运行。完整参数和异常见 JSON。

拟议修复应保持同一原始表内容、单元格和引用，统一表示还原/比较方式；不要用截断表格来规避限制。packet 总容量仍应独立强制执行。

## 4. 索引粒度与尚未验证边界

目前三个运行包都是 28 个 document/part/item 导航节点，没有更细的子标题树。Microsoft Item 1 覆盖 244 块、Item 8 覆盖 525 块；Alphabet Item 8 为 550 块；AMD Item 8 为 441 块。

这说明不能把“选定 Item”当成适当的默认模型输入。但这不是强制整章读取：系统仍有块级 literal search 和 read_context。需要评估的是模型能否用小目录定位、搜到正确块，并获得完整且受限的原始阅读单元。单纯添加更细目录不修复上述列表/脚注断裂。

本轮没有发现上述例子文字丢失；也没有验证全量财务语义、所有单位适用范围、远程脚注、图像内容或 CSS 视觉阅读顺序。此前登记的未读图像仍是明确边界。不能用“原文与块匹配”证明业务分类、指标口径或问题覆盖完整。

**建议当前验收顺序：修复阅读单元（列表和 split 脚注）→ 修复 compact 交接一致性 → 同输入重验 → 再启动不提供人工选段的Data 取材证据 benchmark。** 本记录仅提出修复依据，没有改动实现或标记这些问题已解决。
