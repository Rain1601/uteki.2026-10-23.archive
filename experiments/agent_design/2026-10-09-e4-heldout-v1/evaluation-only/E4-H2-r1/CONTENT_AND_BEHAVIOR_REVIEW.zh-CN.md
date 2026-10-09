# E4-H2-r1 新公司保留题独立验收

**实际材料仅支持两个整体收入，未取得三地区金额和归属规则；本题失败保留。** 外层 `failed / ValueError`，query `limited / no_progress_limit`，尚未进入双审。

## 已有材料能支持什么

Salesforce 全年 **2024-02-01 至 2025-01-31** 公司整体收入为 **37,895 million USD**；全年 **2023-02-01 至 2024-01-31** 为 **34,857 million USD**。两项金额、合并整体身份、单位与精确起止均与 FY2025 10-K 原件及 inline context 相符。

实际 t3/t4 查询各返回两个等价原件记录，共 4 个候选记录、2 个唯一事实。它们是重复出处，不相加。t6 读到的是 **p60 Consolidated Statements of Operations**（`block-000867-3563acda`），并含公司名、表名和 `(in millions, except per share data)`；不是 MD&A summary。虽然工具结构预览截断，t7 实际模型输入 retained_body 含完整四块正文与 Total revenues 行，逐字匹配原件，不能把此处误说成未读两个整体收入。

## 缺少什么

| 必需项 | 实际结果 |
|---|---|
| R1 FY2025 整体收入 | 已检索、原件核对正确；t7 显式选了一条记录 |
| R2 FY2024 整体收入 | 已检索、原件核对正确；记录尚未显式选择 |
| R3 FY2025 Americas 收入 | 未查询/未读取/未选择 |
| R4 FY2025 Europe 收入 | 未查询/未读取/未选择 |
| R5 FY2025 Asia Pacific 收入 | 未查询/未读取/未选择 |
| 必需地理归属规则 | 未读取/未选择 |

冻结原件标准要求 FY2025 三地区金额和按 **Salesforce 签约主体地区**归属、**可能不同于客户地区**的限定。运行材料没有这些内容，不能用总收入、实体目录身份或预审答案填补。两项收入的某些等价候选出处虽引用 p73 地理表总额，但没有成功读取这张地理表正文；引用总额不证明三个地区都已获得。

`delivery_selection={}`，尚无最终显式原件交付。evidence bundle 的 delivered_body 表示 t6 确实读到四块，不能代替 select_evidence。没有 review-packet、源审核或问题审核产物，不以 canonical 自动补表追认缺失内容。

## 三轴与实际行为结论

| 验收维度 | 结论 |
|---|---|
| 必需覆盖 | 不通过；检索 2/5 金额，缺 3 地区与完整归属规则 |
| 真实性、范围与出处 | 已取两个整体收入正确，不能将部分正确扩大为全题通过 |
| 聚焦与冗余 | 已读合并损益表及邻接单位/标题有用；没有最终选择和完整交付，不宣称完整聚焦验收通过 |
| 实际读取/选择与整体运行 | 读取两个总额的原文通过；显式交付未完成，整体失败 |

## 停止原因与费用

t5/t8 地区目录里出现了 Asia Pacific 身份；目录不是收入事实。t9 计划只传新的 APAC requirement，host 以 `plan revision cannot erase or rewrite an existing requirement; append explicit requirements` 拒绝，新增要求未采用。此前的 Americas/Europe query 也未执行。t10 再查同页目录没有进展，止于 no_progress_limit。原始计划的 customer location/delivery basis 只是未核验查找例子，不能替换原件的签约主体规则。

本轮 **10 请求 / $0.1095249** 保守估算，未知 0，实际账单金额未取得。主线同账本快照累计 **151 请求 / $1.7772861**，原上限 **$3**，未知/在途 0。本次独立验收 API 0。530 个 manifest 条目 hash 一致，原件和冻结标准未修改。

完整证据：[独立验收 JSON](independent-original-and-behavior-review.json)。下一步修复追加计划保留已有要求的通用机制，再用原题和未变标准真实执行；本轮失败与缺口保留。
