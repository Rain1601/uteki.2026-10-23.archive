# E2 季度/累计收入：原件先读核验

Codex独立读原件利润表后，再对照准备数据；另一Codex审阅者只读复查。范围为Microsoft FY2025 Q3 10-Q的公司整体收入，不能代表整份季报通过。0模型、0HTTP、费用$0。

原件page 3为INCOME STATEMENTS，表头为“In millions, except per share amounts”，未经审计；列次是截至March 31的三个月2025/2024与九个月2025/2024，表后有“Refer to accompanying notes.”。

| 必需事实 | 原文：百万USD | 归一：USD | 精确起止 | 记录 |
|---|---:|---:|---|---|
| 2025三个月收入 | 70,066 | 70,066,000,000 | 2025-01-01..2025-03-31 | obs-3f55bd44ba423ec3cf3f9a78 |
| 2024三个月收入 | 61,858 | 61,858,000,000 | 2024-01-01..2024-03-31 | obs-666902e4e5f7773e3559e872 |
| 2025九个月收入 | 205,283 | 205,283,000,000 | 2024-07-01..2025-03-31 | obs-25140183c51f3ebccf95b258 |
| 2024九个月收入 | 180,395 | 180,395,000,000 | 2023-07-01..2024-03-31 | obs-d43d3c992356d28c310625d4 |

正文支持单位、期间列次、金额；精确开始日由原件XBRL context支持，不要求正文重复日期句子。四fact均为us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax，无维度，CIK 0000789019，unitRef U_USD / iso4217:USD，scale=6。

四context依上表顺序为：C_f5d91e16-4fa6-44d0-96d4-472f3551cf38、C_455d6a4d-b989-4a77-93d1-42ed4e1071c0、C_d3bd9e88-a02c-41b2-9d3d-eeb55d3a1689、C_b40cce39-ac78-4781-a390-3531b01d2ba6。证据元数据保留context_xml、unit_xml、scale及精确fact DOM path。

利润表锚点block-000032-4d792bdd，DOM /html/body/div[9]/table，47行17列；总收入row 11、columns 3/7/11/15。相邻block 31为标题，33为附注提示。它是本次复查入口，不是唯一合格出处；原文其他表格重复同值，各事实4个occurrences、合计16条，不得相加。

原件与准备raw逐字节相同，SHA256 33b37f4af3e98c28c7ada1167eefb002e2862e69850e02fa4888d1ad83ee58aa。准备manifest hash 08b2e5474097f45f1676f0098af2de127de0881491acd6310422a2a2ed42ab6b。

[原件](../source-store/sources/objects/33b37f4af3e98c28c7ada1167eefb002e2862e69850e02fa4888d1ad83ee58aa.bin) · [记录](../preparation-v1/dataset/records.json) · [证据](../preparation-v1/dataset/evidence.json) · [离线关口验收](gates-v4/audit.json)。本文与脚本只在evaluation-only，不进入生产Agent上下文；E2问题及完整逐题标准尚未冻结。
