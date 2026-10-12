# E6-QP1：问题审核引用契约

2026-10-12。保留 v2 三次失败首稿、修订稿和费用。本次只对齐 V2 模型提示与字段说明；不改变查询、模型、原材料、校验函数、重试和费用边界。

## 可证伪诊断

三轮首稿均为合法 JSON，却把完整实体名或实体/期间/指标拼接名写入 requested_subject，同时 question_quote 只引用不含实体名的共用指标子句。程序正确拒绝 subject 不在 quote 中。修订只改变问题锚点与 scope，不改变数据。契约不是逻辑不可满足，而是把局部原文锚点和完整语义身份称作同一主体，question_quote 又缺少字段说明，导致生成时两种含义混用。

本次明确：完整请求身份由原文锚点、维度、范围组成；模型先确定身份和连续锚点，再选包含锚点的问题引文，最后保留其他公司/期间等范围。三字段说明由同一份文本供模型 Schema 与提示使用。校验保持完全不变，既不自动补公司也不改引文。

## 验证与失败条件

1. 原 v2 三次首稿仍被严格校验拒绝，修订稿仍通过。独立合成案例验证跨子句主体、实体/期间网格、重复任务与历史 V1。
2. 冻结 v3，实现哈希相对 v2 仅审核契约文件变化。沿用 run_fresh.py 和同一财报数据，从零 R1/R2/R3；不把失败答案或人工选择传给运行 Agent。
3. 独立记录首次审核通过、协议修订、完整交付、公司/期间/币种/数值/精确出处、其他恢复、调用和费用。预期三次首次审核均通过且内容标准不退步；三次通过仅为当前小样本证据。
4. 如果仍有修订，保留失败并报告，不能继续叠提示或修改校验后把旧失败去掉；若发生其他失败，单独归因。

保留原账本及未知预留，沿用本任务 $3 增量护栏。v1+v2 已计 $1.1723694；剩余 $1.8276306。预计本轮约 $0.7，不额外调用顾问。不改变任务预算。

## 研究依据

- OpenAI [Function calling](https://developers.openai.com/api/docs/guides/function-calling)：明确参数语义，将已知工作交由程序；[Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)：结构正确仍可能有内容错误。
- Anthropic [Writing tools](https://www.anthropic.com/engineering/writing-tools-for-agents)：从真实轨迹找接口歧义，以独立评测衡量错误和成本。
- Google [Structured output](https://ai.google.dev/gemini-api/docs/structured-output)：明确字段说明并保留应用语义校验。

这些是设计依据，不是修复有效性的实测证明。
