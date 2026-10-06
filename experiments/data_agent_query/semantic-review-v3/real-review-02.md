# v3 第二轮真实语义复核：独立评测

运行 `semantic-loop-v3/real-run-02` 已结束，**运行接受 1/2，整体 partial**。共 5 次模型调用：3 次 proposal、2 次 critic。分部没有最终接受意见；Cloud 经有效 critic pass 后接受。机器明细与冻结产物哈希见 [real-evaluation-02.json](real-evaluation-02.json)。

本评测只读取实际输入、响应、拒绝及结果，沿用冻结 expected，不改 production、原始响应或 Gold，不追加模型请求。上一轮 `real-run-01` 的 4 次调用、0/2 接受原样保留：两个 critic 均因精确引文偏移错误被拒，不能追记为有效审查。

## 分部：有效 critic 不等于正确 critic

首个 proposal 因 `semantic context claim has duplicate or unknown object` 被拒。第二个 proposal 通过工程校验，critic 输出有效 revise，包含 3 个问题；此时 proposal 两次上限已耗尽，没有发生收到 critic 后的语义修订。因此本轮不能证明完整的“草稿—有效批评—修订—复审”循环跑通。

| critic 问题 | 独立评价 | 原因 |
|---|---|---|
| comparability_scope_omission | 部分合理，应收窄 | 12 条历史分部数据处于 FY2025 重述口径有据；“不是原始报告金额”可能暗示每条数值均改变，原文没有逐条桥接。应限定数值断言，不能否认整组重述口径。 |
| allocation_operating_income_scope | 误报 | 原回答已经说“营业利润受收入和成本分配影响”，没有说利润本身直接分配。critic 也承认这是合理推断，却要求纠正回答没有作出的更强主张。 |
| dimensions_total_scope | 可选补充，不构成 record_scope 错误 | 回答正确识别 Total 与无分部维度记录，没有否认 Total 为分部之和。显式补充加总关系有用，但任务轴未要求 additivity，不能据此认定已有范围错误。 |

分部对冻结 expected 的记录集合覆盖均满足：历史重述 12、合并例外 6、分配 18（收入 9 与营业利润 9 分开）、维度 24（三分部各 6、Total 6）。这只是集合覆盖，不代表整段语义或最终接受通过。维度引用同时包含收入和利润行；没有再出现将合并 Total 与分部求和互斥的错误。

独立复核还保留两处表述边界：营业利润约束提及收入分配，但该条附带引文仅涉及成本/费用，收入依据在同包其他约束；`relative gross margin` 被译成“相对毛利率”，所给原文未建立明确的百分比权重公式，宜保留原文术语或限定解释。当前没有原始披露对重述值的数值桥接，不能声称已完成跨报告逐值核对。

## Cloud：运行接受与独立评价一致

Cloud 首个 proposal 工程有效，critic 首次即输出有效 pass。独立检查两轴均准确覆盖全部 3 条 FY2025/FY2024/FY2023 记录，并引用完整两句原文：

- additivity 说明 Cloud 已包含于四个产品/服务类别，额外相加会重复计算。
- dimensions 保留 Microsoft 365 Commercial cloud、Azure and other cloud services、LinkedIn 的商业部分及 Dynamics 365 的构成，没有把完整产品行相加冒充 Cloud，也没有等同于 Intelligent Cloud 或 Azure 单项。

两个轴的完整段落引用支持金额、构成及重叠关系；未宣称已取得不存在的 Cloud 组件数值分解。故该有界案例独立评价为 pass。这不代表全文遗漏率或跨公司泛化已通过。

## 本轮能证明什么

新 critic 提示下，两份 critic 都成功通过协议校验，不再猜错偏移。但本轮没有触发 critic schema 重试，因此只能说具备该路径，不能以此运行证明重试已经实际成功。critic 对表格维度的普遍否认已有改善，仍存在把合理推断或补充建议升级为阻断问题的校准缺口。

下一步优先验证有真实有效批评的语义修订闭环，并保留 critic 被有据拒绝的情形；随后用冻结未见样例评估，不根据本轮响应改写 Gold。当前结果继续记为 partial，不能将独立评价覆盖回填成运行接受。
