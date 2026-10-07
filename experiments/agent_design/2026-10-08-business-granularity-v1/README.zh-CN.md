# 09：业务总览与明细粒度核查

2026-10-08。当前问题是 Microsoft 图过碎，看不到公司的经营结构。**主要证据指向我们的任务契约与默认展示；没有证据可以把这一现象直接归因于底稿解析失败。** 用户将本阶段基础任务限定为 HTML 10-K。

## 官方报告对照

以下只核对 FY2025 原报告，不能套用后来重组的报告口径；这是 Codex 官方资料核查，不冒充新的系统 Agent 提取。

| 公司 | 原报告的分部结构 | 说明 |
|---|---|---|
| Microsoft | Productivity and Business Processes、Intelligent Cloud、More Personal Computing | 分部下继续列业务组合及具体产品。产品多不等于每个产品都是同级主要业务。[官方年报，Operating Segments](https://www.microsoft.com/investor/reports/ar25/index.html) |
| Alphabet | Google Services、Google Cloud、Other Bets | Services 同时包含多个产品与平台；不能把产品清单全部当成独立分部。[官方 10-K](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000018/goog-20251231.htm) |
| Meta | Family of Apps、Reality Labs | 应用家族包含 Facebook、Instagram、Messenger、WhatsApp 等；业务、产品与收入构成是不同维度。[官方 10-K](https://www.sec.gov/Archives/edgar/data/1326801/000162828026003942/meta-20251231.htm) |

## 为什么两版粒度不同

Microsoft run09 有 79 节点：公司1、分部3、offering_group16、business59。冻结 graph-stage Skill 要求所有产品/客户/变现属性为空，并将已定义产品、平台、组合单列节点。覆盖规则又把很多自有产品提及的非 node 处置当成失败。默认完整图把这些层级同时铺开。于是 CALs、产品云子集等也被装进 business 类型。

Google 旧 Sonnet 产物是 13 节点、14 关系；它采用旧 Skill v0.3，产品可留在 `products_services`。这不是控制变量一致的模型对比。Meta 在本次检索的原件、Agent 运行和验收目录中尚无真实提取产物，只有公司名单与股票回测等记录。

实际结果入口：

- [Microsoft 新总览](http://127.0.0.1:8769/docs/design/data-agent-acceptance/microsoft-business-overview-v1/)：同一 run09 候选，新的阅读投影。
- [Google 旧 Sonnet 提取](http://127.0.0.1:8769/docs/design/data-agent-acceptance/agent-business-revenue-v1/?view=business)：FY2025 冻结选段，仍为候选。
- [Google 旧 Opus 提取](http://127.0.0.1:8769/docs/design/data-agent-acceptance/opus-stream-recovery-v1/?view=business)：同一旧选段，仍有语义缺口。

## 本轮已实现

从候选现有的 `part_of/reported_under` 关系选出公司、可到达的报告分部、分部直接构成，以及已有祖先路径。没有分部时只选择公司及其已有直接构成。共享对象按 ID 去重；unknown 边不作为归属。没有公司、非法端点、缺关系依据或旧协议均明确拒绝，不猜测关系。

Microsoft 默认总览 **13 节点、12 关系**。其余57个下层对象、9个没有通向公司根节点的归属路径的对象都仍可在完整图和原文详情查看。13+57+9=79，完整图86条关系不变。显示布局不表示收入权重或重要性排序。同层沿用候选的关系，不保证原文同级。GitHub 等缺少根路径的对象有单独入口，不能因折叠而掩盖这些缺口。

沿用已有 Mermaid、节点身份、点击出处和三分部视图。新页单独保存；旧图、请求、候选、费用、评价均未重写。原始提取由系统 Agent 完成，本轮 Codex 只实现确定性展示投影。内容仍为 `needs_work`，不能用清晰度改进冒充语义验收。

验证：6项投影测试、4项原渲染边界测试；实际SVG节点/边/原文映射与744条本地链接通过。没有浏览器视觉验收。Google旧产物是v0.1、缺少关系basis，已明确拒绝新投影，不自动赋予explicit。通用行为目前另由无分部、循环、多父、孤立分部和缺范围等合成例检验，不能声称真实多公司新协议已通过。

## Claude 顾问与 Codex review

已在原私密上下文追加第16轮顾问复核，实际估算$0.396532；原上下文与原答留在原会话。本轮没有执行Agent模型调用。顾问赞同先修总览、再升契约，具体采用与修正见[复核记录](advisor-review.json)。

Codex 未直接采用“Alphabet作为holdout”：它是历史已用公司，只能作为回归。也未采用“等待视觉批准才可做后续工程”；用户已授权继续。程序能检查引用存在与字段非空，不能独立证明重要性或语义支持。

## 紧接着的一个行动

升级09的**提及到产物的覆盖契约**：重要经营对象保留身份，产品/能力可以有据映射到非空属性；node、attribute、context、unresolved分别记录，空deferred不能算覆盖。输入、Skill、契约与评价标准须冻结到新版本，历史规则不回写。先以 Microsoft 与 Google 做同版本回归，再将 Meta 作为新增公司样例；没有提前跑出 Meta 的假结果。

验收：每个提及有可核对去向；重要业务和关系无未解释遗漏；总体/子集范围及逐声明引文正确；首页与展开详情能共同覆盖；系统 Agent 独立生成。仅改变节点数不算通过。
