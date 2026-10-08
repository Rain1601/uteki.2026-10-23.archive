# Alphabet 收入交付：r1 独立内容验收

结论：**两个年度收入及其原文引用正确，交付最小性未通过。** 三轮均取得足够数字材料，但最终仍带回布局页眉及另一张地理拆分表。周期为 `attempts_exhausted`；本评测不将模型的 `question_coverage=complete` 当成整个任务通过。

只读检查冻结资料，无 API 调用，未替运行模型选择业务材料。机器核验与完整引用见 [googl-revenue-review.json](googl-revenue-review.json)。本文件及定位示例仅用于事后评测，不得传入运行模型或 Skill。

## 冻结绑定

- [最终周期](../runs/googl-revenue-r1/result.json)：`attempts_exhausted`。
- [最终包](../runs/googl-revenue-r1/attempt-03/review-packet.json)：SHA-256 `7bcb75c8d7ac2eca5b0a0bb4abd2332eba20ecdd47ba2f6e76dedfc57a523ce4`。
- [最终复核](../runs/googl-revenue-r1/attempt-03/review-01/result.json)：`analysis_eligible=false`。
- [冻结 10-K 原件](../datasets/googl/raw/googl-2025-10k.html)：SHA-256 `c2f6301004f35411a20611c14ff01d80a85c0bcbab6053c80d8cc7f6fc747161`。
- 已校验数据集全部 manifest 文件哈希；最终 query/ref、review manifest 与周期引用一致，review input 与包逐字节一致。

## 数值与出处核验

| 项目 | FY2025 | FY2024 |
|---|---:|---:|
| 原始收入 | 402,836 百万美元 | 350,018 百万美元 |
| 标准化 USD | 402,836,000,000 | 350,018,000,000 |
| XBRL 期间 | 2025-01-01 至 2025-12-31 | 2024-01-01 至 2024-12-31 |
| 实际所选记录出处 | 合并损益表，753 | 地理拆分表的 Total revenues，924 |
| 单元格（从 0 开始） | row 3, column 16 | row 8, column 16 |
| 块内字符范围（左闭右开） | 63–70 | 278–285 |

逐条从原 HTML 重读对应 inline XBRL：标准概念均为 `us-gaap:Revenues`，发行人为 `0001652044`，scale 均为 6，单位均为 `iso4217:USD`，日期及无维度上下文与记录一致。金额转换正确。FY2024 引用的是地理表**总额**，不是美国或其他地区单项；该总额包括原表中的套期损益行，不存在漏加地域项的计算问题。

8 个交付原文块的文字及两张完整表的所有单元格均与冻结 HTML DOM、冻结 blocks 一致；事实引用全部落在实际原文，数值的字符和单元格坐标准确。损益表自身同时包含两年收入、年度列及完整 Revenues 行，另有公司名称、CONSOLIDATED STATEMENTS OF INCOME 标题与百万单位行。

因此，公司的实际合并损益表所报收入、年度和单位已充分。此处没有要求附带整套 GAAP 或抵销政策。若后续报告进一步声称具体合并边界、抵销政策或收入排除哪些税费，则需额外政策原文；不能从 `reported_consolidated` 标签或 `us-gaap:` 前缀直接推出。

## 为什么还没有通过

最终包是 **8 块原文、2 条数值记录、4 条 source_block 事实**。两类多余材料来源不同：

1. **工程自动扩展的布局页眉。** 749 是 `running_header` 表，内容为 `Table of ContentsAlphabet Inc.`。模型没有在最终正文选择中选它，但原表上下文仍将它带回。它没有业务或会计限定作用。本次不将它宽松改判为有用上下文，也不要求模型反复删除无法通过选择控制的内容；应由版本化工程规则处理。
2. **记录选择导致的额外表格。** FY2024 数值记录的原始引用一直指向地理表 924，因此其引言 923 和区域定义脚注 925 也随原表上下文交付。由于损益表已同时支持两个年度，这张额外地理表可以避免。不能删除记录出处却保留该记录；系统应自行检查已查询记录的原始引用，再选择覆盖问题所需的精简原始披露。

单张完整损益表包含其他利润行，可由原表原子读取解释。这个理由不能无限推广到另一张已经不必要的表。地理脚注说明 EMEA/APAC/Other Americas，与公司总收入的口径无直接关系。第三轮 reviewer 虽然 `revision_requests=[]`，仍将页眉和区域脚注判为 irrelevant；程序据此不放行，属于正确保护。

## 三轮与运行职责核查

三轮收入金额相同，均为 `evidence_ready`；reviewer 都认为问题数字完整，却因多余原文而没有接受。第二、三轮调整了正文选择，但继续选择相同的 FY2024 地理表记录。因此问题没有消失。

第三轮 turn005 给出的理由是“prior review verified them against the income statement”。这只是 reviewer 用损益表交叉验证了金额，**不会改变原记录的出处**。`select_evidence` 选择新的正文也不会覆盖 `select_records` 所选记录携带的出处。

调用配置仅提供公司、冻结来源、问题、模型和资源限制；plan、query、read、select_records、select_evidence 均见真实模型轨迹，`plan_origin=model`。未发现 Codex 在调用参数中提供章节或块选材。重试使用系统 reviewer 的历史反馈；这是有反馈的连续修订，不是三次互相独立的盲测。本次离线评价发生于封存后，不参与运行答案生成。

## 可迁移的协议问题

查询收据中的每个 record 有 `evidence_ids`、XBRL origin 和文件位置索引，但没有直接展开 block/table/cell 定位。`source_leads` 列出候选块，却未连接到具体 record。完整 citation 已保存在 evidence artifacts，模型可以分页再读；然而第三轮选择前的默认 evidence_index 页只显示前 8 个 record，完整 20 项中的 citation 不直接可见。

另一个信息差是修订只收到 reviewer 的 assessment。reviewer 的引用可以是交叉验证材料，不等于原包中 record 的不可变出处。现有机制理论上能找齐映射，但不够直接，容易把“值已核对”误解成“原始出处已改变”。

建议通用修复：解释 record 出处不可由正文选择覆盖；在 query 返回或可读取的紧凑映射中，展示每条 record evidence ID 对应的原始 citation block、cell、quote。缩小材料包时，需要重新选择满足同一条件的原始披露。映射必须由当前数据自动生成，不预置公司、正确 ID 或目标表格。

## 后续授权修复（不改变 r1 判定）

独立审查结束后，按主任务授权实现了 `record_origins` 通用映射。它由本次查询生成，默认展示记录 ID、原出处、短引用及完整引用读取入口，并在随后阅读步骤中保留。已有 cell/字符坐标直接保留；原数据只有 fact_dom_path 时保留该坐标，不编造单元格。每页最多 12KB、100 项，更多内容通过精确游标读取。映射是导航，不增加原文阅读完成度。

执行提示更新为 v12、query Skill 更新为 v11，明确正文选择和 reviewer 交叉证据不会重写原记录出处。36 项相关离线检查通过，包括同值不同出处的 synthetic 选择，以及 Google 全部 10 个查询候选在默认输入中的出处核验。没有模型调用，没有修改冻结 r1 或数据集；代码通过不代表新的模型执行已经通过。

下一步：通用来源映射及布局扩展修复后，由系统重新选择与交付，再独立验收新运行。此 r1 的失败状态保留。
