# Qwen 低成本取材适配核对

当前候选为 AIHubMix 的 `qwen3.8-flash`。本轮仅做官方资料核对、只读模型目录查询和模拟 HTTP 测试，未发送付费生成请求。真实参数受理和取材质量仍需一题实跑验证。

## 官方依据

- [AIHubMix 模型页及价格](https://aihubmix.com/model/qwen3.8-flash)
- [AIHubMix 参数说明](https://aihubmix.com/model/qwen3.8-flash/llms.txt)
- [AIHubMix 公开参数 JSON](https://aihubmix.com/model-data/models/qwen3.8-flash.ff72f9f0.json)：原件保存在同目录 `qwen3.8-flash-official-schema.json`，hash 与只读目录观察保存在 `qwen-support-metadata.json`。
- [阿里云 OpenAI 兼容协议说明](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)
- [阿里云结构化输出说明](https://help.aliyun.com/zh/model-studio/qwen-structured-output)

2026-10-09 核对：本机账户通过只读 GET `/v1/models` 得到 `qwen3.8-flash`。目录存在不等于已验证生成权限、网关全部参数或质量。

价格单位是美元／百万 token：输入 0.1126，输出 0.38，缓存读取 0.0141，缓存写入 0.1759。运行时使用公开价格估算，不代替实际账单。当前适配不请求缓存写入；如响应出现未支持的缓存收费字段，保留未知费用及全额预留，不默认为零。

## 首题明确配置

| 项目 | 首题配置及含义 |
| --- | --- |
| 模型 | `qwen3.8-flash`，AIHubMix Chat Completions |
| 努力程度 | `reasoning_effort=low`，避免供应商默认 `xhigh` |
| 输出上限 | SDK 入口 `max_tokens=8192` 映射为请求 `max_completion_tokens=8192`，覆盖思考与可见输出总量 |
| 历史思考 | `preserve_thinking=false`；当前每次决策使用独立的最新状态包 |
| 采样 | 不传 temperature、top_p、top_k；不承诺逐字复现 |
| 格式 | `response_format=json_object`；提示包含输出契约；宿主再次检查重复字段、类型和业务协议 |
| 工具 | 模型输出宿主可执行的 JSON action；此适配不启用原生 tool calls |
| 流式 | false，要求完整 `finish_reason=stop` 才执行 action |
| 审阅者 | 固定沿用 Sonnet；只替换 planner／worker |

因此这是“Qwen 取材 + Sonnet 审阅”与“Sonnet 取材 + Sonnet 审阅”的混合系统对照。它不是完全相同采样参数的底模 A/B。题目、原件、数据集、工具、预算账本、输出契约和独立评分保持冻结，推理参数差异必须保留。

## 代码与验收范围

工厂仅对这个显式模型 ID 注册适配，不把它作为默认模型。Qwen 复用已有 SDK、严格 JSON 校验、费用预留和网络重试机制。每次调用保存可见原始输出、原始 usage、请求及响应 ID、实际返回模型、终态和配置切面。思考 token 已包含在 completion_tokens 内，不二次收费；未保存私有思考正文。

测试使用真实 SDK 加模拟 HTTP，覆盖实际请求参数、总输出上限、缓存读取计费、重复 JSON 字段、截断结果拒绝、缺失 usage 保留未知费用及历史配置 hash 兼容。它证明工程边界，不证明模型能够取对材料。真实首题由主任务在既有共享账本下执行，不能另开账本获得额外额度。

SDK 入口示意：`SdkAutonomousPlanner(provider='aihubmix', model='qwen3.8-flash', reasoning_effort='low', max_tokens=8192, ...)`。其余公司范围、数据集、任务、输出目录与共享预算必须由调用者显式传入；reviewer 配置保持原 Sonnet 配置。

已知限制：当前只注册一种 Qwen 型号；不支持流式和原生工具；单次总输出工程上限 8192；不启用平台缓存写入；网关真实生成尚待验证。对未知模型别名、错误 effort、采样覆盖、额外请求字段和截断终态明确报错，不回退到其他模型。
