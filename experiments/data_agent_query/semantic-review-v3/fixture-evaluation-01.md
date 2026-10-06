# Development / heldout 首轮独立评分

**四个案例独立通过 0/4。** 原始断言标签为 **11/11 正确**，但三个案例未通过局部引用覆盖校验；唯一被 host 和 critic 接受的案例仍违反冻结的缺资料声明约束。不能用标签正确率代替案例通过率。

本次按运行前冻结的 development / heldout expected 评分，没有改预期、prompt 或模型输出。每个案例最多一份 proposal；仅有效 proposal 进入 critic。本次四题实际共 **4 次 reviewer + 1 次 critic** 调用，没有修订稿。

| 案例 | 首稿断言标签 | 最终已接受断言标签 | Critic | 独立结果 |
| --- | --- | --- | --- | --- |
| sv2-001：Birch 两期同值 | 1/1 | 无已接受结果 | 未调用 | not_accepted：dimensions 约束只引表头，没有收入/利润行 |
| sv2-002：Birch 已供详情与引用 | 2/2 | 2/2 | pass | fail：自由文本仍作缺资料声明，并与“无法确认是否已提供”矛盾 |
| sv3-001：Northstar 新指标同值、已供定义 | 4/4 | 无已接受结果 | 未调用 | not_accepted：dimensions 只引表头/定义，没有对应行；另有解释错误 |
| sv3-002：Northstar 非自然财年、重述与合并例外 | 4/4 | 无已接受结果 | 未调用 | not_accepted：supported 断言只引重述说明，没有规定的原表行 |

sv3-001 正确认出了净利润与经营现金流虽然同值、仍是不同指标，也判断了诉讼费用反例。但中文多次把 operating income 写成“营业收入”，并将调整过程表述为“从 14 扣除 2 和 3 得 19”。原文支持排除费用影响后加回：14 + 2 + 3 = 19。最终报告金额正确，不能据此忽略概念翻译和操作方向错误。

sv3-002 的重述范围和合并例外均准确：重述绑定 FY2023 Sensors 收入，合并例外绑定 FY2024/FY2023 两期。其重述说明直接支持金额 50；未接受的原因是冻结协议另外要求在该 supported 断言上引用对应表行，不能将此次拒绝写成“实质断言为假”。

唯一一次 critic 返回 pass、没有 issue，漏掉 sv2-002 的未核实缺资料推断及内部不一致。冻结规则要求区分“给定摘录不足以说明分配方法”和“未解析的 Note 4 引用证明内容没有提供”。这里不是声称摘录中实际存在该方法，也不是判断发行人缺少附注。其余三个案例在 critic 之前被拒绝，不能计为 critic 漏报。此次没有 critic 发出误报 issue；只有一次 critic 样本，不能据此推断误报率或准确率。

完整元数据、首稿检查项和逐条独立说明位于 Git 忽略的归档目录：

- [Development 完整评分](../../../data/company_workspace/record_review/semantic-loop-v3/development-independent-evaluation-01.json) · [独立说明](../../../data/company_workspace/record_review/semantic-loop-v3/development-independent-notes-01.json) · [原始结果](../../../data/company_workspace/record_review/semantic-loop-v3/development-run-01/result.json)
- [Heldout 完整评分](../../../data/company_workspace/record_review/semantic-loop-v3/heldout-independent-evaluation-01.json) · [独立说明](../../../data/company_workspace/record_review/semantic-loop-v3/heldout-independent-notes-01.json) · [原始结果](../../../data/company_workspace/record_review/semantic-loop-v3/heldout-run-01/result.json)
- [离线评分脚本](evaluate_fixtures.py)

结果 SHA256：development `5077b214516263a18f3457f0de45ba64a470229356d06ac9e98eed7869048f78`；heldout `4bb9853fd42ba52f38be03f3cd1cddc60a0c265906164c82a71e378990fa3016`。

下一步：将这些失败用于后续开发时，应把相应案例视为回归集，另建未见案例才能继续声称 heldout 泛化验证。原始通过标准与本轮评分保持不变。
