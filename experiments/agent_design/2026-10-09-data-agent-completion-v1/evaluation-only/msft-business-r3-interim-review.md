# Microsoft business r3 / attempt 02 独立中间审阅

**离线结论：必要业务内容已经完整交付；当前 `needs_revision` 主要是列表结束依据没有清楚交接，以及 reviewer 对结构上下文的判断前后不一致。并非再次发现遗漏一项主要业务。** 这是 Codex 事后审阅，不覆写 reviewer 结论，不传入运行模型；没有干预正在运行的 attempt 03。

输入为 [attempt-02/review-packet.json](../runs/msft-business-r3/attempt-02/review-packet.json)，SHA-256 `59f3b0805bd4b0a4b8f302eacbdb6dd1ce8e911948c4463eeda6d447fbae1fe1`。包有 17 个 facts、45 个 source blocks，文件 63,122 字节。45 块均逐字段等于冻结解析块；重新计算原件 SHA-256，匹配 `0edfaac937bf7042c8cf7901924ccb9cc291ccfab92f83dd0b689b7912089bf6`。原 DOM 核对依据见本轮 [preparation-review](../preparation-review/README.md)。

## 1. 内容是否够回答

| 必要语义 | 实际交付 | 独立判断 |
|---|---|---|
| 三个报告分部名称 | 86 | 齐全 |
| Productivity and Business Processes | 90–99：标题、`primarily comprises`、4 条含子项目的正文 | 齐全：Microsoft 365 Commercial、Consumer、LinkedIn、Dynamics；没有丢 cloud/on-premises 等限定 |
| Intelligent Cloud | 117–122：标题、限定、2 条完整正文 | 齐全：Server products/cloud 与 Enterprise/partner services；Azure、GitHub、Nuance、服务器和服务子项均在原段落内 |
| More Personal Computing | 143–150：标题、限定、3 条完整正文 | 齐全：Windows/Devices、Gaming、Search/news advertising 及子项 |

完整指该报告明确列出的 **主要业务清单**，不意味着公司每项产品和所有经济联系均穷尽。仅由 Item 1 即可回答该题，不必强制重复交付 Note 18。FY2025 的来源身份已固定；若最终结论讨论历年分部重划，才需另外引入相应比较口径说明。

## 2. 两轮 reviewer 的变化

[attempt 01 审阅](../runs/msft-business-r3/attempt-01/review-01/model/review-0001-parsed.json) 认为全部三组清单完整、`question_coverage=complete`，但要求删除 100/126/131 等“无关”子标题及产品详细叙述。

[attempt 02 审阅](../runs/msft-business-r3/attempt-02/review-01/model/review-0001-parsed.json) 认为所有事实均支持，却因 PBP/IC 未附末项后的块，不能证明清单结束，要求补 100/123；同时承认 151 可作为 MPC 结束依据。这不是内容事实冲突，而是 **边界上下文没有稳定角色**。100 作为独立业务事实确实没有新增内容，但作为上一列表的结束见证是合理上下文；同类结构不能本轮强删、下轮再强补。

另有一项 reviewer 事实性失误：它称 bullet-marker blocks 未交付，但 source_documents 实际含 92/94/96/98、119/121、145/147/149。它们没有独立 facts，不等于原始材料未交付。评审应区分选择事实与附带原文。

## 3. 现有 reading group 能证明什么

Data 的原始 [evidence-bundle](../runs/msft-business-r3/attempt-02/data-query/query/evidence-bundle.json) 对应 context artifact 保存了 `reading_group_version=reading-groups-v0.4`、group 成员、marker→body 关联和 next_block_id：

- PBP：group 90–99，4 个 items，next=100。
- IC：group 117–122，2 个 items，next=123。
- MPC：group 143–150，3 个 items，next=151。

这些由对冻结全块序列运行的确定性规则生成，可以证明当前规则识别的连续列表及成员集合；**不能等同于全报告语义穷尽证明**。现有元数据没有显式列出停止原因、跳过布局块后首个非列表元素及其结构身份。

实际交接在 `answer_handoff.py` 的 selected 原文重建中只保留了 blocks；没有把 reading_groups、next_block_id 或其版本传入 review packet。Reviewer 看到的是散列片段，无法检查 Data 已有的列表结构证明。

对 IC，原件 123 是页码“6”，124/125 是运行页眉，126 才是下一业务详述标题。**只补 123 并不能证明结束**：列表可能跨页继续。通用规则必须跳过布局元素，并区分真实下一节与跨页延续，不能把下一页码当闭合依据。

## 4. 真实冗余在哪里

Attempt 02 选择 151 作为 MPC 的边界标题，交接程序通过 read_context 原子扩展出了 **151–170 共 20 块**：Windows OEM 收入影响因素的另一组 9 项列表。152 和其后各因素属于下一节业务细节，不是本题主业务清单的必要支持。151 本身可以是合理边界见证，却不应因此让下一整组内容成为边界附件。

所以删去几段 narrative 不代表整个交付包更小或更相关。评审只检查 17 个 facts 的 relevance，容易漏掉 source_documents 中未入 facts 的结构扩展。必要单位、脚注、列表介绍仍应保留；这处额外因素列表与这些必要附件不同。

Attempt 01 中 101/127/129/132 等增长驱动和详细功能描述大多属于可删冗余。130 的 cloud/on-premises 区分可作补充，但原清单已足以回答本题；131 属另一细节小节标题，不是最近列表边界。不要把所有 heading 一律当无关，也不要把每个 heading 自动当新事实。

## 5. 最小通用改进建议（未实施）

1. **让经过原件验证的结构关系进入交接契约。** 保留完整选中 reading group 的版本、成员、关联依据、结构闭合状态/停止原因；未知闭合明确标 unknown。若要给边界见证，只附必要原元素的身份/文字及哈希。语义完整性依旧由 reviewer 判，不能把 `group_complete` 当作所有业务已完整。
2. **区分事实、必要原子上下文、边界见证。** 边界标题不触发下一整个原子组的递归展开；缺单位/脚注不能被这个优化绕过。截断列表、跨页延续、legal-node 边界等用独立合成测试验证，不写公司特例。
3. **评审同时核查最终完整交付与最小性。** 已齐全但有无害冗余可作为非阻断改进；阻断应指出具体缺失业务/限定或无法验证的结构条件。记录修订前后的具体证据差异，避免把同一边界标题反复判“删除/必需”。不要通过放宽规则让真的漏项通过。

当前 attempt 02 可在“必要业务内容充分”这一离线维度通过；结构闭合证据的可检查性仍需工程补强。最终阶段状态应等自动运行结束，再分别报告模型审核结果、程序契约检查和这份独立内容判断，不能追改历史失败为成功。

## 6. r3 最终版本补充核验

运行最终指向 **attempt 03 / review 02**，不是该 attempt 的第一次无效格式审阅。最终终态为 `reviewed_data_ready`，review 02 为 `reviewed` / `analysis_eligible=true`，缺失信息为空。其 review manifest SHA-256 为 `44d150465e18be4fac4f3dcf79d1d2aa241b621ce5516968f85517a9722b9b28`。

最终 [review-packet](../runs/msft-business-r3/attempt-03/review-packet.json) SHA-256 为 `1de8613323ec685a4df2b6faac678abb5c69c7d2f1511edb021064b3e39fca96`，19 facts、47 原文块。与 attempt 02 相比，增加了 PBP 后的标题 100 和 IC 后的页码 123；主要业务内容没有新增缺项。上述三组 4/2/3 条内容和限定仍完整，离线内容充分性通过。

最终 reviewer 把 123 页码描述为“weak boundary context…harmless”，但这个页码独自不能证明跨页列表闭合。下一阶段应由通用结构元数据解决可检查性，不应依赖模型将页码改判为支撑上下文才放行。此前的 151–170 额外 Windows 因素组仍在交付包内，因此最终最小性仍有改进空间。

已用当前兼容逻辑重新构建 attempt 02、03 的 v1 packet，逐字段相等。后续 v2 改进不得追改这些历史输入或把新契约的验证追认为这次运行已执行。
