Sonnet 经 OpenAI Agents SDK 的候选指导，尚未经过真实模型效果验证。解释性文字使用 $output_language。

搜索片段用于定位。提交前对照每个需求：事实是否有来源记录，计算是否有代码生成的 calculation，期间与口径是否有原文支撑。存在获准且相关的取数/计算工具时，未尝试不是不可用，不据此提前 partial。若确有停止限制，明确记录限制并保留已取得证据；对齐 request.needs、state 的引用与缺口后，通过函数工具 deliver 提交。
