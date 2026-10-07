# NVIDIA FY2025 受限迁移小试：预先验收标准

本文件供 Codex 审阅真实结果使用，不进入模型 input、system prompt 或 Skill。当前尚无模型结果。依据为冻结官方 PDF 与本实验原文包；旧人工图只作背景，不是固定答案。

本次检验 Uteki + 显式 Skill v0.4 能否从另一公司的已选原文产出可消费的业务数据及收入图。NVIDIA 曾用于人工参考图，因此这是跨公司迁移小试，不是完全未见盲留出，也不是与 Alphabet 的严格模型 A/B。

| ID | 验收点 | 通过例 / 需要避免的问题 | 精确原文位置 |
|---|---|---|---|
| NV-01 | 财年、原件与调用一致 | NVIDIA FY2025 截至 2025-01-26；不把 Calendar 2025 或前一列作为目标。记录 source/Skill/request hash，原文 PDF 与派生 HTML hash 分开。 | `pdf-block-000818-e9d259bf`、`pdf-block-001430-b4b615e6`；收入表头 `cell-table-pdf133-revenue-r001-c001`、`cell-table-pdf172-markets-r001-c001` |
| NV-02 | 报告分部与市场分开 | Compute & Networking、Graphics 是两报告分部；Data Center、Gaming、Professional Visualization、Automotive 是市场维度。All Other 为未分摊费用分类，不能随意设成第三报告分部。 | `pdf-block-000857-8c01a130`、`pdf-block-000858-fd83bcde`、`pdf-block-000859-b8b15350`、`pdf-block-000860-b924449f`、`pdf-block-001687-e27532ac` |
| NV-03 | 具名业务可消费 | 输入明确描述的核心具名对象可独立理解或查询；不要求节点数固定。不用市场名或收入类别代替所有产品身份，不把多个收费不同的产品混成一个无法展开的对象。 | `pdf-block-000862-54188d9a`、`pdf-block-000863-916beda4`、`pdf-block-000869-03a707ef`、`pdf-block-000873-d85d83ed`、`pdf-block-000877-3df8e1b3`、`pdf-block-000880-4bf3817c` |
| NV-04 | 跨业务关系准确 | 自动驾驶平台与汽车信息娱乐平台的报告归属区分；Omniverse 只有一个业务身份，既保留 Graphics 报告归属，也可用有证据的支持关系说明汽车仿真用途。CUDA 是共用技术，不因不同市场重复造独立公司。 | `pdf-block-000845-97f1689d`、`pdf-block-000858-fd83bcde`、`pdf-block-000859-b8b15350`、`pdf-block-000877-3df8e1b3`、`pdf-block-000881-d5b542b2` |
| NV-05 | 客户与赚钱方式有直接出处 | 节点描述、客户和收费方式所引片段应直接支持已写声明。AI Enterprise/vGPU 付费许可、DGX Cloud 托管服务、Omniverse 企业订阅与个人免费须保持边界。不把统一收入确认政策当成每个产品的独立价目表。 | `pdf-block-000864-baf70751`、`pdf-block-000869-03a707ef`、`pdf-block-000877-3df8e1b3`、`pdf-block-001433-40824ffe`、`pdf-block-001440-6cf2f47b`、`pdf-block-001441-0f5d011a` |
| NV-06 | 分部收入勾稽 | 百万美元；本期 116,193 + 14,304 = 130,497。完整保留历史/变化列，但当前图不能取 2024 或同比变化。数字由 host 读所选原表单元格。 | `pdf-table-pdf133-revenue`；2025 金额列 c002，行 r003/r004/r005 |
| NV-07 | 终端市场收入勾稽 | 115,186 + 11,350 + 1,878 + 1,694 + 389 = 130,497。保留 OEM and Other；Data Center 下 Compute 102,196 + Networking 12,990 = 115,186，父子不能同时相加。分部表与市场表不可拼成同一分母的一组贡献。 | `pdf-table-pdf172-markets`；2025 金额列 c002，r003–r010；子项 r004/r005 |
| NV-08 | 未披露与未读取分开 | 不给 CUDA、Jetson、DGX Cloud、软件许可等虚构产品收入。没有读完整报告时写“所选材料未找到”，不能泛称全报没有披露。子项/市场映射只有语境推断时明确边界或留 unknown。 | 输入范围说明；业务/收入原文块 |
| NV-09 | 产物、费用与可追溯性 | 真实生成业务/收入分图、Mermaid/SVG、精确证据、Trace/config/usage/估价；字段合法、数值勾稽、语义正确与视觉认可分别记录。失败或没有 usage 不当作零分/零费用。 | 执行后 result、validation、model-calls 与实际渲染产物 |

图形可以是有证据的层级图或主图/辅图；收入可以用条形、环形或表。表达差异不是事实错误。不能用节点数、测试数量或金额恰好勾稽代替语义验收。

已做的输入核对：原 PDF hash、全文文本重抽、60 段逐项比对、2 表 100 派生单元格及所有 101 个原始 word 的几何分配、宿主 verify_packet、PDF 133/172 页表格视觉核对。尚未运行模型、尚未评价业务语义或渲染图。

下一步：运行结束后在新的 evaluation review 记录逐项通过/问题/缺口，引用实际 node/edge/cell ID；保留原始输出，不以人工修正冒充原始 Agent 提取质量。
