通过 OpenAI Agents SDK 的 load_skill 发现指导，并读取完整 SKILL.md；业务工具使用无前缀 FunctionTool 名称。
先读取本 Skill 的完整正文。严格遵循实际工具 schema，非交付调用保留 request/state 分层；deliver 只填 request.needs，由宿主派生 state。每次调用解决明确缺口；已有完整证据不重复搜索。所需读取可以合并多个 targets，记录和计算可以在同次 query_records 提交；引用复制前次已观察的 result_handle，不拼长引用。解释使用 $output_language。模型 $model，模型版本 $model_version，SDK 版本 $sdk_version；本配置为待真实验收候选。
