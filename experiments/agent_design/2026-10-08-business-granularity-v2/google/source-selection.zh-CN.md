# Google FY2025：完整 Business 原文输入

本轮为 Alphabet Inc. 的 FY2025 官方 HTML 10-K 选取**完整 Item 1. Business**，不是只选 Google Cloud。输入只来自原始报告和来源身份元数据，没有加载旧候选图、人工答案或模型审阅。

- [冻结输入](source_packet.json)：93 块，68,886 bytes；SHA-256 `661ed7511e6e62988829875a399d2186a07580de37234d78dbd6b1a216ba8a38`。
- 91 块连续正文：ordinal **61–151**。起点是 `ITEM 1.BUSINESS`，终止边界为 ordinal **152** 的 `ITEM 1A.RISK FACTORS`（不纳入）。
- 2 块封面身份材料：ordinal **11** 的年度说明，ordinal **17** 的 `Alphabet Inc.`。公司 ID `sec-0001652044`，报告 ID `googl-2025-10k`，期末 `2025-12-31`。
- 原件与旧索引的每一块都重新与原始 DOM 比较。起止边界之间的全部 DOM 文字与 91 块拼接一致，没有截断或过滤。
- Competition、Culture and Workforce、Government Regulation、Intellectual Property、Available Information 均保留；页码与 6 个导航表块也保留。导航表以原文块表达，本任务未添加财务表格或金额拆分。
- Item 1 内提及的 Risk Factors、MD&A、外部网站与其他材料未加载。模型可以记录这些引用和缺口，不能称为已读。

原文为[SEC 官方 10-K](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000018/goog-20251231.htm)，使用已冻结本地原件；SHA-256 `c2f6301004f35411a20611c14ff01d80a85c0bcbab6053c80d8cc7f6fc747161`。本轮没有重新网络获取。身份与本地获取记录已交叉核对，见 [source_manifest.json](source_manifest.json)。

## 与 Microsoft 输入的规模对照

Google 共 93 块、23,762 个原文字符；既有 Microsoft Operating Segments 是 103 块、20,077 个字符。Google 原文字符多约 **18.4%**，无需为了大小缩减成更小的章节。

两家公司使用同一 complete_report_subsection 协议，但报告自身结构不同：Google 是完整 Item 1，Microsoft 既有包是完整 Operating Segments 小节。因此可以比较规则迁移，不能把节点数或 token 总量直接当作模型质量排名。费用须按最终请求、输出上限及有界修订路径再预检；块数和原文字数不能保证全流程不超过任务预算。

## 实际核查

[verification.json](verification.json)保留原件/索引/输入 hash、全部 ordinal、原始 DOM 边界、大小及读取来源。生产 `verify_packet(... contract_version='business-draft-v2')` 通过；每块包含独立文本 hash 和 DOM 路径。

准备脚本复用此前 Microsoft 完整小节准备中的不可变文件写入与 JSON 序列化，以及同一官方来源 manifest / source packet 约定。Google 的选段只写在本实验，没有加入生产公司特判。旧 packets、原件和索引没有改写。本轮模型调用：0。

复核：

```sh
PYTHONPATH=src .venv/bin/python experiments/agent_design/2026-10-08-business-granularity-v2/google/prepare_input.py
```
