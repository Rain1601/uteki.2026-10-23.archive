# 这份 10-K 被程序解析成的结构

材料：Alphabet FY2025 10-K。这里显示确定性解析结果；目录、文本块及 HTML 表格不等于模型已理解或完整抽取。
[返回验收样本](/Users/bytedance/Documents/ChatGPT/uteki/docs/design/data-agent-acceptance/README.zh-CN.md)

| 原文块类型 | 数量 |
| --- | ---: |
| table | 185 |
| heading_candidate | 273 |
| paragraph | 622 |
| other | 11 |
| page_marker | 97 |
| list_item | 148 |
| image | 2 |

**185 个 table 是 HTML 网格数量，不是财务表数量。** 包含 97 个页眉表、1 个目录表、4 个空表；其余 83 个非空 HTML 表尚未逐一完成业务类型验收。273 个 heading_candidate 是标题候选，下面目录实际上只有 28 个节点。图片 2 张仅保留引用。

[全部 1,338 个解析块](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/indexes/googl-2025-10k/blocks.jsonl)
 · [冻结 HTML 原件](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/raw/googl-2025-10k.html)

## 完整目录节点

| 类型 | 标题 | 报告内页码 | 原文块范围 |
| --- | --- | ---: | --- |
| document | googl-2025-10k | 2 | block-000001-e3b0c442 → block-001338-64932fc7 |
| part | PART I | 3 | block-000060-495768bd → block-000354-a3014a36 |
| item | BUSINESS | 3 | block-000061-5c0c0c66 → block-000149-24a569d3 |
| item | RISK FACTORS | 9 | block-000152-0346f09a → block-000339-bdd6c4e8 |
| item | UNRESOLVED STAFF COMMENTS | 23 | block-000340-66d297db → block-000341-a3014a36 |
| item | CYBERSECURITY | 23 | block-000342-81f22896 → block-000348-78ba5414 |
| item | PROPERTIES | 24 | block-000349-00454a69 → block-000350-e2e60811 |
| item | LEGAL PROCEEDINGS | 24 | block-000351-f4389f2c → block-000352-737ca3b1 |
| item | MINE SAFETY DISCLOSURES | 24 | block-000353-04597531 → block-000354-a3014a36 |
| part | PART II | 25 | block-000357-87b6a3b1 → block-001281-a3014a36 |
| item | MARKET FOR REGISTRANT’S COMMON EQUITY, RELATED STOCKHOLDER MATTERS, AND ISSUER PURCHASES OF EQUITY SECURITIES | 25 | block-000358-801a524b → block-000389-973caf7f |
| item | [Reserved] | 27 | block-000390-6b264e21 → block-000390-6b264e21 |
| item | MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS | 28 | block-000393-ddac7c96 → block-000674-066091ae |
| item | QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK | 41 | block-000675-424c31fc → block-000702-dd83fec8 |
| item | FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA | 44 | block-000705-d8fafffe → block-001254-1d81d3bc |
| item | CHANGES IN AND DISAGREEMENTS WITH ACCOUNTANTS ON ACCOUNTING AND FINANCIAL DISCLOSURE | 89 | block-001257-192d7e7c → block-001258-903ea500 |
| item | CONTROLS AND PROCEDURES | 89 | block-001259-8dcaa824 → block-001268-06dca432 |
| item | OTHER INFORMATION | 89 | block-001269-f827e3e6 → block-001279-b29a991f |
| item | DISCLOSURE REGARDING FOREIGN JURISDICTIONS THAT PREVENT INSPECTIONS | 90 | block-001280-4463e43b → block-001281-a3014a36 |
| part | PART III | 91 | block-001284-8867fe43 → block-001295-a52dc434 |
| item | DIRECTORS, EXECUTIVE OFFICERS, AND CORPORATE GOVERNANCE | 91 | block-001285-331a649e → block-001287-76d1af5b |
| item | EXECUTIVE COMPENSATION | 91 | block-001288-505bcd35 → block-001289-fd05653f |
| item | SECURITY OWNERSHIP OF CERTAIN BENEFICIAL OWNERS AND MANAGEMENT AND RELATED STOCKHOLDER MATTERS | 91 | block-001290-2870ee90 → block-001291-3bb0e435 |
| item | CERTAIN RELATIONSHIPS AND RELATED TRANSACTIONS, AND DIRECTOR INDEPENDENCE | 91 | block-001292-136373bc → block-001293-997b2851 |
| item | PRINCIPAL ACCOUNTANT FEES AND SERVICES | 91 | block-001294-dd5ad323 → block-001295-a52dc434 |
| part | PART IV | 92 | block-001298-caa911f8 → block-001337-730cd280 |
| item | EXHIBITS, FINANCIAL STATEMENT SCHEDULES | 92 | block-001299-5a9baa0c → block-001323-bc04fd1d |
| item | FORM 10-K SUMMARY | 96 | block-001324-4c9fa19b → block-001337-730cd280 |

## 现金流量表的结构样本

原表位于报告第 52 页。解析后保留 `block_id`、原文 `text`、页码、DOM 路径、`table.row_count`、`column_count` 与单元格 `row/column/rowspan/colspan/text`。该表原始网格为 44 行、18 列；含合并单元格和版式占位，不能理解成 18 个财务指标。

[单位原文：(in millions)](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/indexes/googl-2025-10k/blocks.jsonl:773)

[原表完整解析对象](/Users/bytedance/Documents/ChatGPT/uteki/data/company_workspace/extraction_ab_v1/corpus/googl/dataset/indexes/googl-2025-10k/blocks.jsonl:774)

### 另一个样本：第 38 页的原文列表项

```json
{
  "block_id": "block-000615-414413ff",
  "type": "list_item",
  "text": "•technical infrastructure, which consists of our investments in servers and network equipment, data center land, and building construction and improvements; and",
  "reported_page": 38,
  "text_hash": "414413ff3b36fe13119a9baa8231d2b0ece780e1e429a8822860b54a306ffa77"
}
```
上例为真实原文块的字段节选，其余定位字段仍保留在完整对象。

解析索引 SHA256：`4c43a61d8285f9ec33e0cdfd7d131fda1e315db10e5ec2db4e28c1d4925922a8`。
