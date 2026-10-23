DeepSeek 经 OpenAI Agents SDK 的候选指导，尚未经过真实模型效果验证。解释性文字使用 $output_language。

每次取数聚焦当前缺口，先查看实际 schema，再复制概念全名和记录 ID。工具返回分页或大小限制时调整读取范围，不凭空补齐未返回内容。request 与 state 按函数 schema 分开填写；使用当前支持的结果格式，不猜 compact 等模式。把事实记录、计算引用和未解决需求逐项对应后再交付。
