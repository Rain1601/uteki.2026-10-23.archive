# 第二轮记录复核的独立语义抽查

本报告只读检查 `data/company_workspace/record_review/msft-fy2025/run-02` 的三个已接受 `assessment.json`、最终 `result.json` 及其 `inputs-03` 来源上下文。没有修改原响应或候选记录，没有额外调用模型。首轮报告保持不变。

## 实际覆盖

第二轮三个批次分别接受 24、24、21 条意见，最终状态为 `reviewed`，69/69 条全部判为 `supported`。与首轮已接受的 33 条 record ID 比较：交集为 0，并集为 102。

因此，102 条指定候选记录均已有通过结构、覆盖和引用校验的 LLM 复核意见。**这不等于 102 条全字段得到独立验真，更不等于全文提取无遗漏。** 本报告是针对重点语义问题的独立抽查，不是 Gold 标注或自动采纳决定。

## 已改善的检查

### 现金流出与正向支付金额

`packet-001` 的三个资本支出意见现在明确区分了表中括号流出和 `capex_cash_payments` 的正向支付金额。例如 `obs-3032e8ac53e4015e31bcf1d9` 说明 2025 年 64,551 百万美元的括号表示现金流出，记录按正数保存符合指标定义，引用为连续原文：

> Additions to property and equipment (64,551 ) (44,477 ) (28,107 )

2024 年 `obs-1562b9f7e6f080b3bb4c8d1f` 和 2023 年 `obs-aad5727a15ad1f33e86843d4` 也给出相同口径说明。这解决了首轮意见未解释符号转换的问题；不意味着该指标可替代所有形式的资本投资。

### 美国地区收入的脚注限定

`packet-002` 对美国地区收入的三条记录提及脚注 (a)。例如 `obs-9d00133e48defbb230bee2f4` 同时引用地理收入表的美国行，以及 `block-001221-73695690`：

> Includes billings to OEMs and certain multinational organizations because of the nature of these businesses and the impracticability of determining the geographic source of the revenue.

理由明确解释该限定语适用于记录。这支持“按披露口径归属的美国收入”理解，不能简单等同为终端客户实际所在地收入。该脚注讲的是包含特定开票归属，不是排除这些收入。

### 非连续引用问题

抽查 `packet-001` 的净利润、经营现金流、资本支出和 More Personal Computing 记录，第二轮改用完整连续表行或合法原文片段。例如 2024 年净利润引用保留了同一行中的其他年份数字，没有再将行名与第二列金额跳列拼接。三个批次均已形成通过严格引用校验的接受产物；无需改写首轮被拒原响应。

## 仍未充分解释的语义

### 分部历史重述和费用分摊

`packet-001` 中 More Personal Computing 的六条收入/营业利润意见仍主要表述“对应行和年度数值一致”。例如 `obs-b2476370393460b74b70a82d` 确认 2024 年收入 50,838 百万美元，但未解释当前报告的历史重述口径；`obs-281f43cdb444f0468b258378` 对 2024 年营业利润 11,959 百万美元也未说明分部费用分摊限制。各条 `qualifiers` 仍为 `supported`，`limitations` 为空。

输入已有重述说明及相关分摊上下文，模型却没有在这些记录的理由或引用中落实。批次级未解析 Note 引用说明保留了边界，但不能代替逐记录对已提供限定语的解释。本次没有据此断言数值错误，也没有将意见改判；遗留问题是 `supported` 的语义论证不足。

### Microsoft Cloud 与产品收入重叠

`packet-003` 中 Microsoft Cloud 的三个记录为：

- `obs-f8e00a77890bcdeb3edd38a2`：2025 年 168.9 billion USD。
- `obs-0b93130590eaf7825ad22d22`：2024 年 137.7 billion USD。
- `obs-34467d4558b7878f6fb37d22`：2023 年 111.6 billion USD。

其意见引用了业务构成和金额的完整句子，解释了金额、期间及维度，但没有引用或解释同一来源段落 `block-001227-3bdf0315` 紧后的句子：

> These amounts are included in Microsoft 365 Commercial products and cloud services, Server products and cloud services, LinkedIn, and Dynamics products and cloud services in the table above.

该句已交付模型，明确这些金额包含于前表产品和服务收入。三个意见的 `qualifiers` 全为 `supported`，逐记录限制为空，未明确指出不能再与前表收入相加。因此云收入数值及业务构成获得了一定支持，重叠/不可加总限定尚未充分体现在复核意见中。

### 不透明维度的剩余边界

第二轮部分理由比首轮更明确地对照了 XBRL 成员、期间和可见行名，这是进步。但批次级限制仍声明维度为不透明分类法成员、未解释为通用业务名称，且 Note 18/Note 1 的交叉引用未全部解析。不能将本次逐表对照扩展为通用维度映射能力或跨期可比性已经验证。

## 使用结论

可以报告“102/102 条指定记录完成 LLM 复核意见覆盖，结构和引用校验通过；所有意见均为 supported，候选事实未修改、未自动采纳”。同时应保留以上重述、分摊、云收入重叠和交叉引用限制，不能报告“全部财务语义已验证正确”。本抽查没有评估全文遗漏率，也没有核验真实账单。
