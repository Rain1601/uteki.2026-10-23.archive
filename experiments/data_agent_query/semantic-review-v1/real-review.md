# 两个真实语义复核案例的独立评测

依据已冻结的 [real-cases.json](real-cases.json)，检查 `data/company_workspace/record_review/semantic-quality-v1/real-run-01/result.json` 中每条约束的内容、引用和 affected-record 集合。原结果 SHA256：`bd08ea6440584f3e0663f6be3ada5ac3be6c8aab6bd632e0f1cd40b30bdce957`。

详细机器结果见 [real-evaluation.json](real-evaluation.json)。本次没有修改模型结果、候选事实或预期约束，没有追加模型调用。

## 结论

| 案例 | 独立结果 | 主要依据 |
|---|---|---|
| 分部表 24 条 | partial | 重述、合并例外和分摊已识别，但重述记录范围过宽，分摊未按指标拆分，Total 解释出现错误 |
| Microsoft Cloud 3 条 | pass | 明确收入重叠及不可加总，正确识别其组成与非报告分部属性，记录范围精确 |

整体为 **partial**。五个请求轴都返回 `constraints_found`，不等于五个轴的每项内容都正确。这里逐项判定：符合全部冻结要求才为 pass；有正确约束但仍存在缺口为 partial；明确错误的单条陈述为 fail。

## 分部案例

### comparability：重述主旨正确，记录范围需要修正

第一条约束引用 Note 1 和 Note 18，明确 2023/2024 分部数字已按 FY2025 构成重述。这比前次只核对数值的意见有实质进步。

但其陈述只讲 2023/2024，`record_ids` 却包含全部 18 条分部记录，比冻结要求的 12 条历史分部记录多了 6 条 FY2025 记录。例如 FY2025 收入 `obs-c9967bda56a0a08e2bdc7acf` 被归入该重述约束。应区分“当年现行分部口径”和“历史分部数字重编”，不能仅以广义相关性代替精确受影响范围。

第二条约束正确单列六条无维度 Total，并引用 `block-000818-3a2e0b27` 中合并报表不受本次重述影响的例外，判 pass。其“保持原报告口径”应限定为本次分部重述没有影响，不应外推为不存在任何其他历史变更。

### allocation：识别正确，收入与利润未分开

模型引用 `block-001211-94df82c9`、`block-001212-72e12aed`，指出相对价值、价格、成本加成等收入分配和按毛利/人数等分摊公司费用，正确否定将分部结果直接理解为独立经营实体经济结果。

但所有 18 条收入/营业利润使用同一条合并陈述，没有区分收入分配适用的 9 条收入记录，以及费用/公司成本分摊适用的 9 条营业利润记录。不能使陈述看起来像“收入金额本身包含公司成本”。依据冻结约束判 partial。

### dimensions：分部成员分组正确，Total 的排他表述错误

前三条分别绑定 Productivity and Business Processes、Intelligent Cloud、More Personal Computing 各六条记录，集合与原始维度一致。

第四条对六条 Total 声称：

> 无维度成员的总计记录对应合并报表口径，而非分部合计。

“合并口径”和“本表分部合计”并不互斥。`block-001217-90dfc72b` 的三个分部收入和营业利润在每年都精确相加为 Total。例如，单位百万美元：

- FY2025 收入：120,810 + 106,265 + 54,649 = 281,724。
- FY2025 营业利润：69,773 + 44,589 + 14,166 = 128,528。

FY2024、FY2023 同样成立，完整算式见机器评测。因此该单条约束判 fail；正确说法应保留“不是单个分部成员”，不能否定它同时是本表分部汇总。

## Cloud 案例

### additivity：pass

模型对三个 Cloud 记录精确给出同一约束，并引用 `block-001227-3bdf0315` 的 `These amounts are included in ...` 句，明确该收入已包含于四类产品/服务收入，不可重复相加。首轮数值复核遗漏的重叠语义现在已经落实到约束。

### dimensions：pass

模型引用完整组成句，其中包含 Microsoft 365 Commercial cloud、Azure and other cloud services、LinkedIn 的 commercial portion、Dynamics 365，并结合三个报告分部的来源句，区分 Microsoft Cloud 分组与 Intelligent Cloud 等报告分部。三个 affected-record ID 精确覆盖，未创造组件金额或把整行产品收入直接加成 Cloud 收入。

这是对当前来源中该分组的判断，不是通用分类法映射，也未独立重建 Cloud 各组件金额。

## 工程检查与范围限制

`python -m unittest tests.unit.test_semantic_review` 的 11 项检查通过，包含来源绑定、原 DOM 片段、记录/块/指标篡改、轴与断言覆盖、精确引用和禁止注入预期字段。这证明相关工程边界有效，不证明模型语义判断正确。

本次只有两个真实案例，没有提供 assertions，因而不能据此评估真实模型的断言反驳能力。没有评估全文提取遗漏率，也没有对原始历年报表或 Cloud 分项进行独立对账。评测是独立源文核对，不是全量 Gold 标注；候选事实及模型原意见均保持不变。
