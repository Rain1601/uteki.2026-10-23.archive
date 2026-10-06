# 相同回复的调用链核对

当前离线验证未发现 feedback 丢失或本地旧回复替换。**真实模型为何原样返回失败稿仍未确定**，不能归因于 provider 缓存故障。

检查链路：

1. [SdkRecordReviewer](../../../src/uteki/agents/data_query/record_review_model.py) 将完整 packet 序列化后传给 `Runner.run`，每次请求前清空原始响应字段。
2. [DeepSeek 适配器](../../../src/uteki/agents/runtime/deepseek_model.py) 保留 input，仅设置 JSON mode、schema 指令及模型选项；从新 HTTP 响应中取得文本与元数据。
3. 已安装 SDK 将 system 和 user 消息传入 `chat.completions.create`。源码未见读取历史 raw/parsed 文件作为新输出的路径。
4. [continuation harness](continue_rejected.py) 只有第一稿显式重放旧响应；第二稿调用真实 reviewer，不替换其结果。

独立代理用两个 continuation 的实际归档 packet 和对应 prompt，经真实 reviewer、Runner、适配器和 AsyncOpenAI 的 `HTTP MockTransport` 各运行两次，共四次全离线检查。临时模拟账本与真实账本分开，**零外部模型请求**：

- 最终 HTTP 请求包含 system、user 两条消息，user 逐字等于完整 packet JSON，feedback 所有字段保留。
- continuation-02 新增的通用第 9 步完整进入 system。
- mock 返回不同内容/ID 时，归档 raw_text 和 final_output 也不同，未复用旧稿。

真实归档显示原始返回 SHA256 均为 `ec1690b874bd52e71259c4db8aa223e5fa3712fc23138dd97a90083e403b111f`，两次新请求 response ID 不同；input tokens 为 8,518 和 8,719。provider 返回的输入缓存命中数为 5,504 和 1,152；这是输入缓存信息，不能推断输出被缓存。

没有历史完整 HTTP 报文或服务端记录，因此上述离线检查不能证明历史服务端的实际接收/处理行为。可确认的现象是：当前调用链完整传递反馈，新模型请求仍返回同稿。下一步应在明确新增调用范围后，对消息组织及模型配置做小规模对照，继续保留失败；不能通过直接改答案或放松引用要求制造通过。
