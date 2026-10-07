# Microsoft FY2025：业务图与收入图输入准备清单

已有冻结的官方 10-K 足以准备下一次运行。业务说明、四个完整收入维度和对应原文定位都在本地。**尚未生成当前 runner 的 `source_packet.json`，也未运行 Microsoft 模型提取；本轮只完成离线盘点。**

具体例子：输入 Microsoft FY2025 的业务段落、收入原表及期间/币种证据，Uteki Agent 分别输出业务结构与收入构成；工程层从模型选择的原始单元格读取金额。验收时逐条检查节点依据、收入口径、2025 年列和加总关系。既有人工业务图仅用于事后参考，不传给模型。

## 1. 已冻结材料与明确范围

| 项目 | 明确值 |
|---|---|
| 公司 | Microsoft Corporation；CIK `0000789019`；建议沿用既有数据集的 `company_id=sec-0000789019` |
| 文档 | Form 10-K；建议沿用既有数据集的 `document_id=msft-2025-10k` |
| 财年 | FY2025：2024-07-01 至 2025-06-30；`period_end=2025-06-30` |
| 年列标签 | `requested_period_label=2025`；原表写的是 `2025`，不是 `FY2025` |
| 财务展示单位 | USD / million；须带原件单位证据，不能只设配置值 |
| 申报日期 | 2025-07-30 |
| 官方来源 | [SEC 原文](https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630.htm)；本轮未联网重拉 |
| 原件字节数 | 8,158,179 |
| 原件 SHA256 | `0edfaac937bf7042c8cf7901924ccb9cc291ccfab92f83dd0b689b7912089bf6` |

已核对以下三份本地 HTML 的字节哈希一致：

- [冻结官方原件](../../../data/company_workspace/extraction_ab_v1/corpus/msft/originals/msft-2025-10k.html)。建议新输入直接引用这一份。
- [数据集原件副本](../../../data/company_workspace/extraction_ab_v1/corpus/msft/dataset/raw/msft-2025-10k.html)。
- [既有业务图原件副本](../2026-10-07-business-map-mermaid-v1/microsoft/source.html)。

[获取记录](../../../data/company_workspace/extraction_ab_v1/corpus/msft/acquisition.json) 与 [数据集来源记录](../../../data/company_workspace/extraction_ab_v1/corpus/msft/dataset/sources.json) 保存公司、申报日期、来源及期间。它们是已有元数据，不是本轮重新获取的证明。获取记录的 SHA256 为 `f31ee149de1b82f2a8f08802faca2033a07dc97a3d7784bac69df26aec00777b`。

既有人工业务图使用别名 `microsoft` / `msft-fy2025-10k`。下一轮须显式选择并统一调用参数、packet 和结果中的 ID；不能把旧别名自动当作新数据集 ID，也不能混入别家公司的来源。

## 2. 可复用的索引与业务段落

已有 [原文块索引](../../../data/company_workspace/extraction_ab_v1/corpus/msft/dataset/indexes/msft-2025-10k/blocks.jsonl)，共 1,401 块。本文的块号均指这份索引的 `ordinal`。它与旧人工业务图按 `p` / 列表容器统计的段落号不同，不能直接混用。

- 索引 JSONL SHA256：`f538b960f9d3d893e2b7288b4c228409c0f7ce6a6cecd7c47cf206c91546a9d7`。
- [目录索引](../../../data/company_workspace/extraction_ab_v1/corpus/msft/dataset/indexes/msft-2025-10k/index.json) SHA256：`b8d27a5348add6ce103e4441dbc6a0f633f5819d3aa9644510f200775187aeaf`。
- [索引 manifest](../../../data/company_workspace/extraction_ab_v1/corpus/msft/dataset/indexes/msft-2025-10k/manifest.json) SHA256：`2d4ec900fa0bc08f14d4b6fb460b412e99e6dbab96c88988930a4df8204db5bc`。

建议按完整小节选取以下原文。只移除页码、重复页眉和孤立的项目符号，不改写段落、不从旧答案倒推选段。

| 原件页码 | 内容 | 候选索引范围 / 关键块 | 输入用途 |
|---|---|---|---|
| 2 | 公司名称、财政年度截止日 | 6、8 | 公司与期间证据；保留封面原文 |
| 3 | General / What We Offer | 39–49 | 公司业务范围、软件/服务/设备/广告 |
| 5 | Operating Segments | 85–89；`block-000087-44aabdcd` | 三个报告分部；FY2025 口径调整 |
| 5–6 | Productivity and Business Processes | 90–110，去除页眉/页码/孤立符号 | 商业与消费者 Microsoft 365、LinkedIn、Dynamics 的范围和收费方式 |
| 6–7 | Intelligent Cloud | 117–132，去除页眉/页码/孤立符号 | Server products and cloud services、Azure、GitHub/Nuance、企业与合作伙伴服务 |
| 8–9 | More Personal Computing | 143–180，去除页眉/页码/孤立符号 | Windows/设备、Gaming、Search and news advertising；保留列表与上下文 |
| 11–13 | Distribution / Licensing Options | 208–240 起，按所选许可小节完整结束；最低包含 209、211–216、220–234 | 客户、渠道、合同与订阅；后续准备时不能在半段截断 |
| 55 | Note 1 / Recast | 811–818 | FY2025 分部调整；以前年度已按当前管理口径重列 |
| 55–56 | Note 1 / Revenue | 823–838，去除页眉/页码 | Product 与 Service and other 的定义、订阅/用量计费、许可和广告确认原则 |
| 82–83 | Note 18 / Segment Information | 1180–1212，去除页眉/页码/孤立符号 | 分部披露和归属、费用分摊说明；与 Item 1 重复的业务清单可只保留一份，并记录选段策略 |
| 84–85 | Note 18 表前说明、脚注、交叉口径说明 | 1216、1218、1221、1225、1227 | 分部表含多种财务指标；地区定义；产品服务维度；Microsoft Cloud 与其他类别重叠 |

精确定位示例：

- FY2025 分部变化：`block-000087-44aabdcd`，`/html/body/div[15]/p[3]`。
- Azure 业务说明：`block-000127-93a9159b`，`/html/body/div[21]/p[2]`。
- 以前年度重列：`block-000817-00ca3208`，`/html/body/div[165]/div/ix:nonnumeric/div[3]/ix:nonnumeric/p[2]`。
- 地区口径与 OEM 脚注：`block-001218-43fbab2a`、`block-001221-73695690`。
- Microsoft Cloud 重叠说明：`block-001227-3bdf0315`，`/html/body/div[255]/div[1]/ix:continuation/div[1]/ix:nonnumeric/p[4]`。

原索引的部分 `source_anchor` 继承了远处节点，不能作为精确跳转依据。索引还标记了 Item 1B、Item 2、Item 9、Item 9B 的标题歧义。本次所选内容应以原件 DOM 路径与文本 hash 复核；不要因此宣称整份目录已正确覆盖。

## 3. 收入完整表：保留原表，不预填模型答案

原件包含 85 个 HTML 表。以下表号是原件 `//table` 的 1 起始顺序，表格行列坐标是 0 起始。页码来自原件页脚；已复核第 50、84、85 页。每张表都含 2025、2024、2023 年，当前任务只要求 2025 年。

| 原件页 / 表号 | 维度 | 原文块 | 表的 DOM 路径 | 原始行数 / 单元格数 |
|---|---|---|---|---|
| 50 / 24 | Income Statements：Product / Service and other | `block-000781-9ee5633d` | `/html/body/div[150]/table` | 46 / 502 |
| 84 / 72 | Note 18：报告分部 | `block-001217-90dfc72b` | `/html/body/div[252]/div/ix:continuation/div[1]/ix:nonnumeric/table` | 45 / 557 |
| 84 / 73 | Note 18：客户地区 | `block-001219-8fbdd09e` | `/html/body/div[252]/div/ix:continuation/div[2]/ix:continuation/table` | 12 / 113 |
| 85 / 74 | Note 18：重要产品与服务 | `block-001226-283de46e` | `/html/body/div[255]/div[1]/ix:continuation/div[1]/ix:nonnumeric/table` | 20 / 217 |

四张表的规范化全文 SHA256 分别为：

| 原文块 | 文本 SHA256 |
|---|---|
| 781 | `9ee5633df804a67fca8110856500b749499f0408c6de3bab307db9fe9e650961` |
| 1217 | `90dfc72b7d69537584af292e26e4d0a51b0c32548b675560c4bd0c970317bf09` |
| 1219 | `8fbdd09eae6408b7114307db2ecb5900bd69d63b0799f31a5c16fdaef1943598` |
| 1226 | `283de46ecdb49aaf06e035894a9b7cd920233aa2ff4c28f80764d1c768c259fb` |

2025 年的表头均在第 4 行。表 24、73、74 的年表头从第 2 列跨两列，金额位于第 3 列；表 72 的年表头与金额都在第 3 列。美元符号是独立单元格，不能把 `$` 与金额错误合并或改变列坐标。保留空单元格、空行以及 `rowspan` / `colspan`；当前 runner 会重建物理表格并逐格核对。

表 72 同时包含 Revenue、Cost of revenue、Operating expenses、Operating Income；表 24 还包含利润与每股指标。完整输入并不意味着所有行都是收入。模型须依据原文选择，工程校验不能只靠加总碰巧相等判断口径正确。

单位可引用对应原表的 `(In millions)`。美元币种不能仅由 `$` 推断。本轮未在已索引正文中找到 USD 明文，但原件有可验证的 XBRL 单位节点：

- DOM：`/html/body/div[1]/ix:header/ix:resources/xbrli:unit[5]`；原始 ID：`U_USD`。
- 精确文本：`iso4217:USD`。
- 文本 SHA256：`47f88315199f8cbacb7a62e396ed2572614d49eff28bf5722f169abe4eba24db`。
- 已检查四表中收入事实的 `unitref=U_USD`、`scale=6`。新 packet 可将该原始单位节点作为明确标注的来源元数据块加入；不改写官方原件，也不凭人工声明补齐币种。

## 4. 接入同一 runner 前还要准备什么

当前 [runner](../../../src/uteki/agents/business_map/product_run.py) 可核对这一官方 HTML，无需新增通用 parser。但旧索引不能直接当作 packet：块字段名称不同，表内单元格尚没有 runner 要求的稳定 ID、原件 DOM 路径和文本 hash。

| ID | 准备项 | 完成条件 | 当前状态 |
|---|---|---|---|
| MS-P01 | 固定公司、文档、期间和原件版本 | 明确 ID、2025 年列、USD/million；调用参数与 packet 一致；原件 hash 通过 | 已盘点，待冻结调用配置 |
| MS-P02 | 选定完整业务段落与说明 | 从上述原件选段；有 section path、原始 ordinal、DOM、规范化文本和 hash；删除项有说明 | 已定位，未生成 packet |
| MS-P03 | 准备四张完整表 | 原始所有单元格有 ID、文本、hash、DOM、row/column/span；保留表头、总计、脚注与空格位 | 已检查几何，未序列化为正式输入 |
| MS-P04 | 接入期间、单位及币种证据 | 2025 年列可定位；原表单位与原件 `U_USD` 节点可验证；保持原始文本 | 已定位，待加入 packet |
| MS-P05 | 冻结 Skill、schema、输入和请求 | 使用显式选定的 Skill 版本；分别记录 hash；`verify_packet` / `prepare` 离线预检通过 | 未执行 |
| MS-P06 | 检查输入体积与成本预留 | 计算实际请求字节及预留；使用已有额度，不把原件大小当作输入 token 数 | 未执行，存在体积注意项 |
| MS-P07 | 单次真实执行及事后源文验收 | 保存配置、Trace、usage、原始输出、图和引用；失败先核对账单，不自动重跑 | 未运行；须在主任务后续安排 |

字段衔接应只转换证据形态：旧 `block_id → id`、`dom_path → source_dom_path`、`text_hash → text_sha256`，补充明确小节路径；单元格坐标按原 DOM 重新读出，再与旧索引结构交叉核对。禁止把旧人工图的节点、关系、图形选择或财务期待值混入 packet。

原有 acquisition 和 index manifest 不是 runner 可选 `source_manifest` 字段要求的同一 schema，不能直接塞入该字段冒充兼容。可以在新实验说明中保留其文件/hash，而 packet 直接引用已验证原件；若新增该字段，必须另建明确的来源元数据记录并通过全部匹配检查。

体积注意项：四表共 **1,389 个原始单元格**，其中有大量布局空格。以短示例 ID 序列化 runner 所需的单元格字段，离线量得约 **353,223 字节**；这只是表格字段的粗略字节基线，不是正式 packet 大小、token 统计或价格。加上业务段落、Skill 和 schema 后会更大。默认先保留完整证据；若需分批，应在调用前冻结每批范围和费用，不静默丢弃行、压平表格或声称已覆盖所有维度。

## 5. 仅用于事后评价的期待与风险

**本节、旧人工业务图及其生成脚本均不作为模型输入。** 原始来源中的数值当然仍在原表；这里列的是验收侧预期，不是让模型照抄的答案或共享代码常量。

| 评价维度 | 本报告的源文期待 |
|---|---|
| 业务层级 | 能辨认三个 reportable segment；产品/服务组与分部不混为一个层级。允许不同合理粒度，不固定节点数或复制旧图 |
| 分部重组 | Microsoft 365 的商业组件按 FY2025 报告列入 Productivity and Business Processes；不能用旧年份归属替代本报告 |
| 收入维度分开 | 分部、重要产品服务、客户地区、Product/Service and other 分别表达；不能混在同一饼图相加 |
| 逐表完整性 | 分部 3 个贡献项；重要产品服务 10 个贡献项（包括 Other）；地区 2 个贡献项；产品/服务 2 个贡献项。只在本报告评价侧检查，不写成通用 Skill 的数量要求 |
| 2025 年核算 | 四个维度各自精确加总至 **281,724 百万美元**；实际金额由工程层从模型所选原始 cell 读取。该总额仅为本轮原件核算期待 |
| Microsoft Cloud | 该披露跨越多个产品组，原文明确已计入各组；不能再作为同层贡献项加入总收入，也不能把它当作第四报告分部 |
| Azure | 业务节点可以有 Azure，但选定的产品服务收入表只披露 Server products and cloud services 汇总；不能把汇总额直接标为 Azure 收入，也不能编造拆分 |
| 地区口径 | 按客户所在地分类，并保留美国项关于 OEM / 跨国组织开票的脚注；不能解释为终端用户实际所在地 |
| 指标边界 | 商誉、未赚取收入、长期资产虽然也有分部/地区表，却不属于本轮收入构成。排除原件表 47、58、75 等错误候选 |

已有 [Microsoft 人工业务图](../2026-10-07-business-map-mermaid-v1/microsoft/business_map.json) 与 [原文证据页](../2026-10-07-business-map-mermaid-v1/microsoft/evidence.html) 可用于事后参考。该公司已在本项目讨论并展示过，因此下一轮是跨公司迁移检查，不能称为盲测留出集。

## 6. 本轮实际检查与下一步

已完成：三份原件字节一致；索引所选 208 个块的规范化文本与 hash 对回原 DOM、无差异；四张完整表的物理行列/跨度无重叠，单元格数量与既有索引一致；核对 2025 年表头、金额列、USD 单位引用；四个收入维度在评价侧各自加总一致。未运行模型、未重拉网络原件、未修改历史源/产物，也未生成新的正式 packet 或请求。

优先下一步：

1. 按 MS-P01–P04 冻结正式输入包及选段说明，保留官方 HTML 作为真值。
2. 完成 MS-P05–P06 的离线预检，核实实际请求体积与预留，再安排一次真实运行。
3. 用本节评价侧标准审查输出并交付可点回原文的业务图、收入图；把字段合法与内容正确分开报告。
