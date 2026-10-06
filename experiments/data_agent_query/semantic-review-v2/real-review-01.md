# v2 首轮真实语义复核：独立评测

审阅 `data/company_workspace/record_review/semantic-integrity-v2/real-run-01` 的原始响应、接受产物及最终结果，沿用该实验已冻结的 `frozen-real-cases.json`，不修改预期。结果 SHA256：`1ac1bc1cf72349a7fa2d63f4c7120b2c5635a47314d9186df021f62664c1cd83`。

机器评价见 [real-evaluation-01.json](real-evaluation-01.json)。本次没有追加模型请求，没有修改原响应或运行契约。

## 最终结果

运行状态为 **partial，接受 1/2 个案例**。分部案例第二次响应通过工程校验；Cloud 两次响应均因未覆盖完整段落锚点被拒。

| 案例 | 工程接受 | 独立评价 |
|---|---|---|
| 分部 24 条 | 是，第二次响应 | partial：原两个残留改善，但合并例外少覆盖两条 FY2025 Total |
| Cloud 3 条 | 否 | partial：原始语义判断有据，但不满足 v2 完整段落锚点要求，不能计作接受意见 |

## 分部首响应：空 IDs 约束

首响应 `checks[2].constraints[2]` 引用 `block-001228-76ee317f`，指出资产未分配至分部、利润中折旧摊销不能单独识别。该原文确实存在，但该约束的 `record_ids` 为空，违反契约。

当前 24 条记录是收入和营业利润，没有资产或单列折旧摊销指标。模型加入了一条一般使用限制，却没有指定它究竟约束哪些观测。不能自动把它挂到全部 24 条，也不能为了保留原文而绕过非空 ID 要求。若针对利润推导折旧摊销的使用场景，应明确关联利润记录及推导边界；当前响应没有完成这一步。

因此拒绝正确。原文有据不等于模型约束有完整归属。上述说明是输出行为判断，不是对模型内部动机的证明。首轮通用 ValidationError 反馈没有定位空字段，属于单独的反馈可用性问题。

## 分部接受响应

### 原两个残留已有实际改善

- 三个分部和 Total 的维度约束均引用收入行及相应营业利润行。Total 现在同时引用 `Total Revenue $ 281,724 $ 245,122 $ 211,915` 与 `Operating Income $ 128,528 $ 109,433 $ 88,523`。
- 不再自由文本声称已供 Note 1 重述段缺失；响应使用宿主已知对象的 `context_claims`。其中引用目标 unresolved 与已供 source block 是不同对象，不能解释为已供正文不存在。
- 历史分部重述 12 条、收入分配 9 条、营业利润费用分配 9 条以及维度 24 条集合正确，未观察到 Total 排他错误回归。

### 冻结验收范围出现新漏项

合并例外约束只列四条 FY2023/FY2024 Total，其陈述也准确限定这两个历史年度；未观察到对这些四条的错误金融解释。

但原冻结 expected 要求六条 Total，此响应漏掉：

- `obs-71426abfd6e87ce682843e93`：FY2025 合并收入。
- `obs-d471c9f3d1f12b167e1eb773`：FY2025 合并营业利润。

不能改预期来迁就本次响应，也不能用维度轴已经提过两条记录来替代 comparability 轴的明确覆盖。故该项为 partial，而不是六条均已通过。

## Cloud：语义判断与契约拒绝分开报告

两次原响应均识别 Microsoft Cloud 已包含于四个产品/服务类别，不可重复加总；也保留 Microsoft 365 Commercial cloud、Azure and other cloud services、LinkedIn 的 commercial portion 和 Dynamics 365 的构成。

第二次响应的 additivity 引用段落第二句 `These amounts are included in ...`；dimensions 引用第一句完整构成和三年金额。这些是连续原文，三个 record IDs 也正确。没有观察到把 Cloud 理解成独立可加总收入的语义回退。

但 v2 对三个 Cloud 记录的 host anchor 是完整 `block-001227-3bdf0315` 段落，范围 `[0,459)`，包含两句。dimensions 约束仅引用第一句，未覆盖完整锚点；即使另一轴引用了第二句，也不满足每条约束独立覆盖的要求。两次均被拒，最终失败理由为 `citation does not cover the complete record anchor`。

因此，本轮不能称 Cloud 通过。这里暴露的是完整段落锚点要求与模型按语义拆句引用之间的边界，不是再次证明模型不理解重叠关系。本评测不放宽校验、不拼接原响应、不将未接受意见补记为通过。

## 范围限制

这是已见真实案例上的契约迭代，非未见公司泛化或全文遗漏率评测。原始语义判断、工程接受与冻结 expected 覆盖分别记录；所有候选事实和原结果保持不变。本报告未评价后续独立 synthetic 运行，也未追加任何模型调用。
