# TSMC FY2023：原文业务图候选

[业务图数据](business_map.json)包含 **14 个节点、15 条关系、13 处原文证据和 4 个待核对问题**。这是 Codex 依据冻结原文整理的首轮候选；未调用模型 API，未接入生产 Agent，也未经用户采纳。

本图回答“台积电服务哪些主要应用，并提供什么技术”。台积电按客户设计制造半导体，主要应用平台包括 HPC、智能手机、IoT、汽车和数字消费电子。**这些是应用平台，不是五个经营分部。** 附注 38 明示公司只有一个晶圆代工经营分部，依据为块 1918。

| 应用平台 | 图中挂接的产品服务组 | 原文位置 |
|---|---|---|
| HPC | 逻辑制程与 IP；3DFabric 封装与硅堆叠 | [块 304](../../2026-10-07-parser-navigation-v1/stage-b-tsmc/document.html#block-000304-e759458b) |
| 智能手机 | 逻辑制程与 IP；配套芯片专用技术；3DFabric（原文明确 InFO） | [块 305](../../2026-10-07-parser-navigation-v1/stage-b-tsmc/document.html#block-000305-3d9c8aaa) |
| IoT / AIoT | 超低功耗 ULP 平台；3DFabric（原文明确 InFO） | [块 308](../../2026-10-07-parser-navigation-v1/stage-b-tsmc/document.html#block-000308-c149c1c3) |
| 汽车 | 汽车逻辑与 N3AE 早期设计支持；汽车级专用技术 | [块 309](../../2026-10-07-parser-navigation-v1/stage-b-tsmc/document.html#block-000309-046fea01) |
| 数字消费电子 | 面向电视、机顶盒、相机等客户芯片的制程 | [块 310](../../2026-10-07-parser-navigation-v1/stage-b-tsmc/document.html#block-000310-e7a304b7) |

公司总体服务与客户类型依据块 260、264、266、297。经营分部边界依据[块 1918](../../2026-10-07-parser-navigation-v1/stage-b-tsmc/document.html#block-001918-aed11683)。图中“产品服务”指台积电提供的制程、IP 或封装相关能力；客户 AI 加速器、手机、汽车及电视等是应用语境。N3AE 保留“2023 年推出的早期设计支持”语义，不将它等同于量产完成。

## 契约与证据

- 使用现有 `BusinessMap` 的 `company`、`business`、`offering_group` 类型。应用平台在元数据 `node_roles` 中明确标为 `application_platform`；没有新增枚举，也没有 `reportable_segment` 节点。
- `part_of` 保持“平台 → 公司”；`supports` 保持“技术服务 → 平台”。公司、平台、服务可排成三层；跨平台 3DFabric 只保留一个节点，不重复制造业务实体。
- 每个节点及每条关系均有 `evidence_ids`。`metadata.node_assertion_basis` 与 `metadata.relationship_assertion_basis` 区分 `explicit` / `derived`。后者的键为 `source_id|kind|target_id`。归组是派生展示；原文提供的技术及支持关系有直接依据。
- `Evidence.paragraph_ordinal` 在本小样中映射到冻结块序号；`text_hash` 是整个块的 SHA-256。`metadata.evidence_locators` 保存完整阅读版路径、真实块锚点、原 DOM 路径与精确引用。引用逐字匹配规范化块文本，不冒称原始 HTML 字节切片。
- 期间为 FY2023 年报，`period_end=2023-12-31`，披露可用日为 `2024-04-18`；`temporal_basis=report_disclosure_context`。它不代表所有技术在整个年度均已交付，也不表示 2026 年现状。

原件来自 SEC：[TSMC FY2023 20-F](https://www.sec.gov/Archives/edgar/data/1046179/000119312524099840/d592628d20f.htm)。输入包为 `stage-b-tsmc`，解析版本 `sec-source-blocks-v0.1.10`。原件 SHA-256：`8ab4ee8c621d4d7bc804d08bd5cfe494b91dc09a63a4c7decfad4e5f8b9961c1`。仓库相对原件路径保存在 JSON 的 `metadata.source_local_path`。

## 实际阅读与验证

实际阅读块范围：258–278、285–330、1913–1924；涵盖公司概览、客户、制造与主要应用平台、部分横向服务以及附注 38。没有逐段通读整份 20-F。

已执行：

1. `business_map_from_dict` 构建与落盘后重新加载均通过。
2. 14 个节点、15 条边均绑定已登记证据；节点/边类型合法，端点及证据引用存在。
3. 13 条精确引用均包含于对应原文块；13 个块文本 hash 与实际文本吻合。
4. 13 个阅读版锚点各唯一存在；对应原 DOM 路径均存在；原 HTML hash 与冻结 `source.json` 一致。

未执行：生产 Agent 自动生成、模型 API、完整财报语义/漏项审计、图片/OCR、真实查询 benchmark、浏览器视觉验收或人工采纳。

## 保留的缺口与下一步

收入表中的 Others 未展开；未提取财务数字、定价与利润分摊；未核验具名客户到具体平台/工艺的完整关系；未逐技术核验量产或采用状态。设计、掩模、测试在公司字段保留，CyberShuttle 等横向服务没有全部扩成节点。当前未读或未建图不表示原件未披露。

1. 先用这份候选渲染 Mermaid，核对层级、箭头含义和原文跳转。
2. 再按用户关注点补 Others、横向服务或客户关联，逐项取证；不把该小样计为 TODO 09 整项完成。
