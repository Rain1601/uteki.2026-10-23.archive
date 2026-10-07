# Microsoft 重提取：独立原文审阅清单

这份清单只用于审阅，不能放入生成模型输入。审阅者已完整读取冻结的 103 块，尚未读取新模型请求或产物；已知历史对话，因此不是严格盲测。

范围是 Microsoft FY2025 10-K 的 Operating Segments 全章节。它包括三个分部的主要业务及竞对说明，不等于整份财报、全部产品或最新官网。

## 核心判断

Azure、Azure AI、Azure AI Foundry、Azure Security、GitHub、Nuance 的关键原文已经齐备。图中孤立不自动说明报告没有依据。层级可以用可核验的上下文推断，但须标 derived，不能冒充逐字披露。GitHub / Nuance 整体与云子集必须分开；本地子集精确会计归属则确为本章节限制。

## 覆盖清单

| ID | 检查项 | 原文块序号 |
|---|---|---|
| C01 | 范围、期间和三个分部 | 6, 8, 86, 87 |
| C02 | Productivity and Business Processes 四条主线 | 91, 93, 95, 97, 99 |
| C03 | Microsoft 365 Commercial 云与本地范围 | 93, 101 |
| C04 | Microsoft 365 Consumer | 95, 103 |
| C05 | LinkedIn | 97, 108 |
| C06 | Dynamics | 99, 110 |
| C07 | Intelligent Cloud 两条主线 | 118, 120, 122 |
| C08 | Server products and cloud services 的云/服务器结构 | 120 |
| C09 | Azure 本体与产品能力 | 120, 127 |
| C10 | Azure AI | 127, 128 |
| C11 | Azure AI Foundry | 128 |
| C12 | Azure Security | 134 |
| C13 | GitHub 整体与云子集 | 120, 130 |
| C14 | Nuance Healthcare 整体与云子集 | 120, 130 |
| C15 | Enterprise and partner services | 122, 132 |
| C16 | More Personal Computing 三条主线 | 144, 146, 148, 150 |
| C17 | Windows and Devices | 146, 152, 171 |
| C18 | Gaming 和 Xbox | 148, 176, 177, 178 |
| C19 | Search and news advertising | 150, 180 |
| C20 | 竞对证据边界 | 112, 113, 114, 115, 116, 134, 135, 136, 140, 142, 182, 183, 184, 185 |
| C21 | 具名重要对象关系完整性 | 86, 93, 120, 128, 130, 134, 146, 148, 150 |
| C22 | 原文引用与主张一致 | 86, 93, 120, 128, 130, 134 |
| C23 | 未决事项逐条分类 | 88, 120, 128, 130 |
| C24 | 图上可见与覆盖一致 | 86, 93, 120, 128, 130, 134, 146, 148, 150 |
| C25 | 收入与精确财务分解不越界 | 88, 101, 103, 108, 110, 127, 129, 178 |

详细接受标准及逐字原文在同目录 JSON。没有固定节点数；不能用机械复制期望树评判模型。

## 未决事项怎么判

| 项 | 分类 | 结论 |
|---|---|---|
| U01 Azure 是否属于 Azure and other cloud services？ | `grounded_inference_available` | 组合名称加后续 Azure 定义支持业务范围推断。允许有据 derived；将其完全孤立属于分析缺口，不等于所选材料没有 Azure。 |
| U02 Azure AI、Foundry、Security 为什么孤立？ | `unresolved_analysis_if_unlinked` | 原文具名能力和平台定义齐全，须分析上下文层级。精确正式层级不是逐字披露；可用限定推断，不得把仅此局限升级为没有业务关系。 |
| U03 GitHub/Nuance 整体是否全部包含在云组？ | `false_premise_if_whole_equals_cloud` | 原文明确同时含云和本地，云子集可明示定位。整体等于云组是范围错误。 |
| U04 GitHub/Nuance 本地部署业务精确计入哪条财务线？ | `not_stated_in_selected_section` | 所选章节未明确其本地子项的精确会计归类。只声明本章节限制，不宣称整个 10-K 没有。 |
| U05 各个 AI/GitHub/Nuance 子项收入有多少？ | `outside_selected_evidence` | 本输入无数值表，且指向 Note 18。需要读取财务章节；即使读取后仍可能没有产品单列，不能提前称公司未披露。 |
| U06 Azure AI Factory 是什么？ | `name_correction` | 此输入的正确名字是 Azure AI Foundry。不能补造 Azure AI Factory；Azure Data Factory 不在所选块中。 |
| U07 能否据此画微软所有业务产品？ | `scope_limit` | 三个经营分部描述使用 primarily comprises；此输入能覆盖报告该章节的主要业务，不代表所有产品、内部组织或官网最新范围。 |
| U08 报告是否明确 Azure AI 和 Security 互为父子？ | `not_stated_in_selected_section` | 材料分别描述两类 offerings，无依据把 Security 归入 AI 或反向。各自与 Azure 品牌/业务可作限定推断；同品牌不等于同产品。 |

## 验收边界

- 格式有效、引文存在、内容正确、覆盖完整、关系解释清楚、图形可读分别判定。
- 重要业务无解释孤立、云子集等同整体、无据父子边、主要业务漏项不能 Pass。
- 可以用主图加子图，不必把所有细产品挤在一张图里。
- 收入数字未在输入中；不能补造，也不能提前宣称整个报告未披露。
- 用户的视觉验收保留独立状态，原文审阅不能替代。
