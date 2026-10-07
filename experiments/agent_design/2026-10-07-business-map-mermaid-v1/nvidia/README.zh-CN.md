# NVIDIA FY2025 候选业务图

本轮由 Codex 阅读官方年报原文，整理 **16 个节点、24 条关系、20 条证据**。没有调用付费模型。所有节点与关系均为 `candidate`，没有生成收入、利润或估算金额。

## 来源与版本

- 报告：NVIDIA FY2025 Annual Report 的 Form 10-K 部分，报告期末 **2025-01-26**；不是 FY2026，也不是公历 2025 全年。
- 官方发现页：[NVIDIA Annual Reports and Proxies](https://investor.nvidia.com/financial-info/annual-reports-and-proxies/default.aspx) 的 2025 条目。
- 官方原件：[FY2025 PDF](https://s201.q4cdn.com/141608511/files/doc_financials/2025/annual/NVIDIA-2025-Annual-Report.pdf)，本地保存为 [source.pdf](source.pdf)，181 个 PDF 实际页面。
- PDF SHA256：`757b344ab62ba282f6e44e0702e8ce5f190d88fb23b5e0a2beaf4cb277a395cc`。
- 对应 [SEC FY2025 10-K HTML](https://www.sec.gov/Archives/edgar/data/1045810/000104581025000023/nvda-20250126.htm) 下载返回 HTTP 403，因此使用官方 IR 页直接链接的同年度 PDF。未改用第三方内容。
- [source.html](source.html) 是 **PDF 文本派生视图，不是官方原始 HTML**。`pdftotext -layout` 输出保存在 [source.txt](source.txt)；HTML 只做空白规范化、转义和定位标记。原件与派生文件各自的哈希见 [source_acquisition.json](source_acquisition.json)。

## 已读范围

已阅读并目视核对下列 PDF 页及原印页码：

| PDF 实际页号（从 1 起） | PDF 页索引（从 0 起） | 原印页 | 范围 |
|---:|---:|---:|---|
| 97 | 96 | 5 | Our Businesses、Our Markets、Data Center |
| 98 | 97 | 6 | Data Center 续页、Gaming、Professional Visualization |
| 99 | 98 | 7 | Automotive、相关平台说明 |
| 149 | 148 | 57 | Note 1：收入类型与产品销售 |
| 150 | 149 | 58 | Note 1：软件许可与云服务 |

整本 PDF 被保留用于追溯；这不表示整本 181 页已完成语义审查。派生文本不自动拼接跨页段落，所用证据都保留其实际页位置。

## 分部、产品与市场

年报只有两个报告分部：**Compute & Networking** 和 **Graphics**。公司 → 报告分部 → 产品组使用 `reported_under` 关系，子节点指向报告归属。

**Data Center、Gaming、Professional Visualization、Automotive 是四个市场维度。** 现有域契约没有 market 枚举，因此这四个节点的 `kind` 使用 `business`，同时以 `metadata.node_roles: market` 和文字标签明确身份。所有指向市场的边均为 `supports`，表示产品或平台服务该市场，不代表报告归属，也不是完整收入勾稽。

汽车自动驾驶平台列入 Compute & Networking；汽车信息娱乐平台列入 Graphics。Omniverse 与汽车市场的关系来自原文的自动驾驶仿真说明。图不会把整个 Automotive 市场误归入单一报告分部。

本轮独立代理复核后修正两处标签范围：游戏产品节点改为“游戏产品：GeForce、云游戏与主机”，使名称覆盖已列出的主机 SoC 和开发服务；Omniverse 节点改为“Omniverse / Omniverse Enterprise”（中文“Omniverse 平台”），赚钱方式明确为“Omniverse 平台以企业订阅变现，对个人免费”，避免把个人免费误读为 Enterprise 免费。节点 ID、关系及证据保持不变。

## 证据与检查

- [business_map.json](business_map.json)：兼容 `BusinessMap` schema 0.1。英文官方名称及中文标签分别保留。
- [evidence.html](evidence.html)：精确源文块、候选支持说明、PDF 实际页/原印页、文本哈希、PDF 页链接与派生文本片段链接。
- 证据段落是 PDF 各页按空行切分的非空文本块，按全文件顺序编号；只折叠空白后计算 SHA256。
- 已检查所有 `exact_quote` 存在于对应 PDF 提取页文本中；所有节点/边有有效证据引用，只有两个 `reportable_segment`，市场边没有误用报告归属。[validation.json](validation.json) 保存检查结果。
- [build_extraction.py](build_extraction.py) 仅包装本轮人工整理内容和定位，不代表通用业务语义提取程序。

## 未覆盖与限制

未系统审查整份风险因素、供应链和制造、竞争、出口限制、全部附注、地区/客户集中度或后续事件。公司级收入确认政策不等于逐产品收费表；DRIVE、Jetson、汽车信息娱乐的具体收费方式保留为未知。没有推算市场到分部的金额映射，也没有声称独立人工复核、采纳、数据库入库或生产接入。

下一步：先审核市场维度与报告分部的视觉区分，再由主任务生成 Mermaid 和统一页面；如需数字，另行核对同一期间的分部及市场披露。
