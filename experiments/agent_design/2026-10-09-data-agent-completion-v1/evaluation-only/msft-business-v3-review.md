# Microsoft 业务题 · v3 独立验收

**结论：通过本题的数据交付验收。** 系统独立选材、阅读、筛选并根据模型审阅修订一次，最终交付 18 块、3,720 字符的原文。它足以回答 FY2025 三个报告分部及主要业务；没有塞入整个业务章节。

这是 Codex 对冻结原件的独立检查，与 Sonnet 审阅状态分别记录。未进行人工用户验收，也没有调用分析 Agent 生成业务图或报告。这个案例属于已知材料上的调试矩阵，不是新公司的泛化证明。

| 核对项 | 结果 | 原文位置 |
|---|---|---|
| 三个报告分部与 FY2025 口径 | 通过；保留商业 Microsoft 365 重新归入 PBP 的调整说明 | 86、87 |
| Productivity and Business Processes | 4 项完整：Microsoft 365 Commercial、Consumer、LinkedIn、Dynamics；云端/本地及所列子项保留 | 90、91、93、95、97、99 |
| Intelligent Cloud | 2 项完整：Server products and cloud services；Enterprise and partner services。Azure/other cloud 下的 GitHub cloud、Nuance Healthcare cloud 等仍在正确层级 | 117、118、120、122 |
| More Personal Computing | 3 项完整：Windows and Devices、Gaming、Search and news advertising；各项必要子列表保留 | 143、144、146、148、150 |
| 列表限定 | 三处均保留 “primarily comprises”，不把主要业务解释为全部产品 | 91、118、144 |
| 精确引用 | 18/18 块与冻结索引、原 HTML 的唯一 DOM 路径及 text hash 一致；18 条整块引用全部一致 | [逐块核对记录](msft-business-v3-review.json) |

原材料：[Microsoft FY2025 SEC 10-K](https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630.htm)。以上数字是冻结索引的块序号，不是财报页码。交付原文位于报告标记页 5、6、8。

## 最小性与非阻塞说明

本次保留三个标题和 41 字符的过渡句（89），便于识别列表所属分部。它们不是有害噪声；这份包是有界、充分的原文集合，但不声称字符数的数学最小值。没有竞争段落、产品详细介绍或收入表混入。

reading-group 的 `all_group_blocks_delivered` / `all_required_blocks_delivered` 仍为 false，因为没有传递单独的九个圆点标记块。已直接核对原 HTML：这些块只有 `•`；4/2/3 个实质列表正文、引言和限定全部存在。它不构成本题缺项，但机器元数据未来可以更清楚区分标记与正文。

验收按原问题所需语义进行。没有要求把隔离参考集当作固定 block 清单，也没有强迫加载整章或所有产品详情。

## 运行职责与修订

原始输入只固定公司、报告、问题、数据集和限额，没有人工指定章节或 block。第一次由系统执行目录、搜索、分段阅读和原文筛选；模型审阅确认内容完整，要求删除 Note 18 的冗余跳转提示（88）。第二次输入中的反馈与第一次冻结模型 assessment 完全一致。

最终运行轨迹为：加载 Skill → 规划 → 查看目录 → 三次读取原文 → 选择交付 → 结束。模型选择记录与最终 18 块相符。最终输入保留来源和全部原始限定，Codex 没有替系统选材或修改运行结果。本轮 Codex 只核验已封存的输出；没有 API 请求。

## 冻结绑定

- 运行：[msft-business-r4/result.json](../runs/msft-business-r4/result.json)，共 2 次尝试、1 次修订。
- 最终原文包：[attempt-02/review-01/input.json](../runs/msft-business-r4/attempt-02/review-01/input.json)。
- 最终模型审阅：[result.json](../runs/msft-business-r4/attempt-02/review-01/result.json)。
- Packet ID：`data-review-42c9d67ce514b736b6df6c30`。
- Packet 文件 SHA-256：`050707f6d5dcc33080943cf7458019f68bc48506ee9e91158fef0c8c3a30d822`。
- Cycle manifest SHA-256：`cf48040457e38a37c4e8578a4d06a5851dc0b03e0f288d620d72900b6f4ebc67`。
- Final query manifest SHA-256：`ff8b4dd8536903160a06c0b9f8bf597d1284a944813d142cc41c65c49c3b3057`。
- Final review manifest SHA-256：`d29911787a4effe6a24b4fc2f6e6704130f33157212508a970ec6c28f5b670c4`。

完整 hash、来源、逐块 DOM 检查和运行轨迹见 [机器可读验收记录](msft-business-v3-review.json)。已校验 cycle、各次 query/coordinator/review、dataset 的冻结 manifest；本检查未改动这些文件。

下一步：继续六题矩阵其他题的独立内容验收。本题无需额外模型重跑。
