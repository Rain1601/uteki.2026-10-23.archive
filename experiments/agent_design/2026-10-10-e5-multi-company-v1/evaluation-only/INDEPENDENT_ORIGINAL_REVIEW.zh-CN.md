# E5：独立原件复核（仅评测侧）

复核日期：2026-10-10。复核者：Codex 独立子代理。输入：两份已选 FY2025 10-K 的完整 raw HTML 和各自 `sources.json`。未读取运行答案、已有参考答案或解析器的 records / evidence / blocks；未调用外部 API，未联网。此文件不得传入运行 Agent。

结论：题目可由这两份原件直接回答。必需答案为下表四项；每项必须与正确的公司、完整财年、币种、数量级和原文出处绑定。两家公司同名 FY 的日期不同，不能统一套用自然年。

| 公司 | 财年 | 期间（含首尾日期） | 合并总收入 | 币种及原表单位 |
|---|---:|---|---:|---|
| Microsoft Corporation | 2025 | 2024-07-01 至 2025-06-30 | 281,724 | USD，百万 |
| Microsoft Corporation | 2024 | 2023-07-01 至 2024-06-30 | 245,122 | USD，百万 |
| Alphabet Inc. | 2025 | 2025-01-01 至 2025-12-31 | 402,836 | USD，百万 |
| Alphabet Inc. | 2024 | 2024-01-01 至 2024-12-31 | 350,018 | USD，百万 |

## 1. 来源身份、字节与截止日

下列相对路径均以仓库根目录为根。本次从 `sources.json` 的 `raw_file` 打开完整原始文件，以 lxml 解析全部 DOM，再定向精读题目对应的损益表、等价披露、上下文及合并范围说明。没有把完整文件的程序加载称为逐字审阅全部年报。

**Microsoft**

- raw：`experiments/agent_design/2026-10-09-data-agent-completion-v1/datasets/msft/raw/msft-2025-10k.html`
- 原件 8,158,179 bytes；SHA-256：`0edfaac937bf7042c8cf7901924ccb9cc291ccfab92f83dd0b689b7912089bf6`。与源目录声明一致。
- 原始 URL：[Microsoft FY2025 10-K](https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630.htm)。本次仅记录本地元数据所载 URL，没有重新访问。
- 原件封面 `dei:EntityRegistrantName` 为 MICROSOFT CORPORATION，CIK 为 `0000789019`，表单为 10-K，期间结束日为 June 30, 2025。实体 DOM：`/html/body/div[3]/p[15]/span/ix:nonnumeric`；期间 DOM：`/html/body/div[3]/table[2]/tr[2]/td[2]/p/span[2]/ix:nonnumeric`。
- 目录 `available_at` 为 2025-07-30；原件签字段 `/html/body/div[303]/p[2]` 同样写 July 30, 2025。

**Alphabet**

- raw：`experiments/agent_design/2026-10-09-data-agent-completion-v1/datasets/googl/raw/googl-2025-10k.html`
- 原件 2,616,499 bytes；SHA-256：`c2f6301004f35411a20611c14ff01d80a85c0bcbab6053c80d8cc7f6fc747161`。与源目录声明一致。
- 原始 URL：[Alphabet FY2025 10-K](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000018/goog-20251231.htm)。文件夹 `googl` 与 SEC 文件名 `goog` 不构成实体冲突；以封面 Alphabet Inc.、CIK `0001652044` 和原件身份为准。
- 实体 DOM：`/html/body/div[20]/span/ix:nonnumeric`；期间 DOM：`/html/body/div[15]/span/ix:nonnumeric`，为 December 31, 2025；表单 DOM：`/html/body/div[11]/span/ix:nonnumeric`，为 10-K。
- 目录 `available_at` 为 2026-02-05，因此在题设 2026-02-06 截止日内。**截止日可用性本次依赖已选数据集的来源元数据，未独立联网核验 SEC acceptance 时间。** 不应以文件名中的 2025 推断报告于 2025 年已公开。

## 2. 主出处及必需上下文

以下 table / tr / td 序号均从 1 开始，按完整原始 HTML 中的实际元素计数，不展开 colspan。带 `ix:` / `xbrli:` 的路径为 lxml HTML DOM 标识；执行定位时可用 `//*[@id='…']`，避免把冒号误当未声明的 XPath namespace。

### Microsoft

- Item 8，INCOME STATEMENTS，原件印刷页 50。第 24 个 table：`/html/body/div[150]/table`。
- 表中单位为 `(In millions, except per share amounts)`；第 5 行给出 `Year Ended June 30,` 与 2025 / 2024 / 2023 表头。
- 第 12 行是 `Total revenue`；2025 数值位于 `td[4]`，2024 位于 `td[8]`。必须保留该总收入行和对应年份/单位；Product 与 Service and other 是上方组成行，不可冒充总额。
- 2025 fact ID：`F_54f7ed46-65f2-456a-a77a-3c4b7593c6fb`；2024 fact ID：`F_f3644c27-3201-4eae-830b-29806654338e`。两者均为 `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`，`unitref=U_USD`，`scale=6`。
- 对应 context IDs：2025 `C_7102029d-8d6c-44c5-b166-04cf41443b1e`，2024 `C_c19fe6c0-0e87-44b0-aa2a-d9c6e40a5862`。原件 context 明载上表起止日期、正确 CIK，且没有 segment dimension；`U_USD` 明载 `iso4217:USD`。
- 合并范围可由 Note 1 佐证：`/html/body/div[165]/div/ix:nonnumeric/p[2]` 写明 Microsoft Corporation 及子公司，内部往来和余额抵销。不是必须额外整段输出的答案。

### Alphabet

- Item 8，CONSOLIDATED STATEMENTS OF INCOME，原件印刷页 49。标题 `/html/body/div[815]`，第 80 个 table：`/html/body/div[816]/table`。
- 表格父节点包含 `(in millions, except per share amounts)`；第 2 行为 `Year Ended December 31,`；第 3 行对应 2023 / 2024 / 2025。
- 第 4 行 `Revenues` 是合并损益表的总收入；2024 位于 `td[7]`，2025 位于 `td[11]`。虽然该行未写 Total，合并表标题和无分部的原件 context 已明确范围，不能因缺少单词 Total 判缺失。
- fact IDs：2024 `f-189`，2025 `f-190`；均为 `us-gaap:Revenues`，`unitref=usd`，`scale=6`。contexts 为 `c-28`（2024）和 `c-1`（2025），原件明确给出对应自然年起止日期、正确 CIK，且没有 segment dimension；`usd` 明载 `iso4217:USD`。
- 合并范围见 `/html/body/ix:continuation[2]/ix:nonnumeric[2]/div[2]`：Alphabet 及按 variable interest / voting models 纳入合并的实体，内部余额及交易抵销。可作验证上下文，无需输出会计政策全文。

主出处已经充分。引用须能定位收入行和适用年度/单位/公司；仅链接年报首页、仅列金额或仅列 XBRL metric 名称均不充分。不要求运行 Agent 使用上述唯一 fact ID 或表号；接受其他能支持同一事实的精确原文定位。起始日期可通过正确财年表头和完整年度定义合理确定，也可直接由原件 context 证明，不应强制读取某一个隐藏元数据块。

## 3. 已核实的等价出处

同值的重复披露不必全部取回，也不提供额外覆盖分。以下仅供验收者判断出处等价性，不能变成运行时检索提示。

| 公司 | 等价披露及原件位置 | 使用条件 |
|---|---|---|
| Microsoft | MD&A 第 14 表 `/html/body/div[114]/table[2]`，第 5 行 Revenue | 2025 / 2024 金额相同。保留单位与财年语境；可剔除百分比变化列。 |
| Microsoft | Note 18 第 72 表 `/html/body/div[252]/div/ix:continuation/div[1]/ix:nonnumeric/table`，第 39 行 Revenue | 必须连同前方 Total 分组标题；单独 Revenue 行可能被误读为分部。 |
| Microsoft | Note 18 第 73 表 `/html/body/div[252]/div/ix:continuation/div[2]/ix:continuation/table`，第 11 行 Total | 地理收入合计；须保留其收入性质、单位和年度，不必带地理构成。 |
| Microsoft | Note 18 第 74 表 `/html/body/div[255]/div[1]/ix:continuation/div[1]/ix:nonnumeric/table`，第 19 行 Total | 产品和服务收入合计，前文明确 Revenue；不能拿某一产品行替代。 |
| Alphabet | MD&A 第 44 表 `/html/body/div[525]/table`，第 4 行 Consolidated revenues | 单位位于前段 `/html/body/div[524]`；保留年度，剔除变化额/变化率不损伤答案。 |
| Alphabet | MD&A 第 46 表 `/html/body/div[548]/table`，第 13 行 Total revenues | 单位位于 `/html/body/div[547]`；总额包含该表列示的 hedging gains (losses)，不需输出或重算组成。 |
| Alphabet | Note 2 第 95 表 `/html/body/ix:continuation[10]/ix:nonnumeric[1]/div[2]/table`，第 13 行 Total revenues | 单位在紧邻前段；2024 / 2025 与主表相同。 |
| Alphabet | Note 2 第 96 表 `/html/body/ix:continuation[10]/ix:nonnumeric[2]/div[2]/table`，第 9 行 Total revenues | 地理分解合计；2024 在 `td[10]`、2025 在 `td[17]`，不要误取旁边 100%。 |
| Alphabet | 第 117 表 `/html/body/ix:nonnumeric[3]/ix:continuation/div[5]/table`，第 5 行 Total amounts included on the Consolidated Statements of Income | 仅其中 Revenues 子列可用；2024 在 `td[11]`、2025 在 `td[19]`。不能取衍生工具 gains/losses 行或 Other income 子列。 |
| Alphabet | 分部注释第 163 表 `/html/body/ix:continuation[48]/ix:nonnumeric/div[2]/table`，第 9 行 Total revenues | 该总额可以用，Google Services / Google Cloud / Other Bets 各行不能替代公司总收入。 |

这是一组已经核实的等价位置，不是排他白名单。其他原文位置只要具备相同实体、指标、期间、币种、数量级及精确出处，也可通过人工验收。

## 4. 范围、冗余与验收边界

必需覆盖：四个公司—财年收入组合；各自准确起止日期；USD 与百万单位；合并总收入语义；各自所选 FY2025 10-K 的精确出处。必须逐项判定，不能以额外分部数据或引用数量补偿遗漏。

允许的表格上下文：标题、报告实体、单位、年度表头、收入行、Total 分组标签、必要的近邻文字。原表同时含 FY2023、产品/服务行或其他损益项目时，可作为不可分割的原文表格背景保留；不因这种结构性背景直接判整题失败，也不给它加分。最终整理答案仍应聚焦两年、两家公司。若检索工具只支持整表，整表取回与最终答案主动展开无关分析应分开评价。

排除：同比、增幅、差额、合计或跨公司计算；分部/产品/地区收入分析；财年可比性分析；成本、利润、EPS；其他年份作为独立答案；其他报告、新闻、数据库或截止日后的证据；根据地区收入求和并自行调整对冲。题目无需这些内容。

Microsoft Note 1 原件说 prior-period segment recast 不影响合并损益表（`/html/body/div[165]/div/ix:nonnumeric/div[3]/ix:nonnumeric/p[3]`）。因此本题不应把 segment recast / 可比性长解释列为必需上下文；这是原件核查结论，不是让运行 Agent 添加分析。

建议按三轴验收：① 必需语义覆盖；② 实体/来源/年度/币种单位/出处真实性；③ 聚焦程度。原件引用正确不等于题目完整，字段格式合法不等于内容正确。最终金额若用等值 USD billion 表达，可以承认数值等价，但必须准确标单位并保留原表百万口径；不能以四舍五入的短句替代可核对的精确原数。

未发现实体身份或财年范围冲突。唯一需要明确的来源边界是截止日 available_at 依赖本地来源元数据；本次没有联网复核公开时间。未执行系统 Agent，未评估运行质量，未产生外部 API 费用。
