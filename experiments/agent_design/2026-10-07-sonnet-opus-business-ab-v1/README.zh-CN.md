# Sonnet / Opus 单次受控对照

**后续排查更新：** 已在 AIHubMix 控制台找到与本次时间、模型、输入量匹配的成功记录：VertexAI / Opus 5.5，45,669 → 13,971 tokens，288.188 秒，记录扣费 $0.462096。客户端在 241.047 秒已传输失败，未得到正文。见[独立对账记录](provider-console-reconciliation.json)。本地旧回执与费用未知状态原样封存；控制台匹配依据不冒充本地已收到 provider request ID。以下表格是原执行时的本地观察，补充恢复另开版本。

**本轮已发出真实 Opus 请求，但没有收到产物；内容质量对比仍未完成。** [打开结果与原文复核](http://127.0.0.1:8769/docs/design/data-agent-acceptance/sonnet-opus-business-ab-v1/?view=business)。失败保留为 B，不给零分，也不据此判断 Opus 的内容能力。

## 实际输入与执行

用户要求在已认可的 Uteki + Sonnet 结果上升级 Opus 比较。A 复用已有 Sonnet 运行，B 新增一次 Opus 调用；各一次、先后执行、非盲评。发送前冻结 [协议](protocol.json)，对比两份真实请求，唯一差异是 `model`。没有把旧参考答案或 Sonnet 产物输入 Opus。

- Alphabet FY2025，同一冻结原件的 78 个原文块和 1 张完整收入表（82 个物理单元格），明确选择 2025 年。
- 同一 Skill v0.3 全文、system prompt、输出 Schema、业务契约和执行器代码。
- `thinking.type=adaptive`、`effort=high`、`max_tokens=16000`、`stream=false`、300 秒本地超时、零重试。未发送 temperature/top_p/top_k/seed；不反推供应商默认值。
- Skill v0.4 尚未进入本次请求。模型 A/B 和 Skill 改进验证分轮进行。

| 项目 | A · Sonnet 5.5 | B · Opus 5.5 |
|---|---|---|
| 请求 / 返回模型 | claude-sonnet-5-5 / 同名返回 | claude-opus-5-5 / 未返回 |
| 北京时间 | 2026-10-07 14:19:24–14:20:17 | 2026-10-07 14:57:07–15:01:08 |
| 交付 | 13 个业务节点、14 条关系、2 张收入图 | 连接传输异常，无正文或产物 |
| 调用耗时 | 53.224 秒 | 241.047 秒后失败；不是成功生成耗时 |
| 输入 / 输出 tokens | 45,669 / 8,788 | 未知 |
| 估算费用 | $0.179218 | 未知，不能记为 $0 |
| 状态 | candidate，语义仍有缺口 | failed，内容未能评价 |

费用按保存的 2026-10-06 AIHubMix 价格快照估计，不是实付账单。B 的宿主估算限制为 $1.00，是执行用户本轮请求时选定的单次界限；用户没有逐字指定该金额。已预留 $0.865112，因为没有 usage，预留仍保留，不代表实际扣费。没有自动重试、重置账本或借用旧顾问会话的 $2 额度。

## 已核对与未确定

[Codex 原文审阅](evaluation/comparison-review.zh-CN.md)核对了 78 个原文块、82 个单元格、请求与产物绑定。Sonnet 在选段范围内金额、年度、单位、负调整和勾稽正确；具名业务展开、声明级引用、收入图标题和 Isomorphic 归属标记仍有四项缺口。条形图与环图的选择本身不作为质量扣分。

B 没有 HTTP 状态、响应 ID、停止原因或 usage。运行进入 `Claude Messages transport failed` 分支，而非客户端的 `TimeoutError` 分支；没有依据认定是 token 耗尽、额度不足或服务端生成失败。请求标记 sent 只说明客户端开始提交，不证明上游完成处理。具体网络/供应商链路原因仍待核对。

现有适配器未保存底层 HTTPError 子类，因此无法从这次记录恢复更细原因。本轮在失败后补充白名单错误分类保存（例如 RemoteProtocolError、ReadTimeout）；不保存异常正文、请求头或密钥。改动仅改善后续诊断，未修改冻结请求/结果，也未再次调用模型。37 项适配器、计费与执行器离线检查通过，包含错误分类保留、私密内容过滤、未知费用保留和不重试。

## 产物与 Trace

- [A 原始结果](../2026-10-07-agent-business-revenue-v1/run-01/result.json) · [A 过程](http://127.0.0.1:8765/agent-runs?agent=data&run=run-ac090fecb2c84b8bacc9cd4d60a0bada)
- [B 失败回执](opus-run-01/result.json) · [B 响应元数据](opus-run-01/response_metadata.json) · [B 过程](http://127.0.0.1:8765/agent-runs?agent=data&run=run-0b7848bb2a814cb585f1103360c1f0f2)
- [实际 Opus 请求](opus-run-01/request.json) · [冻结配置](opus-run-01/configuration.json) · [预检](preflight.json)
- [页面验证](../../../docs/design/data-agent-acceptance/sonnet-opus-business-ab-v1/verification.json) · [交付检查](../../../docs/design/data-agent-acceptance/sonnet-opus-business-ab-v1/delivery-check.json)

页面按真实记录生成。验证了协议与结果绑定、内容与链接及 JS 语法；没有浏览器视觉验收。业务/收入仍是两个视图；Opus 一侧明确显示未交付，不制造空白图或缺失页面。

## 当前 TODO 与下一步

1. **立即：核对 Opus 供应商日志与计费。** 关注北京时间 14:57–15:01 的本次调用。待明确结果后，确定恢复方式并补齐内容对照；本轮未追加请求。若改成流式传输或其他配置，要另开版本并明确差异，不能悄悄混进这组仅换模型的 A/B。
2. **随后：固定 Sonnet，验证 Skill v0.4。** 相同冻结输入与设置，只改 Skill；验收四项缺口，显示“旧结果 → 新结果 → 原文依据”，同时守住收入校验。不是用人工补丁代替真实输出。
3. **再做：NVIDIA 留出材料 → 底稿质量核查 → 两个 Query。** 分别检查迁移、页码/单位/脚注/覆盖，以及一个收入问题和一个业务问题的精确取证。整文解析、重复稳定性和其他公司不能由本次选段成功替代。
