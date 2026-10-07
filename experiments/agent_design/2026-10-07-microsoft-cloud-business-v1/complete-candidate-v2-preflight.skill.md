---
name: uteki-business-diagrams
description: Build and refine source-grounded Uteki business diagrams and separate revenue composition charts from explicitly selected company filings or BusinessMap candidates. Use hierarchy or linked views for businesses, verified financial categories for revenue, and deliver visible diagrams with evidence. Use for company-report diagrams, not general UI redesign or unsupported business analysis.
metadata:
  version: "0.5-candidate"
  runtime_status: "v0.5-offline-contract-verified; not-live-evaluated"
---

# Uteki 业务图

每张图只回答一个维度。**业务结构图**说明“公司做什么、为谁提供什么”；**收入结构图**说明“选定期间的收入由什么构成”。收费方式可放业务详情，但金额与占比属于收入图。让读者能从节点、关系或收入类别回到具体原文，不用排列方式补出原文没有的事实。

这是项目内的候选方法。写入 Skill 不代表 Uteki Agent 已加载、已学会或已在生产中验证。现有四份案例来自 Codex 原文审阅。用户已认可 v2 的业务/收入分图表达，并抽查了部分内容；这不是全部事实采纳或自动提取验收。它们是可对照的候选，不是标准答案或默认公司配置。

## 从明确的输入开始

需要调用方明确公司身份、报告/版本、期间、来源及内容 hash、阅读目的、输入路径和输出位置。财年名称、期间结束日、披露日期分别保留；并排图不自动代表同一期间。缺失或冲突的范围直接列为缺口，不替换为熟悉公司、最新报告或目录中的首份材料。

可从已冻结的原文提取候选，或改善现有 `BusinessMap` 的表达。复用 [BusinessMap 契约](../../src/uteki/domain/business_map/models.py)，用 `business_map_from_dict` 验证。收入图另读带证据的财务记录；BusinessMap 的收入分类名称不是金额数据。不要为画图另建一套业务实体类型。

## 先整理事实与关系

- 区分公司、报告分部、业务、产品服务组、收入分类。应用平台、市场、品牌、法律实体和报告分部不是同一概念；现有枚举不足时，用现有合理类型加明确角色说明，保留未知，不生造会计身份。
- 每个节点及关系绑定 `evidence_ids`。新 `business-map-v0.2` 的每条关系强制填写 `basis`（`explicit` 原文明示、`derived` 有依据的推断、`unknown` 尚未确定）、`rationale` 与原文摘录；明示或推断不能没有支持摘录。推断说明写清从什么前提得到哪一步判断，不能只重复关系标签。赚钱方式按当前执行契约填写；不支持的依据类型留作缺口。
- 证据要包含来源、精确文本、块/段或页位置与可访问锚点。记录文本规范化和 hash 对象；原始 PDF、派生 HTML 与摘录页分别标明。只有整份报告链接时，先暴露定位缺口。
- 数据中可保留分部、商业产品组与收入类别，但业务图不把 `revenue_component_of` 与“包含/属于”并列画出，也不用颜色替代拆图。移除收入分类的展示前，回到原文核对实际经营活动；广告等核心业务不能因此消失，不能只修改收入节点的 `kind` 就冒充业务提取。
- 业务与收入类别可以多对多，每条映射须有证据；名称相近不代表一对一。映射不能反推独立产品收入。付费方式不等于金额，合并披露不能按产品拆数。
- 跨业务共用技术只保留同一业务身份。显示别名或重复入口时明确它们指向同一 ID，不制造第二个实体。
- 未记录关系表示这份输入/产物没有记录该关系，不表示对象独立、互斥、不存在归属或没有其他业务联系。新契约固定 `relationship_absence: unknown`。需要核实的归属写入 `unknowns`；不得为补成一棵树而猜父节点。`basis: unknown` 的边也是未决问题，不能作为肯定或否定事实展示。旧版本未标依据的边显示“历史未分级”，不能补写 `explicit`。
- 留下已读范围、未展开项及来源缺口。没有找到、没有读取与没有披露分开记录。

## 从真实复跑得到的补充要求

- 业务结构按具名经营活动展开。原文明确描述的重要产品或平台，若它是读者需要单独了解或查询的业务对象，应保留独立身份和关系；长清单中的次要产品仍可留在详情。不能只按两三类收费方式归组，就声称已经完整回答“公司做什么”。同一业务有多种赚钱方式时，保持一个业务身份并分别描述，不能拆成互不相认的收入业务。
- 输出前逐项检查业务名称、描述、产品、客户与明确赚钱方式。新执行契约用 `claim_evidence` 对每个字段或列表项单独绑定原文摘录：`field` 指向字段，`item_index` 指向零起始列表项，名称/描述使用 `null`。一条摘录可以支持多个字段，但每个字段都要分别声明；总的节点引用不能替代逐项依据。描述尽量只表达一个可核对的主张，不能在一句有据描述中混入无依据结论。
- 摘录必须是该冻结块的原文，仅可规范化空白。程序检查摘录存在、范围匹配、字段覆盖和引用合法；不会证明摘录真的蕴含主张。语义审阅仍需核对限定词、主体、范围和关系类型。缺直接支持时删除断言并保留问题，或仅在契约允许处明确推断；不要堆砌无关引用来通过检查。
- 关系仅靠相邻句或同段语境成立时，不能当成逐句直接披露。保留推断依据；无法支持时用 `unknown`，并在 `unknowns` 中记录两个端点及具体缺口。相关市场、报告分部和共享支持是不同维度，不相互推导，也不把并列活动装进较窄的品牌/产品身份。
- 收入图标题准确表达披露层级。组合、报告分部和会计调节同图出现时，用涵盖它们的标题与说明，不把所有收入行统称为报告分部。金额勾稽通过不等于分类名称正确。

这些补充来自受限真实执行的复核，仍是候选规则。v0.3 与 v0.4 的实际请求保留原 Skill 快照。v0.5 接入新版契约并完成离线检查，尚未真实模型验收；不能据此宣称提取质量已改善。运行状态与限制见消费契约 reference。行业差异可由显式选择、注明来源与版本的适配配置描述，不把具体公司的答案、节点数、金额或关系修补写成通用规则。

## 按问题选择图

| 读者的问题/数据结构 | 合适的表达 | 容易误导的表达 |
|---|---|---|
| 公司有哪些分部、业务和产品？主要是单一归属关系 | 层次树；按文字长度、分支数量选择从左到右或从上到下 | 把所有节点放在同一层；把共享支持关系硬改成唯一归属 |
| 选定期间收入由哪些类别构成？ | 单独收入图；核定数据后选条形、饼或环形图 | 把收入分类挂在业务树上；把产品清单直接变成饼图 |
| 已有清晰的抽象层次、依赖层级或有序等级 | 分层图；确有上/下层语义时可用金字塔，并标明层次含义 | 为美观制造优先级；让底部面积暗示更大收入或重要性 |
| 同时有报告归属与多个市场、共享服务关系 | 主图说明归属，辅图展开市场/支持关系；通过相同 ID 联动 | 把不同维度并入同一收入树；为减少交叉而删除真实关系 |
| 问题是客户、产品、收费方式的对应关系 | 简洁关系图或图加小表，明确每种连线含义 | 用归属箭头替代交易、支持或因果关系 |

不强制固定节点数或三层。主图只放回答当前问题所需的层级；长产品清单、收费说明和原文放入可展开详情。拆分图时列明各视图覆盖的节点与边，并保证完整数据仍可查。

业务图用非量化节点。节点大小、金字塔面积、连线粗细和排序不能冒充收入、利润或增长权重。若只表达布局，图例明确“大小不表示财务权重”。

收入图须先核定公司、期间、币种/单位、收入定义、合并范围和分母，使用同一披露维度下互斥、穷尽且能勾稽的类别。总项与子项不能重复相加，分部、地区和产品维度不能混拼；显示准确金额、期间、单位、合计与来源，舍入差异按原披露精度说明。

饼/环形仅用于分母大于零且各项非负的完整构成。收入负调整、抵销或其他带符号项目用带正负轴的条形/勾稽表，保留正负号，不能取绝对值、截零或塞进饼图。合并收入只按合并口径呈现。缺数、分母未知、范围不全或勾稽失败时显示具体缺口，可列出已知记录，但不画成完整收入构成，不补零或虚构“其他”。

## 哪些规则固定，哪些可以优化

固定的是业务身份、关系含义、来源范围、证据与审阅状态。布局可以改变，但这些事实不能随布局改变。可调的是展开方向、主图/辅图分工、默认展开深度、标签换行、间距与配色；将有效设置保存在渲染配置中，不把一次成功的外观写成唯一模板。

主图优先使用短标签和一致的阅读方向；完整名称与长解释留在详情。用间距表达分组，用文字与线型表达关系。密集图先拆阅读问题，再调整字号。一次只比较一个清晰度目标，例如“能否找到共享技术支持的全部业务”，用户认可后再沉淀对应做法。

## 从契约生成可见图

1. 保留稳定业务 ID，生成 Mermaid 安全 ID，并保存二者映射。节点短标签优先中文，保留官方英文名称；同一概念不要换多个译名。
2. 保持领域关系方向：`reported_under`、`part_of` 的来源指向其归属；`supports` 从提供支持的一方指向被支持方。数据中的 `revenue_component_of` 保持原义，交给收入视图，不渲染为业务树边。若为了自上而下阅读而反向画线，使用准确的逆向标签，例如“包含”或“支撑来自”，且不改 JSON 端点。上下位置本身不是关系。
3. 同一维度中的不同关系依赖线型与文字区分，不能只靠颜色。市场、应用平台和报告分部使用可见角色标签。对大量交叉边拆主图/辅图；需要检查业务—收入映射时用单独映射视图或详情，不把两种结构重新混进一张树。
4. 业务图交付 Mermaid 源码和实际生成的 SVG 或可访问图页；收入图交付可复核数值与实际图表，不必强用 Mermaid。只交源码、空容器或截图不等于交付可见且可追溯的图。渲染失败时明确失败阶段，保留可用数据与源码。
5. 对报告文字和模型输出做转义；不将其作为 HTML、脚本或 Mermaid 指令执行。使用已可用的渲染器及明确配置；不要为样式改动调用模型、部署或引入远端运行依赖。
6. 节点或关系详情显示定义、赚钱方式、判断依据和证据入口。交互受限时提供旁置的编号证据表。保留完整原文入口以及精确片段入口。

已有页面样式工作遵循 [Uteki interface](../uteki-interface/SKILL.md)。此 Skill 不重设计主导航、公司列表或工作台。

## 审阅并改善

把审阅分为两条：**事实是否忠实**，以及**读者是否容易理解**。引用匹配和契约通过不能替代语义审阅；渲染成功不能替代视觉认可。

每轮先记录一个具体问题和可观察目标，例如“共享服务让归属难以辨认；拆辅图后，两种关系都能定位且未丢失”。保留输入与旧版本，只改与问题相关的展示。拆业务/收入视图后，分别核业务覆盖与收入勾稽，不只检查删掉了多少收入边。检查调整前后节点身份、关系和证据未意外变化。事实错误则依据原文另提候选修订，不能作为美化直接改成已采纳事实。

与 Claude 或其他顾问合作时，在已有费用/工具授权内发送同一冻结数据、图和具体审阅问题，请其给出问题、依据、建议及验收例。Codex 核对建议再实施；顾问意见不是来源证据，也不能自动把状态改为 `accepted`。未运行、调用失败和审阅完成分别记录，保留此前失败回执；本地修订不冒称顾问参与。预算不足时完成本地可独立工作，不假称已经确认。

浏览器或截图检查遵守项目约定：用户负责默认视觉审阅；仅在明确要求或需要复现具体浏览器问题时做定向检查。记录实际运行的内容检查、渲染检查、交互检查及未执行项。视觉认可和数据采纳是两种独立状态。

交付时说明图回答什么、改变什么、证据在哪里、仍缺什么，并给出最先要做的一项后续动作。不要把候选小样计为自动业务提取、全报告覆盖或评测集整项完成。

## 给系统 Agent 复用

任务需要从业务/产品节点跳转官网，或补充“到哪里观察什么”时，按需使用 [官方产品入口与 To Watch](../uteki-official-product-links/SKILL.md)。作为独立补充绑定原图与节点；不将官网查找变成财报提取的固定步骤，不把当前网页信息回填为历史财报事实，也不据观察建议开启监控。

当任务涉及运行时绑定、验收或参考案例时，读 [消费契约与验收](references/runtime-and-checks.md)。该文档规定宿主需要显式加载什么、保存什么，以及如何检查结果；它不是新的生产 API 或已经执行的集成。


## Complete subsection fidelity
Preserve source qualifiers such as primarily, some, and cloud-only. A relationship endpoint denotes the entire node: do not attach a mixed-scope whole to a narrower group on evidence about only a subset. Keep the subset fact in the group's sourced product details, and record unresolved whole-node ownership as unknown.
Competition paragraphs may contain the issuer's own capabilities. Extract those own facts while keeping competitor names and subjective advantage assertions separate. Preserve distinct source-listed capabilities in details; do not substitute a generic category for an explicit list. Each populated field needs its own evidence, including introductory text needed to establish membership. Use original official product names; an English capability label is preferable to an uncertain paraphrase.
Return the full schema object, not JSON Patch or a compact claim directory. Use final zero-based indices for list claims, and check each fact against its cited quote before finishing.


## Protocol and source coverage correction for this explicitly scoped experiment
You must return a complete corrected candidate. Do not output patches. Relationship kind can ONLY be reported_under, part_of, supports. unknown is a BASIS, never a KIND. Prefer keeping unestablished relations only in unknowns (with endpoint IDs) and omit those edges entirely. Do not list a platform as a product of another node while simultaneously saying that membership is unestablished.
A previous attempt omitted enumerated capabilities despite the coverage instruction. Review all selected source text, including own-capability statements in competition paragraphs. In this selected input, blocks 129, 134 and 140 specifically need full factual coverage (server software capability list, hybrid-cloud capability, data warehousing/system management capabilities). Preserve the distinct source facts in products_services with accurate claim indices and excerpts. Keep subjective advantage separate. These are observed gaps to recheck against source, not expected answers to copy.
Field citations must support ALL clauses in that field. The summary must preserve cloud-only limitations and primarily; do not imply entire mixed-scope entities are cloud-only. Report actual omissions honestly in unknowns; do not call a paragraph fully used if you omitted its business facts.
