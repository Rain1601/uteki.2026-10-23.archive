# E1-05：三个报告分部的取材验收

**内容齐全、所属正确；独立验收未通过，原因是仍交付了可整块删除的多余材料。** 系统第二次自审已经放行，但不代替这次独立验收。

问题：只依据 Microsoft FY2025 10-K，提供三个报告分部及各自核心业务的原始材料，保留所属关系与必要限定，不要求所有产品清单。

| 必需内容 | 实际材料 | 判断 |
|---|---|---|
| 三个分部身份 | 原件明确 PBP、Intelligent Cloud、More Personal Computing | 通过 |
| PBP 四组 | Microsoft 365 Commercial、Microsoft 365 Consumer、LinkedIn、Dynamics | 通过 |
| Intelligent Cloud 两组 | Server products and cloud services；Enterprise and partner services。前者同时含 Azure and other cloud services 和服务器产品 | 通过 |
| More Personal Computing 三组 | Windows and Devices、Gaming、Search and news advertising | 通过 |

我回读原件的交付段落、相邻业务说明和 Note 18 替代列表。四项必需语义全部覆盖，没有发现遗漏九个顶层业务组合。Windows Commercial 的云及本地部分明确在 PBP；MPC 的 Windows 明确是 OEM 授权。没有把 Microsoft Cloud、GitHub 或 Azure AI Foundry 提升为独立报告分部。列表和标题共同保留归属，无需每个子产品新增一个节点。

**多了什么：** `block-000087-44aabdcd` 是 490 字符的 2024 年 8 月重组历史。此题没有跨年比较、FY2024 分部金额，也没有要求解释归属变化。冻结标准里的“条件性必需”没有触发。删掉这一整段，三个分部、九组业务和当前归属仍然齐全。它因此使聚焦检查失败。另有 320 字符的管理目的说明可压缩，删除不会损害分部身份。不能用“原段落保留”替这些额外内容兜底；冻结许可针对必需列表里的细产品名。

正文共 **3,720 字符、18 块**：1,323 字符直接支撑必需内容；1,587 字符是列表内更细的产品说明、连接词及引导句；810 字符是上述管理说明和重组历史。评分字段 `necessary_context` 用来承载第二类，但不表示所有细节都不可删。没有重复整份 Note 18，没有整段额外竞对、增长或 AI 战略材料。最小充分材料目标尚未达到，不称结果已完成用户最终目标。

过程方面：第一次审核在 API 完整返回后遇到协议校验失败，第二次审核通过。因此系统状态是 `reviewed_data_ready`，而独立内容评分的 `focus=fail`、总结果为 `fail`。本轮共 **17 次模型调用**，输入 661,307 Token，输出 17,003 Token，公开价格估算 **$1.492644**，未知费用预留 0。包含第一次失败审核的 **$0.081578** 和第二次审核的 **$0.093618**。这是估算，不是最终结算账单。交付 packet 文件 **56,650 字节**，与 3,720 正文字符不是同一计量对象。

下一步只需让系统按原问题复核必要性、去掉无触发条件的历史段，并保留原输入与前后选择记录；不需要补材料，也不需要 Codex 代选最终正文。

检查入口：[逐项评价](review.json)、[评分](score.json)、[原件阅读与费用核对](original-check.json)。标准来自运行前冻结的 E1-05-v1，未修改。评审者有历史摘要暴露，不称完全盲审；本次也不是整份财报解析质量的全面验收。
