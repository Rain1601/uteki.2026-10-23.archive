# 启动入口复核：协议修复与产物来源

2026-10-08。本轮只改实验 launcher 的读取/来源保证与输出上限；无 API 调用。runtime 由另一分支实现，原始失败和已有账本保留。

已核查 Microsoft generation-01 的原始 9 份已发表文件。模型完整 end_turn、stream_complete、usage reported，并且本次费用 reservation 在原 $5 账本中已 settled。原节点索引问题机械推导之后，仍存在 `monetization_claim_evidence_mismatch`，因此只能发起一次模型自己的协议修复，不能把宿主删除索引当作有效原答。

协议修复只携带四项：`frozen_source_packet`、`own_failed_response`、`protocol_error`、`failed_response_sha256`。启动入口核对原件身份、相同公司/期间/Skill、source-only 原生成请求与 system、原答 hash、程序重算的错误及原发表记录。不接收人工答案或旧图。后续必须显式选择 `--generation-stage protocol-repair-01`。

后续读取核对自己的已发表 source inventory、生成候选和 audit；候选等于原模型答按契约验证后的结构，投影存在时须与通用机械投影完全一致。修订只能使用自己的已发表审阅；最终审阅不传旧结论。消费者的审阅结果也须由原始响应重新验证得到，不能只信后来改过的 JSON。

## 输出额度

| 阶段 | 最大输出 tokens |
|---|---:|
| generation | 24,000 |
| protocol_repair | 24,000 |
| inventory | 32,000 |
| audit | 32,000 |
| revision | 24,000 |
| audit_final | 32,000 |

审阅需要逐 mention 与逐 claim 返回完整清单，因此与 inventory 使用 32k。数字只是请求上限，不是实际消耗或成功保证；每个请求仍在同一账本预检及预留，不能重建额度。

本轮无 API 预检：Microsoft protocol_repair 请求 148,311 bytes；保守预留 $0.568622；当时同任务剩余 $1.189598；可发起。这个结果不保证之后完整路径也可在剩余额度中完成。预检未锁定预留，实际调用仍需重新检查。

4 项离线测试通过：真实父级原发表绑定、其他公司/系统提示拒绝、额外对话/工具拒绝、完整响应不能替代费用 settled。另一个零模型恢复防护测试证明额外协议错误会在新 trace/候选创建前停止。

边界：当前严格的失败恢复必须费用已知；未知请求保持原账本预留。若普通成功阶段含“先断流未知、后重试成功”，消费入口应允许最终成功调用已 settled、早先未知仍在原账本 held 的情形。已向主线指出这与失败恢复条件要区分，不能清零未知费用。
