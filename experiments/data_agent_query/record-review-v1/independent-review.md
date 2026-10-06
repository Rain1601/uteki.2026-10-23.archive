# 首轮记录复核的独立语义抽查

本记录针对 `data/company_workspace/record_review/msft-fy2025/run-01` 的已接受意见与被拒原响应。只读检查，没有修改响应、候选事实或原件，没有发起网络或模型调用。

首轮请求复核 102 条记录，其中 33 条的模型意见通过结构、逐记录覆盖和原文引用校验。本次对这些意见及部分被拒响应进行独立语义抽查，**不是 Gold 标注，不是 33 条全字段验真，也不代表其余记录已完成复核**。不包含第二轮结果。

## 已观察到的结果

接受产物为 `packet-001`、`packet-002`、`packet-005`、`packet-006`、`packet-007` 的 `assessment.json`，合计 33 条，均判为 `supported`。抽查的数字、年度及可见行名与输入来源一致，但部分字段的理由与引用不足以展示完整的语义检查过程。

### 历史重述说明未落实到逐记录意见

`packet-007` 输入包含 `block-001182-b3eedf85`：

> We have recast certain prior period amounts to conform to the way we internally manage and monitor our business. Refer to Note 1 – Accounting Policies for further information.

例如 `obs-ea3fda8937394a153cf46072` 的意见确认 Productivity and Business Processes 2024 财年收入为 106,820 百万美元，引用仅为 `106,820`，所有子检查均为 `supported`。意见未解释该历史数字属于当前报告重述后的口径，也未引用重述说明。

这不是已证实的数值错误，但不能据此声称重述口径已经得到充分复核。输入已经包含上述说明，因此这里主要是模型意见深度不足，而非该说明未交付。

### 不透明维度的验证边界不清晰

`packet-007` 的来源限制写明“维度 ID 为不透明标识，未将其解释为业务分部名称；仅依据表格行标签进行核对”。与此同时，12 条分部记录的 `entity_dimensions` 均为 `supported`。

例如 `obs-c9967bda56a0a08e2bdc7acf` 原始维度为 `us-gaap:StatementBusinessSegmentsAxis = msft:ProductivityAndBusinessProcessesMember`。其理由指出可见表中该分部的收入为 120,810，引用仅为 `120,810`。这支持对应表内数值的核对，但没有充分展示模型如何验证原始维度与可见分部行的对应关系。不能将该意见扩展为可复用的维度名称映射或分类法解释能力。

### 现金流符号口径未展开说明

被拒的 `packet-004/attempt-2-response.json` 中，资本支出意见仅表示金额一致。例如 `obs-1562b9f7e6f080b3bb4c8d1f` 对应 2024 财年的 44,477 百万美元，模型将 `value_unit_scale_sign` 判为 `supported`。

原表的 Additions to property and equipment 使用括号表示现金流出，而候选指标 `capex_cash_payments` 使用正向支付金额。该口径可以合理成立，但意见未解释表中流出符号与候选正向 payments 的转换依据。这里未断言候选值错误；它是需要明确说明的语义检查点。该批原响应也未通过引用校验，不能计入已接受复核。

### 被拒引用确实存在非连续拼接

`packet-003/attempt-2-response.json` 对 `obs-d5467d8c1e6ca1d1b2dfce48` 引用：

> Net income $ 88,136

实际来源块 `block-000787-238b523c` 的连续文字为：

> Net income $ 101,832 $ 88,136 $ 72,361

模型跳过第一年份列，把行名与第二年份数值拼接为不存在的连续原文。这不是简单空白差异。

`packet-008/attempt-1-response.json` 对 `obs-8db30fb8b8299551605a9c37` 引用 `More Personal Computing Operating Income $ 14,166`，也跳过了分部名称与营业利润行之间的收入、成本和费用内容。严格的连续原文校验拒绝这些响应是正确的；不能手改原响应或放宽校验使其通过。

## 后续复核要求与限制

- 引用可以仅取原文中的目标数字，并额外引用完整行、表头或限定句；不得跳列、跳行拼成单条 quote。
- 对已提供的重述、分摊、维度、金额重叠和符号说明，应给出具体字段判断及可回查引用；缺失的 Note 交叉引用继续明确保留。
- 结构和 exact quote 校验可以阻止伪造引用与覆盖漏项，但不能自动证明模型真正理解了每个字段。
- 本次未进行完整原件逐页复核、独立重建全部事实、跨版本重述核对或真实账单核验。单个 `supported` 意见不触发事实修改或采纳；候选状态保持不变。
