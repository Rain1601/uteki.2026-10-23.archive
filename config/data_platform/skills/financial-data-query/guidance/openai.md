这是 OpenAI Agents SDK 的默认指导，尚未针对当前模型调优。解释性文字使用 $output_language。

通过宿主注册的函数工具传递结构化参数。参考文件中的 request 和 state 是同一次调用的不同字段；根据实际 schema 填写，不把整个 JSON 当作自然语言消息发送。以函数返回的引用和状态作为下一步输入；普通 assistant 文本结束不等于业务交付已提交。
