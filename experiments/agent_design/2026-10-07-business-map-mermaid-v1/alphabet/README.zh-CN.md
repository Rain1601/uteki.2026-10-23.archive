# Alphabet FY2025 业务图：原文核对候选

状态：**candidate**。这是一轮由 Codex 回查冻结原文后整理的业务结构，不是模型 API 提取结果，也没有完成用户采纳。结构为 15 个节点、14 条关系、3 层；包含 20 份精确来源块证据。不含收入金额、收入权重或估值判断。

- [业务结构 JSON](business_map.json)：沿用 `src/uteki/domain/business_map/models.py` 的 `BusinessMap` 契约，`schema_version=0.1`。
- [证据阅读页](evidence.html)：每个 `evidence_id` 有独立可跳转的锚点、原文、段落与来源块哈希、DOM 位置。
- [本地原件](source.html)：仅将仓库的 gzip 文件解压；未添加锚点、改写文本或改动原报告。
- [SEC 原始文件](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000018/goog-20251231.htm)：本轮未联网获取。

## 结构和阅读规则

第一层为 Alphabet。第二层为 Google Services、Google Cloud 和 Other Bets。前两项是 Google 的报告分部；Other Bets 是非 Google 业务的集合口径。本图省略中间的 Google 节点，以保持三层。

第三层包含 Services 的三类广告、消费者订阅、Play 平台和 Pixel 设备；Cloud 的 GCP 与 Workspace；Other Bets 的 Waymo、互联网服务和 X 研发示例。

`relationships.source_id` 为子节点，`target_id` 为父节点。渲染器可反转绘图箭头来从上向下阅读，但不能改变关系语义。`kind` 区分公司、报告分部、业务、产品组和收入类别。它们并列展示，不表示同一计量层级或相同规模。

- 订阅、平台和设备是三个商业活动节点，但使用合并的收入披露分类。图中不拆分各自金额。
- Search & other、YouTube ads、Google Network 是广告收入类别。YouTube 的订阅产品归入消费者订阅，不把 YouTube 全部活动当作广告收入。
- Android、Chrome、Gemini 等产品保留在 Services 描述中，不推定为独立收费业务或单列分部。
- GCP 和 Workspace 有明确收费方式；本图没有给它们分配独立收入金额。Cloud 的其他企业服务未展开。
- Other Bets 的互联网服务是组合收入来源，不推定对应某一家具名公司。Waymo 有明确付费网约车证据。
- X 的研发身份有直接证据；收费方式标为 `unknown`。不能从 Other Bets 部分成员已有收入推出 X 已有收入。

## 原文与定位

冻结原件：`data/source_documents/alphabet_2025_10k/source.html.gz`。

原件解压后 SHA-256：

`c2f6301004f35411a20611c14ff01d80a85c0bcbab6053c80d8cc7f6fc747161`

文档 ID 为 `sec-0001652044-26-000018`；报告期末为 `2025-12-31`。解压原件哈希与冻结 manifest 一致。

本轮用既有 benchmark 作为查找线索，随后对 20 个引用逐个回到原 HTML 的 DOM 位置核对；未把 benchmark、译文或既有摘要当作事实来源。涉及 Item 1 的 Overview、Moonshots、Google Services、Google Cloud、Other Bets，以及 Note 1 的三类收入确认说明。范围是选定段落，不是逐段语义核验整份年报。

`evidence.paragraph_ordinal` 与 `text_hash` 沿用 `sec-visible-blocks-v1` 的原段落契约。`metadata.evidence_locators` 同时绑定冻结 `v0.5-candidate` 索引的 `block_id`、`block_ordinal`、`block_text_hash` 与 `dom_path`。段落与来源块可能因项目符号和标签边界空格而具有不同哈希；分别校验，不混用。

`exact_quote` 是对应原 DOM 块的文字：解码 HTML 实体、相邻文本拼接、空白合并；不翻译、不增删原词。精确阅读链接使用 `evidence.html#e-…`。`original_fragment` 是原 HTML 中真实存在的唯一章节锚点，通常覆盖多段；它不冒充精确段落锚点。局部证据页另列 DOM 路径和原块哈希。

## 已完成核验

1. 使用现有 `business_map_from_dict` 反序列化，并通过现有候选字段校验与 `validate_evidence`。候选的节点、关系、赚钱方式引用均能解析，所有节点与边均保持 `candidate`。
2. 20 个证据的原段落序号、哈希、文档 ID 和 URL 与直接解析冻结原件的结果一致。
3. 20 个证据的原 DOM 文本与冻结来源块文本、哈希一致；段落与块在忽略空白后逐字一致。
4. 每个证据页锚点唯一且对应原文；全部原报告章节锚点在原 HTML 中唯一存在。`source.html` 与原件解压字节完全相同。
5. 没有模型 API 调用、网络调用、财务金额推算或生产代码修改。没有进行浏览器视觉检查。

## 保留的缺口与下一步

本次没有核定完整 Other Bets 成员清单、逐产品收入、竞争地位、风险、增长或利润。Isomorphic Labs 等未展开；集中 AI 研发归属在 Overview 中可见，但本图未画成本中心。有关缺口也写入 JSON 的 `unknowns` 和 `metadata.omissions`。

下一步：由同轮 Mermaid 渲染使用此 JSON 展示结构，并让用户核对层级、节点粒度和赚钱方式。通过后再决定是否扩展数字或完整业务清单。
