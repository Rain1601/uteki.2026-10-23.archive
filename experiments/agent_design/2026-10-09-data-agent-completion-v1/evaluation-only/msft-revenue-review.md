# Microsoft 收入交付：独立内容验收

结论：**这份 3 块原文、2 条数值记录，足以交付两个年度的公司损益表所报总收入。** Item 8 短标题属于合理来源上下文，不应因此要求重跑。通过范围限定为“公司整体损益表所报口径”；不能顺带声称已交付 US GAAP、子公司合并范围或内部交易抵销政策的原文证明。

本记录仅供 Codex 离线评测。不得作为运行模型、检索计划或 Skill 的输入。无模型调用、无联网、未修改原件与运行产物。

## 核对对象与原件

- 冻结包：[attempt-03/review-packet.json](../runs/msft-revenue-r2/attempt-03/review-packet.json)。问题：获取 Microsoft FY2025 与 FY2024 公司总收入，保留单位、期间、会计口径及原文出处。
- 完整包 SHA-256：`c52a44eb606fbb6bbed00af5daac6d09a9cae3fa9b28c604041247bdbb12c091`。
- 原件：[Microsoft FY2025 10-K HTML](../datasets/msft/raw/msft-2025-10k.html)，SHA-256 `0edfaac937bf7042c8cf7901924ccb9cc291ccfab92f83dd0b689b7912089bf6`。
- 数据集 manifest SHA-256：`d5f4c63ae4a8c8524610d2b51cfde10a52de4fd3a47223d049bc7f6cc41c509b`；与包的绑定一致，全部列示文件哈希重新校验通过。
- 机器记录：[msft-revenue-review.json](msft-revenue-review.json)。包括原 DOM 路径、XBRL context、单元格、字符坐标与各项验证。

最终接受周期 [msft-revenue-r3](../runs/msft-revenue-r3/result.json) 为 `reviewed_data_ready`，复用同一个 r2/attempt-03 query。已确认 r3/attempt-01 的 review-packet、最终 reviewer input 与上述原包逐字节一致，最终 query 引用及 review manifest 哈希相符。这次独立验收仍绑定原包哈希，不将重审冒充新检索或新的独立抽取。

## 数值、期间与单位

原件第 50 页，`/html/body/div[150]/table`，块 `block-000781-9ee5633d`：

| 项目 | FY2025 | FY2024 |
|---|---:|---:|
| 原表 Total revenue | 281,724 | 245,122 |
| 原表单位 | 百万美元 | 百万美元 |
| 标准化 USD | 281,724,000,000 | 245,122,000,000 |
| XBRL 期间 | 2024-07-01 至 2025-06-30 | 2023-07-01 至 2024-06-30 |
| 原表单元格（从 0 开始） | row 11, column 3 | row 11, column 7 |
| 块内字符范围（左闭右开） | 175–182 | 183–190 |

逐项重新读取冻结 HTML：两处 inline XBRL 的 scale 均为 6，单位均为 `iso4217:USD`，发行人均为 `0000789019`，期间与记录一致，均无产品或分部维度。概念均为 `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`。数值来自 **Total revenue** 行，没有把 Product 单项或分部收入当成公司总额。

3 块正文全部与对应原 DOM 文本一致；紧凑表格解码后的所有单元格与原 DOM 表格、冻结 blocks 一致。字符坐标指向准确金额。原表包含 `In millions, except per share amounts` 与 `Year Ended June 30, 2025 2024 2023`，单位和年度没有依赖孤立数字猜测。

## 会计口径：本次必须与可选增强

**本次已满足的最低语义**是公司整体、实际、损益表所报的收入，而不是产品收入、某个分部、管理层调整值或预测值。原 Item 8、INCOME STATEMENTS、Total revenue 行，以及发行人无维度 XBRL 相互一致，能支撑上述有限口径。两条记录的 `reported_consolidated` 在这里应按这一有限含义使用。

**不能由该包直接声称的细节**包括 US GAAP 编制政策、Microsoft 与子公司的具体合并边界、内部交易抵销。适配器在无维度时自动写入 `reported_consolidated`，这条程序规则本身不能证明全部会计政策；`us-gaap:` 概念前缀同样不能替代报表编制政策原文。

冻结验收参考中的 accounting-scope 提供了更丰富的支持集，不应机械扩大原问题。若最终只答“公司损益表所报总收入”，不要求附带完整政策。如果最终写出“按 US GAAP、含子公司且抵销内部交易”，这些就成为必须补证的实质性断言。本次没有给这些扩展断言通过。

为核对缺口确实存在于源文件，而非凭常识补充，离线查看了同源 `block-000813-86814fe3` 的 GAAP 句和 `block-000815-a9d394c1` 的合并及抵销句，并复核原 DOM。它们没有出现在当前交付包。它们仅是评测中的可替代支持示例，不能注入运行模型作为指定检索答案。原问题未讨论分部重编，不要求额外提供重编说明。

## 3 块是否合理

| 原文块 | 长度 | 独立判断 |
|---|---:|---|
| 779：ITEM 8. FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA | 51 字符 | 合理来源上下文。明确它属于法定财务报表部分，有助区别其他章节的摘要表；不是另一业务分支，也未引入新的分析任务。 |
| 780：INCOME STATEMENTS | 17 字符 | 合理报表类型上下文。 |
| 781：完整损益表 | 889 字符 | 必要数值与单位、年份所在原表。保留同表其他行符合当前原表原子读取契约；不是字节层面的最小裁剪。 |

两条数值记录分别对应两个年度，没有重复数值记录混入。包中另外还有 2 条 `source_block` 事实，分别承载已读标题和原表；因此 JSON 的 `facts` 总数是 4，不能误说成仅有 2 个 facts。补充原文按块去重后仍是 3 块。

完整表格包含成本、利润及 FY2023 列，在未来具备可信行级切片时可以进一步收窄。但当前保留原表有明确作用：保留行列归属、单位、年度与精确核对，不构成本次阻断。原表收入行没有被删去的编号脚注；紧邻的 `Refer to accompanying notes` 不等于必须把整套附注都交付。

上一模型把 779 判断为 redundant、把原表判断为 necessary。本次独立判断与其前一项不同：**最小充分不是把所有可省略的短来源标题都变成失败条件。** 该标题提供来源类别，增加 51 字符，可接受为 supporting_context。反过来，不能因标题合理就放宽对缺失关键单位、期间或会计断言的检查。

下一步：沿用这份独立评测的断言边界检查最终报告；若报告进一步解释会计政策，系统应自主检索对应证据，再交付。不要把这里的具体块号加入通用运行规则。
