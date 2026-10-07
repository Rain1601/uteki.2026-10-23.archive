# Opus 恢复后交付

**后台流式接收已完成一次真实交付。** [恢复后对照](http://127.0.0.1:8769/docs/design/data-agent-acceptance/sonnet-opus-recovery-v1/?view=business) · [Opus 独立图页](http://127.0.0.1:8769/docs/design/data-agent-acceptance/opus-stream-recovery-v1/?view=business)。

本轮用户要求排查未交付、检查日志并继续其他公司。[排查与修复依据](DIAGNOSIS.zh-CN.md)区分确定事实与推断：旧供应商记录显示成功且计费，本地在完整结果回来前传输失败。具体断连节点没有证据确认。

## 真实恢复结果

| 项目 | 本次记录 |
|---|---|
| 模型 | AIHubMix / claude-opus-5-5，请求与返回同名 |
| 原文 / Skill | Alphabet FY2025 原包；冻结 Skill v0.3，与原 Opus 请求相同 |
| 传输 / 等待上限 | stream=true，后台累计可见文本；600 秒总上限；零重试 |
| 完整交付 | HTTP 200、message_stop、end_turn；严格 Schema/范围/数值绑定校验通过 |
| 产物 | 14 个业务节点、16 条关系、4 张收入图、52 个证据片段、7 项未知 |
| 耗时 | 144.890 秒；63.481 秒收到响应头，63.482 秒收到首个事件 |
| 用量 | 输入 45,669 / 输出 12,561 tokens；缓存读/写均报告为 0 |
| 费用 | 按保存价格估算 $0.433896；预留已结算，本次没有未知费用 |
| Trace | run-9c97aebccd1c43bdb1aa846e4f9e5e2a |

[结果](run-01/result.json) · [配置](run-01/configuration.json) · [响应元数据](run-01/response_metadata.json) · [运行过程](http://127.0.0.1:8765/agent-runs?agent=data&run=run-9c97aebccd1c43bdb1aa846e4f9e5e2a)。原始业务/收入 JSON 与请求保持封存，语义评价另存。

## 怎么比较

与旧失败 Opus 的请求正文只有 stream 不同，本地总上限和传输实现也已改变。与旧 Sonnet 的正文差异是 model 和 stream；prompt、原文、Skill 和输出 Schema 保持一致，原始请求差异与版本可核对。页面称“恢复后对照”，不冒称原纯模型单变量 A/B；每路仅一次完成响应，不能据耗时变化认定流式一定更快或已经证明重复稳定性。

四张图分别是集团汇总、集团细类、Google Services 内部构成、Google advertising 内部构成；每张分母不同或分类层级不同，不能把四张图的金额再相加。具体语义质量见独立复核记录，图数和节点数不是评分。

## 费用分开记录

- 旧未交付 Opus：本地 usage 未收到；控制台匹配记录扣费 $0.462096。
- 本次恢复 Opus：API usage 估算 $0.433896。
- 两次 Opus 尝试参考合计：$0.895992。它混合供应商控制台金额和本地 API 估价，并含关联限制，不是发票实付核对。
- Sonnet 旧基线：$0.179218。NVIDIA 迁移另计，不归入本次模型对照。

旧 Opus 的平台匹配依赖时段、模型和相同输入量；本地缺失 Request ID，因此不改写旧 run 和预算账本。[平台补证](../2026-10-07-sonnet-opus-business-ab-v1/provider-console-reconciliation.json)另存。

## 运行结束后的清理修复

本次已经收到完整正文、最终用量并通过产物校验，随后进程退出时出现 HTTPX/httpcore 异步生成器清理警告。它与原 241 秒断连不同，不能据此抹掉本次已交付结果。

已用真实 HTTP/1.1 分块解析栈和离线数据复现该警告：在 message_stop 直接返回，会让底层迭代链没有读到 HTTP 正文终止符。后续实现现在读完正文，再交付；终止事件后的额外 SSE 事件会被拒绝。51 项离线检查通过。NVIDIA 使用这版清理修复，见其 protocol-v2.json；本次 Opus 的实际实现 hash 保留在本协议，不回填新版本。

## 下一步

本次两模型的[原文语义复核](evaluation/comparison-review.zh-CN.md)已完成：Opus 的两个新增收入下钻图、图标题与一处不确定归属处理更完整，核心业务粒度和声明级引用仍有缺口；Sonnet 本次更快、更便宜。各一次结果不足以宣布总体赢家。

[NVIDIA 真实案例及派生图](../2026-10-07-nvidia-business-revenue-v1/README.zh-CN.md)已交付，继续依据明确错误调整 Skill 或契约。整文解析、更多公司、重复稳定性与 Query 仍分别验收，不把一次恢复当成全链路成熟。

后续 NVIDIA 首次流式请求在 240.744 秒因 RemoteProtocolError 结束，未收到响应头。这说明流式接收不能保证网关及时发送响应头；本修复已验证的是可正确接收和校验完整响应，不是所有长请求都已稳定。见[该次回执](../2026-10-07-nvidia-business-revenue-v1/run-01/result.json)。
