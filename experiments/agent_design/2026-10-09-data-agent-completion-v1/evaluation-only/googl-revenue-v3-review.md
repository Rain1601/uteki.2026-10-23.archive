# Alphabet 收入 v3 独立验收

结论：**通过原问题验收。** `googl-revenue-r2` 第一轮交付同一张合并损益表的两个年度收入，4 块原文足够且没有之前的页眉和地理表冗余。本结论基于冻结 HTML、原始 XBRL 和精确引用的独立核对，不以模型自审代替判断。

| 核对项 | FY2025 | FY2024 |
|---|---:|---:|
| 原表收入，百万美元 | 402,836 | 350,018 |
| 标准化美元 | 402,836,000,000 | 350,018,000,000 |
| 完整期间 | 2025-01-01 至 2025-12-31 | 2024-01-01 至 2024-12-31 |
| 同表单元格（从 0 开始） | row 3, column 16 | row 3, column 10 |
| 块内字符范围（左闭右开） | 63–70 | 54–61 |

两处均来自 `block-000753-53762a3b` 的 Revenues 行。重新从原 DOM 核对 inline XBRL：概念 `us-gaap:Revenues`、发行人 `0001652044`、无分部/产品维度、scale=6、`iso4217:USD`、完整年度日期均与记录一致。不是产品或地域单项，未漏掉套期损益，也没有执行不必要的加总。

原表全部单元格与冻结 blocks 一致；数值对应原文字符及单元格准确。交付保留公司名、`CONSOLIDATED STATEMENTS OF INCOME`、百万单位行和原表。原表有其他利润行，但同表保持单位、年份、行列关系，符合当前原子表格交付方式。没有第二张无必要的表。

本次是 2 个 record facts、4 个 source_block facts；去重后的原始正文仍为 4 块，总计 729 字符。前次 r1 是 8 块，原因既有工程自动带回页眉，也有模型选了地理表中的 FY2024 同值记录。此次两处问题均未出现在最终包。

关键变化可核验：模型 turn006 的输入直接显示 10 个候选的 `record_origins`。模型选择 FY2024 的损益表 occurrence `obs-b5db8f0949bc70a4e8bc553f`，不再选地理表 occurrence；理由明确为两年均引用已读损益表，避免重复披露。最终包的两条 citation 也确实绑定同一原表，没有通过正文覆盖或改写旧记录出处。

会计口径由原题要求的“实际、公司整体、合并报表所报收入”限定；原标题明确 consolidated。未把 `us-gaap:` 标签扩大为完整 GAAP 政策证明，也未断言子公司范围、内部抵销或税费排除细节。若后续报告增加这些断言，需要取得相应原文，本次不替这些内容验收。

运行职责边界核对：调用参数只限定问题、公司、来源和资源，真实轨迹由模型完成 plan/query/read/select；Codex 在封存后审查，没有向此次运行提供正确记录 ID、章节或块清单。通用程序负责来源映射及附件组装。一次成功说明该例已跑通，不代表所有后续公司或任务均有同等表现。

冻结绑定：

- [最终周期](../runs/googl-revenue-r2/result.json)：`reviewed_data_ready`。
- [最终包](../runs/googl-revenue-r2/attempt-01/review-packet.json)：`selected-originals-v3`，SHA-256 `e2a821601e92026dd1989d765d953bfa338d356dbca00276d836f141d68ec22d`。
- [最终复核](../runs/googl-revenue-r2/attempt-01/review-01/result.json)：`analysis_eligible=true`。
- 原件 SHA-256：`c2f6301004f35411a20611c14ff01d80a85c0bcbab6053c80d8cc7f6fc747161`。
- [机器记录](googl-revenue-v3-review.json)：最终 query/review 引用与哈希、原 DOM 定位及各项核验。

已核验数据集全部 manifest 文件哈希、最终 review manifest、query 绑定，包与 reviewer input 逐字节相同。无 API 调用，未修改原件、运行结果或旧审查。下一步等待同批业务材料任务封存，再作独立内容验收。
