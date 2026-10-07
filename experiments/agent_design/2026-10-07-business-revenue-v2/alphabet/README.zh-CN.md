# Alphabet FY2025：业务归属与收入披露分开

状态：**candidate**。本轮修正 v1 将产品/业务与收入类别平铺的问题。v1 文件不变；本目录只新增事实输入和证据，不改渲染器或页面，不调用外部模型/API。

- [business_map.json](business_map.json)：15 个业务/产品节点、14 条归属关系，沿用现有 BusinessMap schema 0.1。
- [revenue.json](revenue.json)：2 个独立收入视图，保留原表金额、单位、期间、负调整和小计。
- [新增证据页](evidence.html)：3 段新增业务定义，及收入的单位、币种、年度列、完整表与金额行定位。
- [原件 HTML](../../2026-10-07-business-map-mermaid-v1/alphabet/source.html)：v1 保存的原 gzip 精确解压副本；旧版 20 条业务证据及其链接原样保留。

## 业务图的修正

新增 `google-search`、`youtube`、`google-network-ad-services` 三个业务身份，依据原文产品定义与广告服务说明。它们没有沿用旧广告收入节点的 ID，也不是只把 `revenue_line` 改为另一个 `kind`。

Search 是搜索产品，不能与包含 Gmail、Maps、Play 等媒体的 **Search & other** 广告收入类别等同。YouTube 是内容平台，同时包含广告与订阅服务，不能仅用 **YouTube ads** 代表。Network 节点表示 Google 在合作伙伴媒体上提供的广告服务，不表示这些合作伙伴属于 Alphabet。

消费者订阅汇总节点改为具名 Google One 产品；YouTube 的订阅产品归入 YouTube，避免将同一平台的订阅再平铺为另一个业务。Other Bets 展开 Waymo、X 及互联网服务活动。原文直接说明互联网服务销售是组合收入来源；将该活动归为产品服务组并连接 `part_of` 是审阅者归组，已在节点/关系描述及 metadata 中标为 `derived`。它不代表披露了具名运营公司、独立分部或独立收入，收费事实仍为原文明示。

互联网服务没有被删除或隐藏；其未知运营主体记入 `unknowns`。metadata 的 node/relationship assertion basis 是本轮审阅约定，不是现有域模型的强制字段。

业务图没有 `revenue_line` 节点或 `revenue_component_of` 边。仅使用 `part_of` 和 `reported_under`；收费方式作为节点说明保留，但节点不代表互斥、可加总的收入切片。Other Bets 仍是非 Google 业务组合，不声称它是第三个独立报告分部。Cloud、其他 Services 产品和完整 Other Bets 成员未穷举。

## 收入的真实取值

来源是 FY2025 Form 10-K 的 **Item 7 → Financial Results → Revenues**。表前原文为 `The following table presents revenues by type (in millions):`。年度列是 2024 和 2025，本轮明确选择 **2025**。币种由原文“report our financial results in US dollars”另行支持。

单位统一为 **USD million / 百万美元**。以下值直接读取原表 2025 列，不从 benchmark、旧候选或预期结果反填：

| 原披露项目 | FY2025，百万美元 | 在本轮视图中的用途 |
|---|---:|---|
| Google Search & other | 224,532 | Services 内部构成 |
| YouTube ads | 40,367 | Services 内部构成 |
| Google Network | 29,792 | Services 内部构成 |
| Google advertising | 294,691 | 上述三项的小计；不重复加入图中 parts |
| Google subscriptions, platforms, and devices | 48,030 | 合并披露项；不拆成订阅、平台、设备三个金额 |
| Google Services total | 342,721 | Services 环图分母；集团收入组之一 |
| Google Cloud | 58,705 | 集团收入组 |
| Other Bets | 1,537 | 集团非 Google 业务组合收入 |
| Hedging gains (losses) | **−127** | 集团负对冲调整；括号按负数读取 |
| Total revenues | **402,836** | 含对冲调整的集团合并收入 |

集团视图使用 `chart_type=bar`：`342721 + 58705 + 1537 - 127 = 402836`。三个正收入组的合计为 402,963，不能将它们归一化成总和 100% 后冒充集团收入占比；负调整单列。

Services 视图使用 `chart_type=donut`，分母明确为 342,721：`224532 + 40367 + 29792 + 48030 = 342721`。此视图没有负值或调整。两个视图是同一批收入在不同汇总口径下的展示，不可跨图相加。JSON 不预填百分比；若渲染百分比，应使用各自明确分母。

## 原文位置与金额复核

冻结原件 SHA-256：

`c2f6301004f35411a20611c14ff01d80a85c0bcbab6053c80d8cc7f6fc747161`

收入表 DOM：`/html/body/div[548]/table`；冻结块 `block-000518-f8791d57`；原报告页 33；旧段落契约 ordinal 506。表前单位说明为旧段落 505。币种说明为旧段落 201 / 冻结块 211。

`revenue.evidence` 是列表。每条金额证据保留原整行的 `exact_quote` 和 `source_dom_path`，同时保留 **2025 数值单元格**的 `source_cell_dom_path`、`source_cell_text`、`cell_text_hash`、`column_period`。每个 part、adjustment 和 subtotal 通过 `amount_evidence_id` 绑定唯一金额证据；每个 chart 通过 `total_amount_evidence_id` 绑定分母/总额的金额证据。`evidence_ids` 与 `total_evidence_ids` 另包含年度、单位、币种依据。

单元格文本算法为相邻 `itertext()` 直接拼接，然后折叠空白；SHA-256 对该文本的 UTF-8 字节计算。原行引文忠实保留两年列，因此阅读时必须结合 `column_period=2025` 与具体单元格，不能取错列。括号只在金额解析时转为负值，不改原 `source_cell_text`。

表格位置与 2025 年度列由本轮原文审阅明确选择；程序从该列的真实 DOM 单元格取值并复算。这不是从任意年报自动发现年度列的通用能力。完整原表的文本哈希、旧段落哈希及单元格哈希各自保留，不混用。

## 实际检查与边界

已检查现有 BusinessMap 契约与原段落引用；旧 20 条证据及定位字段不变，新增 3 条定义与原 DOM 一致。业务图仅保留两种归属关系。收入行引文、2025 单元格文本、SHA-256 与解析值均回原件逐条核对；两图含调整求和等于总额，广告小计与三个广告类别之和一致。

本轮增加读取收入表、单位说明和币种说明，不代表整份年报语义验收。没有给 Search、YouTube、Google One、Play、Pixel、GCP、Workspace 分配独立收入，也没有新增收入预期、估值判断或模型调用。实际图形与页面由主任务生成；本目录不声称已完成视觉或交互验收。

下一步：渲染器对 `amount_evidence_id` 对应的原单元格独立解析校验，再分别显示业务归属图和明确分母的收入视图。
