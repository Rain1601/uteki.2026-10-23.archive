# Microsoft FY2025 原件评测标准候选

本轮做的是：先从原文确定“回答问题至少需要什么”，供随后检查系统 Agent 的交付。还没有把候选标准当作已冻结真值，也没有据此给新运行打分。

本目录只能用于评测。其段落位置、候选答案和覆盖标签不得进入生产查询、Agent 提示词或候选章节选择。

## 阅读来源与独立性

原件是 Microsoft FY2025 10-K，报告期截至 2025-06-30，2025-07-30 发布。来源：[SEC 原件](https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630.htm)。本地冻结原件：[msft-2025-10k.html](../../../2026-10-09-data-agent-completion-v1/datasets/msft/raw/msft-2025-10k.html)。

SHA256：`0edfaac937bf7042c8cf7901924ccb9cc291ccfab92f83dd0b689b7912089bf6`。

本子任务没有打开系统 Agent 的结果或旧评语。但是继承的任务上下文已含历史结果摘要，所以本轮是**重新以原件构建标准，不能声称完全盲审**。候选标准仍需根 Agent 对照原件复查后冻结。

读取了 199 个原始 HTML 节点，覆盖 Item 1 分部列表及邻近产品/竞争说明、MD&A 指标定义和增长、利润表、Note 1 会计与重列、Note 18 分部及地理/产品表。导航使用现成 DOM 路径，引用从原件重新读取；本轮 199 处文本都与索引文本一致。`reference.json` 内保存完整原文、DOM 路径、原件锚点、候选块 ID 和部分精确字符区间。

另外扫描全篇中 `Azure`、`recast`、`245,122`、`Microsoft Cloud`、`Intelligent Cloud`、`75 billion` 的匹配位置，并回到原节点查证。关键词查找用于发现旁证和反例，不等于逐字读完全文。`75 billion` 的唯一字面命中实际在 `$375 billion` RPO 段中，不是 Azure 收入。

## E1-02：FY2025 年报比较列里的 FY2024 总收入

**问题：**请仅依据 Microsoft FY2025 10-K 中的比较披露，提供 FY2024 公司总收入及单位、财年起止和原文出处；不要求分析增长。

**预期：**FY2024 合并总收入为 **USD 245,122 million**，期间是 **2023-07-01 至 2024-06-30**。这里读的是 FY2025 原件内的比较披露，不是声称已取得 FY2024 原件。

| 必须保留 | 为什么不能删 | 已检查的可接受出处 |
|---|---|---|
| Total revenue 行、FY2024 列、金额和单位 | 裸数字不知道是总额、分部还是哪个年 | 利润表 E0781；Note 18 分部合计 E1217 |
| 财年期间 | 防止把 FY2024 当自然年或季度 | 表头 Year Ended June 30 加原记录的 XBRL 期间或已验证的等价元数据 |
| FY2025 原件身份及引用 | 保证使用题目指定披露版本 | 来源快照、原件 SHA、具体表格位置 |

另一组等价出处也成立：地理收入表 **E1218+E1219**，或产品服务收入表 **E1225+E1226**。这里前一个段落说明表格统计的是收入；只拿后面的 `Total` 行而丢掉收入身份不充分。MD&A 汇总表 E0572、分部表 E0587 也可用，但需补全 June 30 财年期间。

精确期间直接核对原件 Inline XBRL：收入标签为 `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`，值 `245,122`，`scale=6`，单位 `U_USD`。其 context 的起止日期为 `2023-07-01`、`2024-06-30`，issuer 为 `0000789019`，没有额外分部维度。JSON 保存了原始 context XML。

**必需脚注检查：**利润表该总收入行没有单独脚注标记。`Refer to accompanying notes` 不代表必须交付全部会计政策。地理表的 `(a)` 附在 United States 行，解释 OEM 地理分配；只回答总收入时不强制附这段。

**条件性上下文：**如果要解释跨年重列，Note 1 的 E0817 说明重列分部口径，E0818 明确不影响合并资产负债表、利润表、现金流量表。这两段有用，但一个数字题不要求主动追加它们。如果没有讲重列，不因未取这些段落扣分。

**什么算多：**六处收入合计全部重复交付；整份会计政策；云产品介绍；分部增长分析。完整利润表随带其他行属于当前表格粒度的附带内容，需要与主动检索来的无关材料分开统计。

## E1-05：三个报告分部及核心业务

**问题：**请依据 Microsoft FY2025 10-K，提供三个报告分部及各自核心业务的原始材料，保留所属关系与必要限定，不要求所有产品清单。

预期是三个分部、九个顶层业务组合。不是尽可能多列产品。

| 报告分部 | 至少要覆盖的核心组合 | 可选等价来源 |
|---|---|---|
| Productivity and Business Processes | Microsoft 365 Commercial、Microsoft 365 Consumer、LinkedIn、Dynamics | Item 1 E0090–E0099 中说明与四条列表，或 Note 18 E1184–E1193 同样内容 |
| Intelligent Cloud | Server products and cloud services（包括 Azure and other cloud services 与 Server products）；Enterprise and partner services | Item 1 E0117–E0122，或 Note 18 E1197–E1202 |
| More Personal Computing | Windows and Devices、Gaming、Search and news advertising | Item 1 E0143–E0150，或 Note 18 E1203–E1210 |

还需保留三者“报告分部”的身份，可来自 E0086、E0550 或 E1181。可靠的章节归属或结构化元数据可替代重复标题块；不强制把每个标题、每个独立圆点都作为额外命中。

**为什么这些是必需：**PBP 四项少任何一项，会遗漏其一个顶层组合。Intelligent Cloud 只给 Azure，会漏服务器产品及企业伙伴服务。MPC 只给 Windows 或 Xbox，会漏其他顶层组合。只给金额分类表不能充分说明这些归属。

**什么不强制：**每个小产品、每个功能都单独展开；Azure AI Foundry；全段竞争；全部增长驱动；收入和利润金额。原文一条完整列表里附带 Teams、Security 等例子可以接受，但不由此增加更多独立强制节点。

**什么时候补上下文：**如果交付涉及 FY2024 与 FY2025 的分部比较，则必须保留口径重列说明。若只说 FY2025 分部现状，不强制把重列解释加到最小包里。特别不能把所有 Windows 产品一概归 MPC；原文明确把部分 Windows Commercial 放在 PBP 商业组合。

## E1-06：三种“云”口径

**问题：**请依据 Microsoft FY2025 10-K，提供 Microsoft Cloud、Intelligent Cloud 与 Azure 的口径定义及 FY2025 对应披露指标，明确金额/增长率差异，不推算未披露 Azure 收入。

| 对象 | 需要的数据与范围 | 原文位置 |
|---|---|---|
| Microsoft Cloud | M365 Commercial cloud、Azure and other cloud services、LinkedIn 商业部分、Dynamics 365；FY2025 **$168.9 billion** | E1227；E0561 只能替代定义部分，不能替代金额 |
| Intelligent Cloud | 一个报告分部，包括 Server products and cloud services、Enterprise and partner services；FY2025 **$106,265 million** | E0117–E0122 或 E1197–E1202；数字 E1217 或补足期间的 E0587 |
| Azure | 云服务平台，供开发、部署和管理应用；消费型 IaaS/PaaS 影响其收入 | E0127 |
| Azure and other cloud services 指标 | 除 Azure 相关 cloud/AI consumption 外，还含 GitHub cloud、Nuance Healthcare cloud、virtual desktop 等；FY2025 披露收入增速 **34%** | 组成 E0120 / E1200 / E0564；增速 E0613 |

“Azure 产品平台”与“Azure and other cloud services 财务组合”要分别交代。不能给 Azure 起一个精确收入金额，也不能把 `Server products and cloud services` 的 $98,435 million 当作它的收入。

题目只问 FY2025，因此 FY2024 对应金额不是强制项。同表/同段天然包含比较年时允许保留。若主动解释 FY2024 分部比较，重列限定就成为必需。

**必要关系：**Microsoft Cloud 跨业务组合，Intelligent Cloud 是分部，Azure 位于其中的云服务范围。需要这些原文定义来支持“有重叠，不能直接相加”；不要求原文恰好写出“不可相加”四个字，也不要求单独生成分析报告。

**负面查找的边界：**在本原件所查 Azure 全文命中、业务说明、指标定义、MD&A 和 Note 18 数字中，没有发现单列 Azure 或 Azure and other cloud services 的绝对收入金额。不能把这个结论扩大成“公司从未在任何官方渠道披露”。原件之外的新闻稿等不在此题范围。

**什么算多：**全部 PBP/MPC 产品说明、Azure 竞争战略、整个云毛利及费用讨论、多次重复定义。它们与“区分口径并给出 FY2025 指标”无直接增量。

## 评分前的边界

1. 按语义要点覆盖评分，接受等价原文。候选块 ID 帮助定位，不是唯一答案。
2. 必需缺失和事实/口径错误分别报告。可选材料再多不能弥补必需缺失。
3. 每条多余材料写明删掉后为什么不影响回答；区分主动冗余、同义重复、完整原块附带上下文。
4. 先检查来源和期间，再统计覆盖，避免错年份的“命中”被算成功。
5. 命中与冗余都需要原文人工复核。此候选没有绝对最短字符数阈值，也不声称它是唯一最优材料集合。
6. 当前范围局限于此份 FY2025 原件。跨 FY2024 原件、不同材料、未知公司迁移由其他验收关单独验证。

机器标准：[reference.json](reference.json)。辅助导出器：[build_reference.py](build_reference.py)。导出器不判定答案质量，只验证原件路径和保存上述人工语义判断。

## 新采集原件的绑定复核

后续系统重新获取的 FY2025 原件 SHA 为 `56d41ecc0adc114c7fcda813d41f5911b244a7e448b545f6dca52dfba9801008`，source ID 为 `source-360182cbf562dcf9a8ab9c4e`。旧参考与旧 SHA 完整保留在 `reference.json`；请对新数据集使用 [reference-revalidated.json](reference-revalidated.json)。

复核结果：199 个原始 DOM 定位及新索引文字完全一致，三个原始收入标签和 XBRL 期间也一致。整个原始 DOM 仅 script 的 src 属性不同；去掉该属性后 DOM 序列化结果完全一致。没有修改任一原始文件，也没有把两份原件 SHA 当成同一个 SHA。差异和逐位置核对见 [source-binding-revalidation.json](source-binding-revalidation.json)。
