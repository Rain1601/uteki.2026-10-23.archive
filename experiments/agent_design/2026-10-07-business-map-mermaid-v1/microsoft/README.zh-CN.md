# Microsoft FY2025 候选业务图

本轮直接阅读官方年报原文，由 Codex 整理候选。未调用付费模型。结果包含 **14 个节点、13 条报告归属边、26 条证据**，所有节点和边均为 `candidate`，没有收入、利润或估算金额。

## 来源与版本

- 报告：Microsoft FY2025 Form 10-K；报告期末 2025-06-30，申报日期 2025-07-30。
- 官方原文：[SEC 10-K](https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630.htm)。
- 本地原件：[source.html](source.html)。复用仓库中已冻结的官方 HTML，未改写其字节。
- 原件 SHA256：`0edfaac937bf7042c8cf7901924ccb9cc291ccfab92f83dd0b689b7912089bf6`。
- 来源复用位置与哈希记录：[source_acquisition.json](source_acquisition.json)。

## 已读范围与表达方式

已阅读 Item 1 的公司概况、Operating Segments、三个分部的主要产品与服务说明，并补读 Distribution, Sales, and Marketing 与 Licensing Options 的相关段落。使用 FY2025 调整后的分部结构：Microsoft 365 商业组件列入 Productivity and Business Processes。

层级为公司 → 报告分部 → 产品与服务组。Intelligent Cloud 下将原文的 Server products and cloud services 拆为 Azure and other cloud services 与 Server products，保持三层可读结构；拆分依据是原文明确列示的两类产品，不是新增报告分部。未把 Microsoft Cloud、AI 或 Copilot 再列为可相加的报告分部。

节点名保留英文官方名称；中文名称在 `metadata.node_labels`，解释用中文。`reported_under` 从子节点指向其报告归属。文字只说明原文支持的业务范围与收费方式，不推断内部组织。

## 证据与验证

- [business_map.json](business_map.json)：复用 `BusinessMap` schema 0.1；含节点、边、未知项及证据定位。
- [evidence.html](evidence.html)：逐条证据、精确原文文本、源 DOM XPath、段落编号与文本哈希。
- 原文块按非空 `p` 与 `div.item-list-element-wrapper` 的 DOM 顺序编号。文本只折叠空白和去除首尾空白；SHA256 对这一规范化文本计算。
- 每个 `exact_quote` 均已检查存在于对应源块与原文规范化文本中。原件哈希、节点/边引用、域契约及真实 HTML 片段 ID 均已核对。[validation.json](validation.json) 保存检查结果。
- [build_extraction.py](build_extraction.py) 仅重建人工整理结果、定位与检查；它没有自动语义提取能力，也不调用模型或网络。

## 未覆盖与限制

本轮不是完整投资研究或财报精编。未系统审查风险因素、全部财务报表和附注、竞争格局、产品价格、地区/客户集中度、承诺及后续事件。企业服务与其他云服务的逐产品计费细节仍保留为未知项。没有自动采纳、数据库入库或生产流程接入。

下一步：先审核节点粒度及每条原文是否支持解释，再由主任务生成 Mermaid 和统一页面；需要量化时，另从明确期间的分部附注提取数值。
