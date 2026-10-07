# DRIVE Hyperion：官方产品补充小样

已完成一个真实、可核对的人工补充：给冻结 NVIDIA FY2025 候选的 `drive_hyperion` 节点补入 **1 个当前官方产品系列入口、2 项 To Watch 建议**。本轮没有模型调用、历史事实回填或持续监控，也没有更新已有验收页。

产物：[nvidia-drive-hyperion.json](nvidia-drive-hyperion.json)；[实际观察记录](observations.json)；[结构与绑定检查](verification.json)。它们使用已有 `official-product-enrichment-v1` 契约，不向 Workflow 增加必经阶段。

## 实际核对了什么

| 入口 | 本轮观察与采用范围 |
|---|---|
| [NVIDIA Hyperion 当前产品页](https://www.nvidia.com/en-us/solutions/autonomous-vehicles/drive-hyperion/) | 实际打开可读。主标题为 NVIDIA Hyperion，正文和规格表介绍该平台系列。页脚公司版权、公司介绍/投资者入口及联系表公司声明支持发布者身份核对。作为当前产品系列入口采用。 |
| [旧开发者 Hyperion 地址](https://developer.nvidia.com/drive/drive-hyperion) | 工具实际观察它转到 [DRIVE AGX Developer Kits](https://developer.nvidia.com/drive/agx)。对象是计算组件开发套件，因此保留为粒度不匹配的缺口，没有把它当作整个平台的独立文档。 |

检查时间为 **2026-10-07T08:58:39Z**。当前名称与原 FY2025 报告中的 DRIVE Hyperion 命名、版本内容存在时间差；产品系列匹配不证明当前版本与历史披露完全相同。官网性能、安全或适用范围保持厂商归属，本小样不独立证实这些声明。网页发布时间没有确认，记录为 `null`。

To Watch 关注两个问题：平台不同代际的计算/传感器/适用范围是否变化；平台组成和配套官方链接是否调整。两条都指向已实际核对的产品页，列出可观察的具体变化，并保持 `suggested`。没有声称这些变化已经发生。

## 来源与验收

- 绑定 [原冻结业务图](../2026-10-07-nvidia-business-revenue-v1/derived-01-single-fence/business_map.json)，SHA256 `bcebbd790caa9bb59be5de9a8a1ada0d31f8800d58a37bb68f2fcb6739f84ddd`；公司 `nvidia`、文档 `nvidia-fy2025-annual-report-10k`、报告期末 `2025-01-26`。
- 保存本轮使用的 [可选 Skill 快照](skill-snapshot.md) 和 [补充契约快照](enrichment-contract-snapshot.md)。这是 Codex 人工执行该方法，未声称系统 Agent 已自动发现入口。
- 既有校验器通过 scope / map hash / 节点 ID、无凭据 HTTPS、短摘录 hash、观察建议来源及状态检查。该检查不代替上面的人工发布者身份核对。
- 原图、原收入图、执行结果及旧补充样例均未修改。仅记录工具实际观察的最终地址；没有单独验证完整重定向链。短摘录 hash 不代表冻结了整张网页。

下一步：若显式选入此补充，可在既有节点详情展示；本轮没有触发页面重建或监控。
