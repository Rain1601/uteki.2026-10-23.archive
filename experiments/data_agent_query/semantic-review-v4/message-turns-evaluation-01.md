# 分角色消息实验独立评分

**message-turns-02 仍未接受：host 引用修复与语义修订均未发生。** 本次是已知 Northstar 失败稿的开发回归，不是新 v4 未见案例的结果。

实际执行为 **1 次历史重放 + 2 次新 reviewer 调用 + 0 次 critic 调用**。此前 message-turns-01 在初始化阶段失败，没有模型调用，不纳入这两次请求。

已核验两份实际模型输入都采用 `user → assistant → user`：第一条是完整冻结来源 packet，第二条是历史模型草稿，第三条是 host 修复反馈。来源、草稿及反馈逐项一致；模型和 prompt 与 continuation-02 相同。没有发现 expected 注入。

两份新回复仍与历史草稿字节完全一致，均为 SHA256 `c5ebabb3323c8e3431041d26b60cb018ea43c75b66118d73db2e369f28e6b222`。分开消息角色没有在本次回归中改变模型行为。

| 检查 | 结论 |
| --- | --- |
| Host 引用修复 | 失败。两组 dimensions 仍只引用表头或定义，没有对应财务行 |
| 独立语义修订 | 未发生。operating income 的术语与费用加回方向错误原样保留 |
| 断言标签 | 两次新回复各为 4/4，但均不是已接受案例通过 |
| Critic | 已启用，但所有 proposal 在此前被拒绝，实际调用为 0；不能判断漏报或误报 |

两次新调用计价估算合计 $0.03643992，实际账单金额未知。历史重放不计新增调用。

- [完整独立评分](../../../data/company_workspace/record_review/semantic-loop-v3/message-turns-independent-evaluation-01.json)
- [独立说明与消息格式核验](../../../data/company_workspace/record_review/semantic-loop-v3/message-turns-independent-notes-01.json)
- [原始结果](../../../data/company_workspace/record_review/semantic-loop-v3/message-turns-02/run/result.json)

运行结果 SHA256：`d3aaf4f6a8996db7b5f49edf3a2c12235957baabe00ca0bdc4ccf204f30e3c2d`。本次没有修改冻结预期，也不改变先前 heldout 评分。

下一步需将这项消息格式失败与新 v4 未见测试分别报告，避免把已知失败稿的重复尝试当作新增泛化证据。
