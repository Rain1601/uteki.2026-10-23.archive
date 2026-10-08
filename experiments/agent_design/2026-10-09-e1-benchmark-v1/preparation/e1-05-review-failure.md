# E1-05 首次审阅失败：逐块审阅被模型漏掉

独立只读复现结果：`review-01` 失败是协议错误，`review-02` 在相同材料和相同提示下通过。没有证据表明取材丢失、网络中断或输出 token 截断。本次定位没有调用模型，没有修改代码。

## 具体错误

调用 `validate_assessment(packet, response)` 复现第一次错误：

`ValueError: review must cover every delivered source body identity exactly once`

输入采用 `source_delivery=query_evidence_v1` 和 `delivery_schema_version=selected-originals-v3`，包含 1 份来源、18 个正文块、18 条事实。第一次模型审查了事实，但返回 `body_checks=[]`。它在 limitations 中自行解释：query_evidence 交付不需要逐块 body_checks，事实相关性检查已经足够。

这个解释不符合实际协议。被冻结的 system prompt 明确要求 selected-originals-v2/v3 对每一个已交付 block 返回 body_checks，且事实相关性不能代替整块正文相关性。因此宿主拒绝是正确的，不能自动填入18条审阅，也不能静默删改原响应使其通过。

## 两次对照

| 项目 | review-01 | review-02 |
| --- | --- | --- |
| 输入正文块／事实 | 18／18 | 18／18 |
| body_checks | 0 | 18 |
| 终态 | end_turn | end_turn |
| 输入 token | 22,914 | 22,914 |
| 输出 token | 3,575 | 4,779 |
| 估算费用 | $0.081578 | $0.093618 |
| 严格校验结果 | 拒绝 | analysis_eligible=true |

两轮 `input.json` SHA256 相同：`1cd143c72f026a732fb2aada251ad5ab25e2adeef260ef6424c3ce8f643d010c`。

两轮冻结提示 SHA256 相同：`5fde4d3a6b58f817a3b1dc45bfc792b150aac7ddf6360319027e6d648e3bbc60`。

这不是修正取材后才通过。第二次模型面对相同输入，自行遵守了原有逐块契约。本观察只能证明两次输出不同，不能以两次运行估计故障概率或宣称问题已稳定解决。

## 判断及建议

直接原因是模型错误解释协议。现有提示不存在要求省略 body_checks 的明确冲突，但同时描述 source_delivery、delivery_schema_version、source_review_policy 三个不同维度，模型混淆了其中两个。输出 Schema 允许空列表以兼容历史包，宿主按当前包版本严格校验，成功挡住错误。没有发现宿主漏传正文或错误要求多余正文块。

工程可进一步降低此类重复费用：为当前包提供确定的 `body_check_keys`，并按当前版本选择单一提示，避免模型自行判断是否要审；为缺失／重复正文审阅记录安全错误码与宿主已知的键；有界修订时提供这个协议诊断，而不是仅以同一包盲重试。上述是后续建议，本次未实施。任何新包字段都需版本化并保留旧包重建兼容；不能改变材料正确性或遗漏检查的标准。

## 原始依据

- [第一次原始响应](../runs/E1-05-sonnet-r1/attempt-01/review-01/response.json)
- [第一次输入](../runs/E1-05-sonnet-r1/attempt-01/review-01/input.json)
- [第一次冻结提示与配置](../runs/E1-05-sonnet-r1/attempt-01/review-01/model/model-config.json)
- [第二次原始响应](../runs/E1-05-sonnet-r1/attempt-01/review-02/response.json)
- [第二次结果](../runs/E1-05-sonnet-r1/attempt-01/review-02/result.json)

这是协议失败诊断，不替代 E1-05 的独立财报内容评分。
