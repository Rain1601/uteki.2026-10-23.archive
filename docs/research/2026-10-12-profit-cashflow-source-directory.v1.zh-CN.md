# 现金流最小场景：公司、期间与官方原件目录 v1

2026-10-12 · DS-04 / 原件目录实例。依据[业务契约v1.0](2026-10-12-profit-cashflow-contract.v1.zh-CN.md)，本轮确定A/B、实际财年、T0/T1及官方文件入口。**这是已核对元数据的目录，不是原件包/内容验收或Agent实跑通过；未开发、未批量下载财报包、未运行模型。**

## 1. 公司与实际期间

| 角色 | 公司 / CIK | 本次用途 |
|---|---|---|
| A | Microsoft / `0000789019` | 首稿与T1更新目标；复用已有公开来源和部分原件，避免从另一家公司重新铺材料 |
| B | Alphabet / `0001652044` | 公司/财年干扰及显式切换的范围检查；使用T0/T1以前已公开的FY2024年报，FY2025年报只作未来材料干扰 |
| 保留 | Costco | 保持DS-02后续独立迁移案例位置，本轮不读取其原件或gold来调规则 |

微软财年为7月1日至6月30日，官方[财年说明](https://www.microsoft.com/en-us/investor/faq)与三份申报期末一致。

| 固定观察期 | A的实际起止日 | 原报告申报日期 |
|---|---|---|
| FY2023 | 2022-07-01–2023-06-30 | 2023-07-27 |
| FY2024 | 2023-07-01–2024-06-30 | 2024-07-30 |
| FY2025 | 2024-07-01–2025-06-30 | 2025-07-30 |

T1新增微软FY2026 Q1，实际期间`2025-07-01–2025-09-30`，单列更新，不拼入原三年年度数列。B的FY2024年报期末是`2024-12-31`，不能继承A的6月期末/财年。B的FY2025年报在2026-02-05申报，晚于本场景两个截止日；同样提问B的FY2023–FY2025时，FY2025完整年报/全年值应留未公开缺口，不自动滚动为FY2022–FY2024或用季度填全年。[B FY2024索引](https://www.sec.gov/Archives/edgar/data/1652044/000165204425000014/0001652044-25-000014-index.html)、[B FY2025索引](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000018/0001652044-26-000018-index.html)

## 2. T0/T1明确时刻与证据

| 时点 | UTC截止日 | 北京时间 | 官方锚点 |
|---|---|---|---|
| T0首稿 | `2025-07-31T00:00:00Z` | **2025-07-31 08:00** | [原始FY2025 10-K索引](https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/0000950170-25-100235-index.html)：Filing Date 2025-07-30；Accepted 16:11:40；对应官方Submissions登记UTC为2025-07-30T20:11:40Z。取其已公开UTC日的下一日00:00 |
| T1更新 | `2025-10-30T00:00:00Z` | **2025-10-30 08:00** | [FY2026 Q1 10-Q索引](https://www.sec.gov/Archives/edgar/data/789019/000119312525256321/0001193125-25-256321-index.html)：Filing Date 2025-10-29；Accepted 16:10:48；对应登记UTC为2025-10-29T20:10:48Z。取下一日00:00 |

按冻结规则采用日级知识截止点。SEC公开索引/申报日期与同日[FY25 Q4公告](https://www.microsoft.com/en-us/investor/earnings/fy-2025-q4/press-release-webcast)、[FY26 Q1公告](https://www.microsoft.com/en-us/investor/earnings/fy-2026-q1/press-release-webcast)核对；**Accepted保留为接收登记时刻，不改名为精确首次公开秒数**，本轮不声称秒级历史PIT已验。日级时间仍不足以判断某个附件/网页在截止日前可知时，该项时间待核验。

本轮用官方在线索引互核本机SEC Submissions历史目录；该目录中T0之后至T1只有一份微软10-Q，即上述2025-09-30报告。历史目录证据入口：`output/ds03-p0-20261012-r1/discovery/filing-candidates.json`，SHA-256 `47edab32ae09426c27854adc19f88feaced09b99645342be710bff1443a9b047`。T1>T0且均早于DS-02总cutoff`2026-10-12T00:00:00Z`。

## 3. SEC原件清单：按申报目录绑定，非按答案选块

下列链接是官方申报索引，列明主文及附件的实际文件名；不是把索引页当财务证据。取得阶段以各目录基址拼接列出的文件名，并绑定原件/hash/实际类型与引用资产。T0/T1可用性仅说明时间与角色，完整事实与附件历史版本仍待原件核验。

| ID | 申报 / 官方目录 | 应取主文与明确附件 | 材料角色/截止日 |
|---|---|---|---|
| S01 | [MSFT FY2025 10-K · 0000950170-25-100235](https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/0000950170-25-100235-index.html) | `msft-20250630.htm`；`msft-20250630.xsd`（嵌入linkbase）；`msft-20250630_htm.xml`；原文引用资产 | A基准主源；T0/T1；已有DS-03部分原件取得记录，不追认为本场景内容已验 |
| S02 | [MSFT FY2024 10-K · 0000950170-24-087843](https://www.sec.gov/Archives/edgar/data/789019/000095017024087843/0000950170-24-087843-index.htm) | `msft-20240630.htm`、同名前缀`.xsd`及`_htm.xml`、引用资产 | 原列报/历史解释；T0/T1 |
| S03 | [MSFT FY2023 10-K · 0000950170-23-035122](https://www.sec.gov/Archives/edgar/data/789019/000095017023035122/0000950170-23-035122-index.htm) | `msft-20230630.htm`、`.xsd`、`_htm.xml`及实际列出的`_def/_lab/_pre/_cal.xml`、引用资产 | 2023原列报/必要解释依赖；T0/T1 |
| S04 | [MSFT FY2025业绩8-K · 0000950170-25-100226](https://www.sec.gov/Archives/edgar/data/789019/000095017025100226/0000950170-25-100226-index.html) | `msft-20250730.htm`＋`msft-ex99_1.htm`；财务iXBRL依赖按索引保留 | 2025-07-30业绩；T0/T1 |
| S05 | [MSFT FY2024业绩8-K · 0000950170-24-087835](https://www.sec.gov/Archives/edgar/data/789019/000095017024087835/0000950170-24-087835-index.htm) | `msft-20240730.htm`＋`msft-ex99_1.htm`及实际依赖 | 2024-07-30业绩/GAAP与非GAAP对照；T0/T1 |
| S06 | [MSFT FY2023业绩8-K · 0000950170-23-034400](https://www.sec.gov/Archives/edgar/data/789019/000095017023034400/0000950170-23-034400-index.html) | `msft-20230725.htm`＋`msft-ex99_1.htm`及实际依赖 | 2023-07-25业绩/定义；T0/T1 |
| S07 | [MSFT重编8-K · 0000950170-24-132722](https://www.sec.gov/Archives/edgar/data/789019/000095017024132722/0000950170-24-132722-index.html) | `msft-20241203.htm`＋`msft-ex99_1.htm`；`msft-20241203.xsd`、`msft-20241203_htm.xml`及引用资产 | FY2024报告的分部重编；T0/T1。影响哪些现金流/利润事实待逐项核验，不整体改写数列 |
| S08 | [MSFT FY2025 Q1 10-Q · 0000950170-24-118967](https://www.sec.gov/Archives/edgar/data/789019/000095017024118967/0000950170-24-118967-index.html) | `msft-20240930.htm`、`.xsd`及`_htm.xml`、引用资产 | S07正文明确要求结合阅读的引用依赖；T0/T1；季度单列 |
| S09 | [MSFT FY2026 Q1 10-Q · 0001193125-25-256321](https://www.sec.gov/Archives/edgar/data/789019/000119312525256321/0001193125-25-256321-index.html) | `msft-20250930.htm`、`.xsd`及`_htm.xml`、引用资产 | T1更新主源；T0未来材料，正文/数值/预览均不入T0模型输入 |
| S10 | [MSFT T1业绩8-K · 0001193125-25-256310](https://www.sec.gov/Archives/edgar/data/789019/000119312525256310/0001193125-25-256310-index.htm) | `msft-20251028.htm`＋`msft-ex99_1.htm`、`msft-ex99_2.htm`、`msft-ex99_3.htm`及图片；实际iXBRL依赖 | 申报2025-10-29，Date of Report为2025-10-28；不能用后者决定公开截止日。只在T1纳入 |
| S11 | [MSFT中间8-K · 0001193125-25-225125](https://www.sec.gov/Archives/edgar/data/789019/000119312525225125/0001193125-25-225125-index.html) | `d863209d8k.htm`；索引Item 5.02 | T0–T1间的人员/薪酬安排披露；财务相关性待内容筛查，不能把“不是业绩发布”直接等于无关或已验 |
| S12 | [MSFT FY2025 Q3 10-Q · 0000950170-25-061046](https://www.sec.gov/Archives/edgar/data/789019/000095017025061046/0000950170-25-061046-index.html) | `msft-20250331.htm`及必要依赖；既有目录已核对 | 季度/YTD干扰，报告期末2025-03-31；不可将九个月现金流当全年值。T0/T1时间允许，但不强制交付 |
| S13 | [GOOG FY2024 10-K · 0001652044-25-000014](https://www.sec.gov/Archives/edgar/data/1652044/000165204425000014/0001652044-25-000014-index.html) | `goog-20241231.htm`及必要依赖 | B公司干扰/显式切换；T0/T1已公开；不填A缺口 |
| S14 | [GOOG FY2025 10-K · 0001652044-26-000018](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000018/0001652044-26-000018-index.html) | `goog-20251231.htm`及必要依赖 | 仅未来干扰；T0/T1均排除。目录ID可记录排除原因，未来事实/预览不传历史模型 |

这14项是**申报级材料/候选项，不是14个文件，也不是14份必读正文**。资产展开、必要引用、待筛查项各有状态；实际下载文件总数和最终必需取材由目录展开及独立核验确定。S12属于既有P0记录，本轮未另请求其原件。

S07的[官方主文说明](https://www.sec.gov/Archives/edgar/data/789019/000095017024132722/msft-20241203.htm)明确为分部重编，并说明不是原财务报表错误重列；因此可验证recast关系，不能据此勾完真正错误更正。S10索引另列`img140252018_0.jpg`与`msft-ex99_3s1.jpg`至`msft-ex99_3s22.jpg`共23个图像文件；正文/附件容器和引用关系都保存，内容是否必需待原件验收，不能只保存三个HTML就称图片内容已取得/已读。

## 4. 官方IR材料清单与重复关系

以下网页入口已核对；当前网页可读不证明历史字节或稳定获取。SEC归档附件为披露版本基准，IR同披露内容作为补源/重复关系核对，不按多个网页重复计同一事实。

| 期间 | 官方业绩原文 | 官方现金流补表 | 时间角色 |
|---|---|---|---|
| FY2023 Q4/全年 | [2023-07-25发布](https://www.microsoft.com/en-us/investor/earnings/fy-2023-q4/press-release-webcast) | [Cash Flows](https://www.microsoft.com/en-us/investor/earnings/fy-2023-q4/cash-flows) | 与S06关联；T0/T1。表内更早比较期不扩展固定观察窗口 |
| FY2024 Q4/全年 | [2024-07-30发布](https://www.microsoft.com/en-us/investor/earnings/fy-2024-q4/press-release-webcast) | [Cash Flows](https://www.microsoft.com/en-us/investor/earnings/fy-2024-q4/cash-flows) | 与S05关联；原发布/后续重编分开 |
| FY2025 Q4/全年 | [2025-07-30发布](https://www.microsoft.com/en-us/investor/earnings/fy-2025-q4/press-release-webcast) | [Cash Flows](https://www.microsoft.com/en-us/investor/earnings/fy-2025-q4/cash-flows) | 与S04关联；三年财务补表；T0/T1 |
| FY2026 Q1 | [2025-10-29发布](https://www.microsoft.com/en-us/investor/earnings/fy-2026-q1/press-release-webcast) | [Cash Flows](https://www.microsoft.com/en-us/investor/earnings/fy-2026-q1/cash-flows) | 与S10关联；只在T1使用，三个月数据不混全年 |

FY2025 Q4财务目录另核对到：[Income Statements](https://www.microsoft.com/en-us/investor/earnings/fy-2025-q4/income-statements)、[Comprehensive Income](https://www.microsoft.com/en-us/investor/earnings/fy-2025-q4/comprehensive-income)、[Balance Sheets](https://www.microsoft.com/en-us/investor/earnings/fy-2025-q4/balance-sheets)、[Segment Revenue](https://www.microsoft.com/en-us/investor/earnings/fy-2025-q4/segment-revenues)。财务补表按同年目录展开，但取数与最终证据仍须按Query选择，不将整页导航或全部表默认装入模型。

[官方Annual Report 2025目录](https://www.microsoft.com/investor/reports/ar25/index.html)可定位财务正文和附注，作为财务重刊/补源候选；网页整体/股东信的历史公开时刻未核准，不能仅因标题“2025”默认T0可知。Earnings相关下载区列出Financial Statements、Earnings Call Slides、Outlook等类别，但本轮未绑定全部下载按钮的资产URL；保留“待展开”，不猜文件名。完整电话会音频/逐字稿仍不纳入本次财务分母；必要财务说明如无法在已允许原件取得，报缺口或明确提出范围变更。

## 5. 本轮完成与未完成的边界

- 已完成：A/B、A三年实际起止日、T0/T1、14项申报/候选目录及上述IR入口核对，关键父附件/重编/引用关系已明确。目录没有答案数值、精确答案块或gold，不替Data Agent选章节。
- 获取限制：网页查阅可读上述主要官方入口；一次本机IR直连在放开网络后仍返回403，另有通用`financial-statements`路径404，已改用官网实际列出的分表入口。没有绕过限制，也不称稳定获取通过。
- 未完成：本场景所有原件实际字节/hash、IR历史版本可知性、下载资产/正文图片与引用展开、S11相关性、全部事实/条件与容差清单、真正错误更正案例、模型/重复次数与资源冻结。已有19对象获取成绩只属于旧DS-03小包。
- 下一小任务：依据此目录核对可复用原件与明确缺件，形成最小原件包及待取/受限清单；当前不自动开始下载、独立gold编制、开发或模型实跑，保持业务契约原字节和历史失败。
