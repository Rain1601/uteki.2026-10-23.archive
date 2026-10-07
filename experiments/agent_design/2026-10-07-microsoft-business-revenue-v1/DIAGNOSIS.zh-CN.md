# Microsoft run-01：输出上限导致未交付

**这次调用成功到达模型并完整收到流；模型在用满请求的 16,000 输出 token 后停止，尚未完成 JSON。** 本地据此拒绝交付候选。没有证据表明是断流、600 秒超时、余额不足或协议错误。

依据：[响应元数据](run-01/response_metadata.json)、[实际请求](run-01/request.json)、[运行回执](run-01/result.json)、[原始可见回答](run-01/response.txt)。Trace：`run-c1a0d061813b4f53ac906ee82357061b`。

| 观察项 | 实际记录 |
|---|---|
| 模型与配置 | AIHubMix / `claude-sonnet-5-5`；adaptive / high；stream=true；max_tokens=16000；timeout=600 秒 |
| 传输 | HTTP 200；headers_received=true；body_complete；stream_complete=true；706 个流事件 |
| 耗时 | 99.55 秒；首个响应头约 76.40 秒 |
| 供应商停止原因 | `max_tokens`；reported input=79,406、output=16,000；非 `end_turn` |
| 可见文本 | 12,023 UTF-8 字节，10,763 字符；未做秘密遮蔽 |
| 费用 | 按已保存单价估算 $0.318812；本次预算 $0.60，held=0、unknown_requests=0。平台实际账单未回填 |

## 截断位置与交付状态

回答以 ` ```json ` 围栏开始，违反请求的“单一裸 JSON”要求。更主要的问题是正文未完成：第 7 个业务对象 `biz_linkedin` / LinkedIn 在字段名 `"evidence` 中途结束，字符串与外层结构均未闭合。

前 6 个对象在语法层面完整：Microsoft、三个报告分部、Microsoft 365 Commercial、Microsoft 365 Consumer。这只是诊断时对可见前缀的观察，**没有将它们作为通过校验的业务产物**。正文尚未到达 `relationships`、`revenue_charts`、`unknowns`、`schema_version`、`relationship_absence`；不能据此判断模型原本打算遗漏这些字段。

本地没有生成 `draft.json`、`validation.json`、`business_map.json`、`revenue.json` 或 `evidence.html`。运行回执里的 `ModelBehaviorError` 对应执行层发现非正常完成的回答，不代表 HTTP 协议损坏。即使移除开头围栏，正文仍不能解析成完整 JSON；不能补括号、补空列表或沿用旧答案来冒充本轮交付。

## 输出密度：支持担忧，尚不能证明全部原因

前 6 个完整对象已包含 **33 条字段证据记录、38 段摘录**。其中公司级对象占 4,505 字节；这些摘录的原文内容合计占 3,710 字节。当前契约要求每个名称、描述、产品、客户和明确赚钱方式逐项引用，因此长清单和重复引用确实会扩大可见输出；同一请求又要求业务与所有完整收入维度一起交付。

但只有一次失败样本，不能证明新版契约、compact 编码或 high effort 单独导致失败。供应商只报告总 output_tokens，本地没有每类输出的 token 分账；**不能用 16,000 减可见字符数来推算隐藏思考，更不能断言模型把多少 token 用在思考上。** 传输完整也不等于提取任务完成。

## 最小下一步

1. 先离线调整任务粒度：业务与收入分别形成完整交付，业务细节可按明确分组处理；为每份输出保留覆盖清单、原文 ID、逐项证据与合并校验。当前单次输出契约需要随之明确版本，不能用空收入列表掩盖未执行部分。
2. 做输出体量检查，减少重复的公司级长清单与引文序列化；如改为宿主回填的摘录引用或范围定位，仍须保留原文逐项匹配能力。不能靠删依据换取短输出。
3. 再设计一项有明确费用与输出边界的真实试验，验证完整 `end_turn`、裸 JSON、契约/原文校验和业务覆盖。提高输出上限是另一个实验变量，现有记录不足以保证提高后就能交付。

本诊断未调用模型、未重试、未修改源文件或运行时，也未恢复/采纳任何不完整输出。run-01 的原始记录保持冻结。
