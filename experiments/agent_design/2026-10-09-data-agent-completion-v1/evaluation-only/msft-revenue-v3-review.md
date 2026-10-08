# Microsoft 收入 v3 独立验收

结论：**通过原问题的公司整体损益表所报收入交付验收。** 新运行 `msft-revenue-r4` 第一轮取得 2 条原始数值记录、3 块报表原文，没有 query/program gap。已独立核对冻结 HTML 与 XBRL，并非只采信模型复核。

| 核对项 | FY2025 | FY2024 |
|---|---:|---:|
| 原表收入，百万美元 | 281,724 | 245,122 |
| 标准化美元 | 281,724,000,000 | 245,122,000,000 |
| 完整期间 | 2024-07-01 至 2025-06-30 | 2023-07-01 至 2024-06-30 |
| 原表单元格（从 0 开始） | row 11, column 3 | row 11, column 7 |
| 原文字符范围（左闭右开） | 175–182 | 183–190 |

两条记录均引用 `block-000781-9ee5633d` 的 Total revenue 行，原 HTML 路径为 `/html/body/div[150]/table`。单位来自表内 `In millions`，年度来自 `Year Ended June 30` 及列头。发行人、无维度、标准收入概念、scale=6、USD 单位、期间与两处数值均重新核对 XBRL。全表单元格与原 DOM 一致，引用字符位置准确。

3 块分别是 Item 8 财务报表标题、INCOME STATEMENTS 标题和原表。两个标题提供有限且合理的来源上下文；整表保留原列和单位，未附带第二张无关表或其他章节。包中仅有 2 个 record facts，没有额外 source_block facts；原始正文由系统根据所选记录的出处附加，仍完整交给复核。

会计口径通过范围是“公司整体、实际、损益表所报总收入”。未交付 GAAP、子公司边界、内部交易抵销政策原文；若后续报告明确作这些扩展断言，需要另取对应原文。不能从适配器标签自动扩大结论。本题无需机械覆盖更丰富的 gold 示例。

运行边界：调用配置只限定公司、来源、问题和资源，plan/query/select_records 由模型执行；原文附加是通用程序操作，没有 Codex 运行选材。该点依照封存轨迹核验，不表示模型读遍了报表，也不表示所有材料的语义解析均已验收。

证据与绑定：

- [最终周期](../runs/msft-revenue-r4/result.json)：`reviewed_data_ready`。
- [最终包](../runs/msft-revenue-r4/attempt-01/review-packet.json)：`selected-originals-v3`，SHA-256 `1d19cf54605de0256ff9965d6aaa9b15a18768b902d42b5dcaaeb2b884401b5c`。
- [最终复核](../runs/msft-revenue-r4/attempt-01/review-01/result.json)：`analysis_eligible=true`。
- 原件 SHA-256：`0edfaac937bf7042c8cf7901924ccb9cc291ccfab92f83dd0b689b7912089bf6`。
- [机器记录](msft-revenue-v3-review.json)：包含最终 query/review 引用、manifest 哈希、原 DOM 定位及逐项检查。

已验证数据集全部 manifest 文件哈希、最终 review manifest、query 绑定，以及包与 reviewer input 逐字节相同。无 API 调用，未修改原数据、旧运行或旧审查。下一步继续核验同批 Google 收入 v3 的封存结果。
