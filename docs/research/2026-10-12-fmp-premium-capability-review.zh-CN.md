# FMP Premium 财务能力核查 · v0.1

日期：2026-10-12。DS-03 来源分工的文档核查；没有注册、购买、认证数据请求、公司样本验收或开发。只查看官方套餐表、Stable 文档和页面公开 Response 示例。示例不是本项目取得的真实 API 结果，不能证明权限、准确性、覆盖率或稳定性。

**结论：可保留为标准财务和部分披露明细的获取候选；完整财务与精确追溯仍需 SEC 原件及官方 IR 补齐。** 本次比上轮确认了套餐权限和具体返回形式，尚未选定供应商。DS-02 冻结不变。

## 1. 价格与套餐

公开个人套餐为 **$49/月，按年支付，计算年额 $588**；未确认独立月付价、税费或商业许可总价。Premium 对三张标准报表开放美/英/加市场；四个 as-reported、产品/地区收入、报告日期及 JSON/XLSX 行显示 Full Access；收入分部没有 Starter 列的“仅年度”标记。SEC Filings 组显示 Full Coverage。

Premium 不含 Latest Financial Statements、三张报表的 TTM 专用接口、bulk/batch 及电话会全文；Key Metrics TTM/Financial Ratios TTM 是不同接口，不能混淆。最多30年为套餐上限，不保证每个字段或证券均有相同历史。产品展示/再分发须另核许可。

证据：[官方价格及逐端点比较表](https://site.financialmodelingprep.com/pricing-plans)。浏览器检查了列标题与 Full Access 标识；纯网页文本会丢失勾选，不能把空白单元格当作未开放。

## 2. 能取得什么、如何补齐

“可以取得”在此指官方接口及套餐支持；“待验”指公开文档不足或需要实际结果核验。

| 类别 | 已确认接口与返回形式 | 边界 / 待验 | SEC / IR 承担什么 |
|---|---|---|---|
| 季度标准财务 F01–F03、部分 F05 | 利润、资产负债、现金流；季度/年度参数。利润示例含收入、成本、费用、净利、EPS、加权股数；现金流含经营/投资/融资、Capex、SBC、回购/股息等 | 标准字段集合不等于原表全部行；现金流单季/YTD、Q4推导、比较期重列与空值语义待验 | 原披露逐行逐列对账；保留实际期间、单位及原表口径，补缺失行 |
| 原披露 F01–F05、部分 F07 | 三张 as-reported 加 full-as-reported；full 示例为报告元数据＋标签到数值的映射；还出现 OCI/权益、税项、租赁、债务到期、承诺及股权激励标签 | **不应说完全没有附注**；但未证明全部事实、多维表格或同标签多个上下文均保留 | 从原件 iXBRL/XBRL 补 context、单位、维度、定义及证据；未标记内容读原表/正文 |
| 产品/地区收入 F06 | 两个收入拆分接口；annual/quarter；示例为日期、财年、期间、币种和“名称→金额” | 专用接口只证明收入拆分；产品、地区、经营分部并非同一分类。不保证利润、资产、抵销、重划与口径解释 | 分部附注及调节表；地区定义、分部变更、比较期重编和交叉维度 |
| 报告 JSON/XLSX F04、F06、F07 的候选补充 | JSON 示例有报表、OCI、权益、附注及分部明细章节，部分行有数值数组/日期/单位；参数列 Q1–Q4/FY | 页名为10-K但参数支持季度，实际10-Q覆盖待验。部分附注/分部示例只有标题、抽象行或空白；章节存在不证明正文和全部数值存在。XLSX未下载 | 原件完整性清单和细粒度证据仍由原披露建立；不以JSON章节数代替覆盖验收 |
| 出处 F00 / 全部事实 | 标准财务示例有 CIK、filingDate、acceptedDate；SEC检索提供 link 申报索引与 finalLink 文件链接 | 所查标准报表示例没有 link/finalLink；raw和分部示例没有逐值文件/表格定位。不能仅凭ticker＋期间把一份申报指定为所有数字出处 | 用发行人、申报accession、版本和事实匹配原件；保存原表行列/正文证据及hash |
| 历史版本 F00 | 有历史期间、申报日期，raw示例有amendmentflag等标签 | 没有在所查财务接口确认 as-of/vintage 参数或供应商首次可得时间；as-reported 不等于全部历史版本/PIT | 原始/修订申报与后续重编分别留存；公开时间、供应商可得时间、取得时间分开；未知保持未知 |
| 非GAAP、指引及解释 F08–F09 | 本次所查接口不能证明完整覆盖 | 三表、比率或报告标题不能替代调节表、适用条件和管理层解释 | 8-K附件、10-K/10-Q及官方IR业绩发布/财务补充；未进SEC的IR材料仍从公司取 |

字段证据：[利润表](https://site.financialmodelingprep.com/developer/docs/stable/income-statement)、[现金流](https://site.financialmodelingprep.com/developer/docs/stable/cashflow-statement)、[原披露全集](https://site.financialmodelingprep.com/developer/docs/stable/as-reported-financial-statements)、[产品收入](https://site.financialmodelingprep.com/developer/docs/stable/revenue-product-segmentation)、[地区收入](https://site.financialmodelingprep.com/developer/docs/stable/revenue-geographic-segments)、[报告JSON](https://site.financialmodelingprep.com/developer/docs/stable/financial-reports-form-10-k-json)、[SEC申报检索](https://site.financialmodelingprep.com/developer/docs/stable/search-by-symbol)。

## 3. 三个容易误判的地方

1. **标准字段可能由 FMP 计算。** 官方解析说明写明对未直接披露的部分字段计算补齐。因此标准化值不能一概标为“原文直接披露”，需要保留来源类别和计算依据。官方称通常SEC申报后约15分钟可得；这是供应商描述，不是本项目实测或SLA。[解析方法](https://site.financialmodelingprep.com/developer/docs/parsing-statements)
2. **raw标签集合不等于完整事实模型。** 所查full示例顶部为 `symbol/fiscalYear/period/reportedCurrency/date/data`，`data` 为平面标签映射。未见逐值contextRef、unitRef、axis/member、期间起止和原件定位。由此推断存在多上下文表达风险；不能仅凭示例判定实际服务必定丢数，也不能认定已解决。
3. **两类链接用途不同。** Financial Reports Dates 返回 `linkJson/linkXlsx`，指向FMP转换报告；它不是SEC原件目录。SEC检索的 `link/finalLink` 才指向申报索引/文件，但仍不是数值与原表的逐值映射。[报告目录](https://site.financialmodelingprep.com/developer/docs/stable/financial-reports-dates)

SEC CompanyFacts/CompanyConcept 可补标准合并事实，但官方聚合范围限非自定义taxonomy、整发行人上下文。**分部、自定义标签和全部附注不能仅靠 CompanyFacts 补齐**；需要申报原件的XBRL/HTML和必要IR材料。[SEC API能力边界](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)

## 4. 获取职责建议（未接入）

- **FMP标准三表**：提供方便查询的数值候选，不承诺原表逐行完整。
- **FMP raw＋报告JSON＋收入拆分**：补披露标签、部分细表及收入分类；保存原始响应，逐项判断可采纳内容。
- **SEC/IR原件**：建立披露目录、全部事实分母、精确出处、定义与版本；补齐供应商空缺和冲突。
- **我们承担的工作**：身份/期间/单位匹配、证据关联、差异诊断、未覆盖事实解析和显式派生。Q4/TTM计算必须先验证期间及同口径输入；EPS、平均股数等不能简单套用可加金额的差分公式。此处未冻结公式，也未实现。

技术入口以 Stable 文档为准。已观察路径：`income-statement`、`balance-sheet-statement`、`cash-flow-statement`；`income-statement-as-reported`、`balance-sheet-statement-as-reported`、`cash-flow-statement-as-reported`、`financial-statement-full-as-reported`；`revenue-product-segmentation`、`revenue-geographic-segmentation`；`financial-reports-dates`、`financial-reports-json`、`financial-reports-xlsx`；`sec-filings-search/symbol`。这些是接口清单，未调用；不把旧 `/api/v3` 或 `/api/v4` 样例当Stable返回契约。

## 5. 采购前仍需关闭的最小问题

| 问题 | 为什么影响选型 | 后续验收（本轮未执行） |
|---|---|---|
| 五年/二十季实际覆盖、季度流量和Q4算法 | 历史上限与quarter参数不足以证明范围和口径 | 对照冻结原件清单；区分时点/单季/YTD、原披露/派生；缺期单列 |
| raw/JSON的附注与分部完整性 | 可能减少解析量，也可能只提供部分行/标题 | 原件独立列全事实、条件、维度；按值/单位/期间/定义对账；记录缺失、额外及错误，不用返回字段数作分母 |
| 数值→确切申报版本→原表的连接方式 | 文件链接不足以满足精确追溯 | 每个采纳值均可核对文件版本、原表行列或正文，连接不确定则不声称可追溯 |
| 历史修订与可得时间 | 影响历史查询和避免未来信息混入 | 对照原始/修订/重编版本；无法恢复的版本明确留缺；不推算供应商历史可得时间 |
| API权限、留存及拟定使用场景许可 | 个人公开价不等于所有产品使用权 | 取得对应套餐书面说明或授权样例；不能用另档样例证明Premium权利 |
| 更新/纠错和连续可用性 | 官方实时描述不证明稳定 | 后续按既定DS-03文件检查与独立连续观察验收；不在本轮启动 |

**后续路径更新**：先使用FMP Basic/Free验证鉴权、限流、Schema、少量返回及SEC关联，再决定是否需要Premium。Free仅能证明受限权限下的实际表现，不能证明本报告列出的Premium覆盖。Data Agent材料边界见[专门说明](2026-10-12-data-agent-material-boundary.zh-CN.md)。供应商注册、认证调用、具体公司获取、购买与开发均未启动。
