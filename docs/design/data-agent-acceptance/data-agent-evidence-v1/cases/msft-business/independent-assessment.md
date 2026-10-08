# Microsoft 业务题 · v4 独立验收

**最终内容验收：通过。** 本轮重新读取并核对 msft-business-r5 的最终封存包。18 块、3,720 字符，完整交付三分部与 4／2／3 项主要业务列表；没有把整章或产品细节全集塞回。结论来自本次原件复核，不沿用 r4 的通过状态。

| 范围 | 核对结果 | 冻结块序号 |
|---|---|---|
| 三个报告分部 | PBP、Intelligent Cloud、MPC 齐全；FY2025 商业 Microsoft 365 归属调整说明保留 | 86、87 |
| PBP 四项 | Microsoft 365 Commercial、Consumer、LinkedIn、Dynamics；云端/本地和必要子项完整 | 90、91、93、95、97、99 |
| IC 两项 | Server products and cloud services + Enterprise and partner services。Azure/其他云服务的子集关系、GitHub/Nuance/虚拟桌面及服务器/服务列表保留 | 117、118、120、122 |
| MPC 三项 | Windows/Devices、Gaming、Search/news advertising；必要列举完整 | 143、144、146、148、150 |
| 限定与最小性 | 三处 primarily comprises 保留。标题和 44 字符过渡句 89 是轻量上下文；没有竞争段落、详细产品叙事或收入表混入 | 91、118、144 |

已逐块核对冻结原始 HTML 的唯一 DOM 路径、索引文本和 text hash；18 条整块引用均正确。最终模型 select_evidence 与 18 个交付 block ID 完全一致。整块引用无需猜测重复句位置。圆点 marker 块未交付不等于业务漏项；实质的 4／2／3 列表与引言全部在包内。

## 内容通过与运行稳定性分开

本 cycle 共 2 次尝试。第一轮达到 no_progress_limit，未选择最终证据，交付包为空；模型审阅正确拒绝，没有把未交付算作完成。第二轮收到同一系统审阅反馈后重新导航、阅读和选择，最终通过。

第一轮曾实际收到相关正文，但正文窗口和已读目录轮换、模型选错旧 artifact 造成反复读取。它是仍需修复的效率/可发现性问题；最终内容通过不能掩盖首次运行失败。具体证据和未实施的通用改进建议见 [导航诊断](../validation/msft-business-r5-navigation-review.md)。

## 独立性、来源与边界

原始调用输入只有公司/报告范围、问题、数据集与资源配置，没有 Codex 指定章节或 block。第二轮 feedback 与第一次冻结模型 assessment 完全一致。运行痕迹显示目录、阅读和筛选由系统模型完成；Codex 本轮只做封存后核验，未 API 调用、未改生产输入或原件。

采用隔离参考集检查语义，不强迫固定原文位置或不必要的参考超集。此次只验收 Data 原文交付；没有运行分析 Agent、没有产出/验收业务图，也不构成新公司泛化证明或人工用户验收。

来源：[Microsoft FY2025 SEC 10-K](https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630.htm)，报告标记页 5、6、8。

## 冻结绑定

- [运行结果](../runs/msft-business-r5/result.json)
- [最终原文包](../runs/msft-business-r5/attempt-02/review-01/input.json)
- [最终模型审阅](../runs/msft-business-r5/attempt-02/review-01/result.json)
- [完整逐块核验 JSON](msft-business-v4-review.json)
- Packet ID：`data-review-f4932e12c4ac670c1963fda0`
- Packet 文件 SHA-256：`40a7effe840aeb2f641eb320590cc2d0dba6b714215bcc057717fd1659d2f8b6`
- Cycle manifest SHA-256：`9cfb373a9b9e271e080879bc7b146763080156a067424ac54e30b19baa5ef6ae`
- Query manifest SHA-256：`9da7eecfa34a655e2c29b8433968e5ec69acb5af93ba892c9a6818098022e4c1`
- Review manifest SHA-256：`94a59736c4f1cdfde18029f647552322f9b48bd30e3684a9d33e885b78804bb2`

已验证 cycle、两次 query/coordinator/review 与 dataset 的冻结 manifest。下一步：独立检查本轮 Microsoft Cloud 口径题；另保留已读目录分页问题作为工程待办。
