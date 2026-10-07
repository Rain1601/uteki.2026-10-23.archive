# 显式配置、一次一项的模型实验

最初交付为执行入口与离线协议测试。后续已用此入口完成[八次显式配置试验](../2026-10-07-reproducibility-pilot-v1/RESULTS.zh-CN.md)，新结果保存在该独立目录。旧 Sonnet 结果仍来自 2026-10-06 22:30:58（北京时间），不因查看对比页面而重新生成。

问题：历史样本没有显式指定 Sonnet 推理力度，也没有完整记录协议参数；容易把请求默认值、实际生效配置和刚刚发生的调用混在一起。

本轮输出：每次发送前保存配置快照、配置哈希、明确的 profile、实际 HTTP 请求正文（不含请求头/密钥）、输入与系统提示指纹。返回后保存 HTTP 状态、请求/响应 ID、用量、结束原因和结果。输入范围及来源完全来自 `--prepared` 指定的冻结材料，无默认公司或期间。参考答案不进请求。

## 可选配置

| Profile | 协议 | 思考 / 力度 | 输出上限 | 超时 / 重试 |
|---|---|---|---:|---|
| `sonnet-native-high-8k` | AIHubMix 原生 Claude Messages | adaptive / high | 8,000 | 180 秒 / 0 |
| `deepseek-low-16k` | DeepSeek 官方 Chat Completions | enabled / low | 16,000 | 180 秒 / 0 |

原生 Claude 使用 `thinking.type` 和 `output_config.effort`；避免将其隐式映射为网关默认。接口说明依据 [AIHubMix 原生接口示例](https://aihubmix.com/blog/claude-opus-4-7-new-parameters-guide)及 [Sonnet 原生规格](https://platform.claude.com/docs/en/models/sonnet-5-5/overview)。**这只明确我们将发送什么，不宣称网关已经回显确认参数或新版模型真实调用通过。** 新协议不是对旧 Sonnet 请求的原样复现，比较时保留该差异。

温度、top_p 等没有发送的字段标为 `not_sent`；无法从历史文件确定的字段为 `not_recorded`；供应商生效配置为 `unverified`。不把未发送解释成某个已知默认值。输入缓存写入未请求；若响应出现未知类别的缓存写入，费用保留未知，不当成零。

## 运行约定

`run_once.py` 必须提供 `--profile`、`--prepared`、`--budget-usd`。先使用 `--dry-run` 检查输入和预算；真实运行还须指定新的 `--output` 目录。一次进程只发送一个模型请求，不批跑、不重试、不续写。结束后检查完整性、原文质量、配置与用量，再决定下一项。价格与预算仅为估算，不是账户强制扣费上限。不要在命令行或日志中传入密钥。

输出使用现有单样本记录结构，另增加 `configuration.json`、`profile.json` 和 `http-request.json`。当前输出契约仍是带证据的 `facts / analysis / gaps`，**不能把该入口称为完整 BusinessMap 或研究报告 Agent**。新任务先准备明确题目、来源、产物契约和评分规则；需要其他结构时再扩展适配器。

## 最初规划的顺序（进度见下方）

1. 用已有现金流材料运行显式 Sonnet 配置，核验原生调用回执与用量字段。
2. 同题运行 DeepSeek low，检查是否减少推理耗费并保持质量。
3. 再分别选择财报短摘要、变动解释、业务关系识别等小任务，逐项准备材料和评分。每项两个配置依次运行；公司业务图的正式结构需另定契约。

以上为最初的逐项运行计划；实施进度如下。

后续状态：上述前两项已在可复现性pilot逐次完成，并扩展到同材料的变动解释。v2 profile明示采样决策；无效参数在发送前拒绝，DeepSeek明确Top-P 0.95；共享预算通过调用参数注入，不通过新目录重置额度。原生渠道已收到成功响应，但不表示每项内部生效参数已获供应商回显。完整业务图与跨公司试验仍未完成。
