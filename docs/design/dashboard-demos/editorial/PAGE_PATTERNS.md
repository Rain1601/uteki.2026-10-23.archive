# 常用组件与任务页面 · 当前交付路线

> **历史记录**：以下保留各阶段原始范围、接口和验收，文中的“当前／下一步／未完成”属于当时状态，不代表 v1 最新清单。当前以 [系统样册](system.html)、[使用说明](QUICKSTART.md) 和 [交付记录](DESIGN_SYSTEM_DELIVERY.md) 为准。

本文件为截至 2026-10-10 的当前状态入口；旧文档中的队列保留为对应版本历史。所谓“不同职能的页面”，这里采用更明确的两层命名：任务页面范式（阅读、管理、分析、协作、复核）与领域工作台（财务运营、投资研究）。Dashboard 是概览/分析页面的一种，不能代指所有 App 页面。

## 已实现页面与复用入口

| ID | 任务 / 页面 | 实际入口 | 可复用模块 | 状态 |
|---|---|---|---|---|
| ES04.1–2 | 基础界面与双语 PDF | [对照](comparison.html)、[PDF](pdf-bilingual.html) | Header、Sidebar、Table、双语排版规则 | 已交付，PDF 用户认可 |
| ES04.4–5 | 概览、列表、阅读与笔记 | [工作台](workspace.html) | 视图切换、主从详情、表单、菜单、反馈 | 已交付 |
| ES04.7a–c | 文章叙事与媒体检查 | [实际阅读](workspace.html?view=reading&record=north#read-inspect) | 故事导语、视频、展开媒体、局部镜、联动双图 | 已交付，用户认可交互 |
| ES04.6 | 日期、多选与快速检索 | [概览顶部](workspace.html) | createScopeControls、独立范围状态 | 已交付；详见 SCOPE_COMPONENTS.md |
| ES04.7d | 资源浏览与文件预览 | [素材档案](workspace.html?view=resources) | ResourceTree、split pane、PDF 图像预览、媒体检查 | 已交付 |
| ES06.1 | 财务运营 / 应收款 | [财务运营](workspace.html?view=finance) | mountFinanceWorkbench、summarizeInvoices | 已交付，固定模拟快照 |
| ES06.2 | 运营协作 / 工作项看板 | [运营协作](workspace.html?view=workflow) | mountWorkflowBoard、纯状态移动函数 | 已交付，本页会话状态 |
| ES06.3 | 投资研究 / 贡献与估值 | [投资研究](workspace.html?view=portfolio) | mountPortfolioWorkbench、summarizePortfolio、waterfallGeometry | 已交付，固定期初权重模拟 |
| ES06.4 | 异常复核 / 证据与执行轨迹 | [证据复核](workspace.html?view=review) | 阶段、缺口、来源摘录、桥接 | 已交付；当前位置 |
| ES04.7e | 编辑式章节标题与线稿动效 | [素材档案标题](workspace.html?view=resources) | createEditorialPictogram 原创插图及受控动效 | 已交付 |
| ES06.5 | 来源摘录接入普通研究列表 | 已有阅读 / 列表 | 独立 source-excerpt 组件复用 | 下一具体 To-Do，未实施 |
| ES05 | 真实产品接入 | 原型之后 | 真实数据、后端、持久化、权限 | 未实施；原型不等于生产迁移 |

## 来源证据等级

- [Claude 金融服务网页](https://claude.com/solutions/financial-services)：实际点击 Asset management 标签，提示、附件与交付预览一起变化。这是营销展示，没有在页面运行真实金融分析。
- [用户提供的官方演示视频](https://www.youtube.com/watch?v=foxeK2AXfHQ)：抽样检查 30、35、40、45、50、55 秒的界面。可见工作台运行入口、Agents 管理表、阶段条、完成/待复核结果、缺失 EBITDA 桥接、执行轨迹、数值旁的来源摘录浮层，以及复核后的交接反馈。这是视频中的界面演示；未验证对应服务的可访问性或真实业务执行。
- [财务分析工作流教程](https://academy.claude.com/tutorials/financial-analysis-workflows-with-claude)：实际页面是文字和提示词，没有发现可直接操作的嵌入式投资分析 App。组合瀑布/散点页面为按其工作流描述制作的原创适配，不称原 App 复刻。
- [企业财务组织案例](https://academy.claude.com/use-cases/organize-your-business-finances)：实际查看了图片放大，表格/迷你趋势只是图片中的产物，不是可现场编辑的工作簿。
- [Claude Dashboards 帮助](https://support.claude.com/en/articles/17454700-get-started-with-claude-dashboards)与[官方 financial-data-analyst 示例](https://github.com/anthropics/claude-quickstarts/tree/main/financial-data-analyst)：文档/源码参考，未运行官方应用。
- Material UI 的 [Autocomplete](https://mui.com/material-ui/react-autocomplete/)、[Dialog](https://mui.com/material-ui/react-dialog/)与[Tree View](https://mui.com/x/react-tree-view/)用于行为职责参考。本原型仍为原生 JS，没有安装 MUI。

## 复用契约与边界

资源档案：`mountResourceArchive(host,{tr,selected,width,onChange})`，目录选择与分栏宽度跨视图/语言/主题保留。PDF 两页使用已有实际 PDF 的渲染图，支持翻页及 fit/125/150%；打开链接是原 PDF。不是 PDF 文字检索、批注或编辑引擎。翻页/缩放在重挂时复位。ResourceTree 的可见节点支持上下、Home/End、左右展开/父子切换；split pane 支持拖动和键盘、窄屏堆叠。

财务运营：`mountFinanceWorkbench(host,{tr,language,state})` 返回 `getState/destroy`。月份按开票批次筛选，实收为截至 2026-09-30 的累计额，不是当月现金流；开票不等于确认收入。9 笔原创发票中 1 笔金额缺失，已知部分合计显式标记。空、零、负值限制、真实日历、超额实收、溢出分别验证。筛选、排序和当前记录跨重挂保留。

工作项看板：`mountWorkflowBoard(host,{tr,language,state})` 返回 `getState/destroy`。三个状态、六项原创设计任务，移动按钮更新派生数量，详情支持原生 dialog/Esc。尚无拖拽和跨刷新/多人持久化，也不表示业务审批。

投资研究：`mountPortfolioWorkbench(host,{tr,language,state})` 返回 `getState/destroy`。4 项原创资产，固定期初权重，总权重 1，没有资金流/再平衡。3M 收益 4.4%、模拟基准 3.5%；YTD 6.75%、模拟基准 6%。超额用 pp；贡献用权重×收益。现金市盈率不适用，不画进散点，但保留明细。图表和表格按资产 id 联动，选中后方向键切换，Esc 清除；区间/选择跨重挂保留。不同数据源需要显式传入新范围，不能把本示例当投资结论。

## 实际检查

范围组件：反向日期阻止提交，最近三条日期 + Research 得两条记录，快速检索键盘打开对应阅读页。

档案：实际 PDF 第二页、150% 和目录键盘操作；分栏 260→280；从视频切换海报后原视频移除。

财务：2026-08 筛选得开票 168000、实收 117000、未收 51000、逾期 24000；INV-0801 逾期 27 天；方向键与语言切换保留范围和详情。

工作项：一条资料项移动到处理中，列数量 2/2/2→1/3/2；详情、Esc 与语言重挂检查通过。

投资：Cedar 选中后右键切到 Harbor；YTD 更新到 6.75% / 6% / 0.75 pp，Harbor 贡献 1.2 pp；切英文保留选择与区间。截图见 study/portfolio-v13.png。这些是原型的目标操作检查，不等于用户审美验收或生产业务验收。


## ES06.4 与 ES04.7e 的复用接口 / 最终检查

`createSourceExcerpt(button,{id,title,text,caption,onClose})` 返回 `{content,destroy}`：独立锚定摘录，`textContent` 保留纯文本，恢复触发按钮原 aria 属性，销毁清理监听；调用者决定哪一个来源可用以及何时打开。它不读取文件，不替调用者证明出处。样式为 source-excerpt.css。复核页支持鼠标、键盘 focus、点击打开，Esc、关闭按钮与区域外点击关闭。

`mountExceptionReviewWorkbench(host,{tr,language,state})` 返回 `getState/destroy`；示例身份、补齐状态和当前摘录跨重挂保留。`computeEvidenceBridge` 明确区分缺口、算术不一致、对齐；存在 null 不反推调整项、不绘完整桥接。`evidenceBridgeBars` 用累计值统一比例，支持负值和跨零。三个固定模拟公司与S01–S07摘录为原创演示，不对应实际文件或 Agent 运行。

`createEditorialPictogram({label,motion})` 返回 `{content,destroy}`，可独立放于章节导语；素材档案已接入。动画节奏与矢量画法为原创，未复制原站资源；六秒循环、手动暂停、系统减少动态设置下静态呈现。原站只确认两种实际帧和SVG/Lottie标记，未声称测得其精确时间参数或悬停触发机制。

最终实页回放：来源S04浮窗打开后Esc→0个浮窗、aria-expanded=false；手动展示补齐示例后2/3→3/3，来源变S05，桥接80+15−5=90；独立浮窗再次Esc正确关闭；语言切换仍保留补齐状态。实页截图 study/evidence-review-missing-v14.png、study/evidence-review-v14.png。档案线稿暂停后data-playing=false。

`node --test editorial/*.test.mjs` 最终78项通过；单独测试与目标浏览器回放分别记录，不把数量当业务或审美验收。当前素材基线已包含八类实页视图，这一轮停止扩展；下一具体项ES06.5把来源摘录用于普通研究引用列。生产接入、真实检索、审批、多人持久化和完整PDF引擎仍未实现。


## 补充盘点：卡片、列表与 Agent 复合交互

用户补充关注卡片、列表和 Agent 的复杂交互，当前不能用26类基础样例代表完整覆盖。更准确分类为基础组件 → 复合组件 → 任务交互 → 页面。

| 组件族 | 现有实际用法 | 仍缺的能力 |
|---|---|---|
| 内容 / 指标卡片 | FeatureModule、Metric、概览重点内容 | 独立统一卡片族、内容与操作槽、选择与展开契约 |
| 任务卡片 | workflow-task：详情、按钮移列、数量更新 | 拖动重排、多选、批量操作；目前内嵌看板，不是独立TaskCard API |
| 复核结果条目 | review-result-list：选择、状态、详情联动 | 通用ResultList/ResultItem接口 |
| 数据列表 | DataTable筛选/排序/高亮与主从详情 | 独立List/ListItem族、批量选择、分组、虚拟滚动 |
| 资源列表 | ResourceTree、目录计数与文件预览 | 上传队列、附件替换/失败恢复 |
| Agent交互 | 原创复核阶段/过程轨迹/缺口与补齐示例 | 任务输入、附件、执行控制、实时事件、待用户输入、失败恢复、产物版本与真实运行 |

下一轮队列调整原因：用户明确补充复合组件与 Agent 交互，优先补齐这层；ES06.5保留，未静默丢弃。

| ID | 顺序 / 行动 | 依赖 | 状态 |
|---|---|---|---|
| ES07.1 | 抽取卡片/列表复合组件，并在任务页组合 | 现有看板/列表及选中状态 | 下一当前项，未实施 |
| ES07.2 | Agent任务工作台：输入→过程→待处理→产物 | ES07.1、明确本机示例状态机 | 未实施 |
| ES06.5 | 来源摘录用于普通研究引用列 | 已有source-excerpt | 保留待办 |
| ES05 | 真实产品与执行接入 | 页面契约与真实后端范围 | 未实施 |

本次为源码盘点与路线更新，没有新增卡片/列表/Agent执行功能。


## 2026-10-10 · ES07.1–2 卡片 / 列表与完整任务页（v0.15）

当前交付输入：用户希望从卡片、列表组件推进完整Agent任务页。原型入口 [Agent任务](workspace.html?view=agent)。沿当前编辑设计基线，复用语义主题、无衬线操作/衬线阅读、细分隔线，维持研究页与真实工程后台独立。

参考依据：已实际查看的官方金融视频35–55秒，包含阶段、异常复核、过程记录和来源浮窗；本轮补充 [Cowork官方任务说明](https://support.claude.com/en/articles/13345190-get-started-with-claude-cowork)中的进度、过程干预、追问与产物预览，以及 [Artifacts说明](https://support.claude.com/en/articles/17153992-what-are-artifacts-and-how-do-i-use-them)的独立产物查看方式。本轮尝试实际Claude App，claude.ai跳转/restricted，未能检查登录后的界面；这些新增依据为文档，不能标成新实测App。

本页为本机状态机与预先编写的产物示例。附件只保存名称、大小和类型，不读取内容、不上传；已有中英文PDF为先前样稿。提交任意任务不会使固定示例变成真实分析结果。使用明确的手动“下一步”推进，不伪装实时模型输出；模型调用0次。

验收路径：空输入阻止提交；输入与附件组合；提交→过程展开→暂停/恢复→待确认→选择范围→完成→备忘/PDF预览；取消与一次中断恢复保留原任务输入和元信息；主题/语言/视图重挂保留草稿与阶段。核心状态校验须阻止跳过确认、非法操作与伪造恢复状态。


### v0.15 最终接口与验收

`Card({id,title,eyebrow,description,meta,status,statusLabel,selected,actions})` 与 `ItemList({id,label,items,selected,emptyText})` 从 compound-components.mjs 导出，样式由 compound-components.css 提供。两者返回语义 HTML，所有展示文本转义，id 与状态受校验；状态标识与可本地化的 statusLabel 分开。卡片用于附件、任务摘要、产物，列表用于过程记录。调用者持有数据和事件监听；操作通过 data-card-action/data-card-id、条目通过 data-item-id 识别。当前没有拖拽、多选、虚拟列表或插槽框架。

`mountAgentTaskPage(host,{tr,language,state})` 返回 `{getState,destroy}`；输入、附件元信息、过程阶段、确认选择、重试次数和产物选择可跨语言/主题/视图重挂保留。刷新会重置本机示例，未提供持久化。`createAgentTaskState/validateAgentTaskState/reduceAgentTask` 明确约束转换，恢复状态必须与重放的事件记录相符，不能通过伪造 complete 跳过确认。原生附件选择只读取元信息；最多8个、每个50MB，整个批次校验后再更新。模拟中断允许一次重试，保留原任务。备忘为原创固定文本，PDF为既有中文样稿，不是新生成文件。

浏览器实际回放：空输入阻止提交；中英文两份附件随任务保留；提交后两次推进进入待确认，未选择时继续按钮禁用；选定边界后继续；模拟中断→重试→暂停时移除推进按钮→恢复→完成；备忘/PDF预览切换；语言切换和投资研究视图往返后保留任务与当前PDF预览。最终版本再次回放输入→双附件→确认→产物。截图 study/agent-confirm-v15.png、study/agent-task-v15.png。原生本机文件选择未在浏览器实选，元信息与批次限制用程序检查；取消路径有状态检查。未做移动端或读屏全矩阵，不代表用户审美验收。

最终 `node --test docs/design/dashboard-demos/editorial/*.test.mjs`：91项通过（包括6项卡片/列表检查、7项任务状态检查）；检查覆盖非法跳步、确认门槛、一次重试、取消和伪造恢复状态。模型调用0次，没有真实Agent运行或上传。

| ID | 当前路线 | 依赖 | 最新状态 |
|---|---|---|---|
| ES04–ES06.4 | 基础组件、阅读交互与八类页面 | 原有基线 | 已交付原型 |
| ES07.1 | 独立卡片/列表并用于任务页 | 现有主题与状态 | 已完成 |
| ES07.2 | 输入、附件、过程、待确认、产物完整任务页 | ES07.1 | 已完成；当前位置 v0.15 |
| ES06.5 | 来源摘录用于普通研究引用列 | source-excerpt | 下一项 |
| ES05 | 真实产品与执行接入 | 明确后端范围 | 未实施 |

旧队列状态保留为历史，以本表为当前状态。下一具体动作是把现有来源摘录组件接入普通研究引用列，保持来源和页面选择关联。


## 2026-10-10 · ES06.5 来源引用组件与两处实页接入（v0.16）

问题：研究列表与Agent产物缺少就地核对原文的入口。输入为调用方显式提供的摘录、来源身份、定位和链接；不检索、不从附件推断出处。研究列表新增引用列，Agent备忘三个规则及PDF产物页脚入口均接入同一组件。保持文字引用、细下划线与衬线摘录，不添加整页跳转或统一大盒子。

接口：`Citation({id,label})` 返回转义后的引用按钮；`mountCitations(host,{sources,labels})` 返回 `{destroy}`。sources数组包含 id/title/text/caption/kind，可选 locator/href；kind限定local-document/authored-specimen/external-document。labels.openSource和labels.kinds可本地化，原文保持原语言。未知引用、重复ID、非法链接明确拒绝；调用方负责真实性和版本。复用已有createSourceExcerpt；点击展开/再次点击关闭、单浮窗、Esc/外部点击关闭，关闭按钮与Esc回到触发按钮；滚动/窗口改变关闭，重挂销毁监听。固定定位与视口限制避开表格裁切，长摘录独立滚动。没有自动摘要、检索或缺口补齐。

DataTable新增显式slot:true文本单元格槽，生成列key与转义后的行id，不接受任意HTML；引用组件由页面按记录身份插入，排序/筛选不按行号绑定。workspace固定使用v0.16表格模块地址：首次浏览器复核加载旧依赖，没有引用槽；显式更新依赖版本后重放恢复，旧DataTable调用保持兼容。引用Esc与研究详情Esc隔离，不误关记录。

来源范围：research-source-notes.md为六条虚构研究记录的原创编辑说明原件v1，只解释阅读意图，不支持模拟数值/日期。Agent引用WORKSPACE_DESIGN.md的字体角色以及PDF_LAYOUT_RULES.md的表格、页脚规则；备忘三项表述已按这些实际摘录对齐，引用不是上传附件核验。九条摘录均程序逐字确认存在于各自原件，定位按文件和段落/规则显示。既有PDF没有改写为带可点击脚注的新文件，仅其网页预览增加引用入口。

实页检查：北线引用显示原文与north定位；共同地带选中后Esc关摘录，详情仍在（0浮窗/1详情）；Agent完成后表格规则显示对应原文，切换页脚引用仍只有1浮窗；切英文销毁旧浮窗并保留任务，原文仍中文；PDF预览页脚引用可打开。截图study/research-citation-v16.png、study/agent-citation-v16.png。没有做全视口/读屏矩阵，未打开每个外部网站，也未声称生产来源检索。

最终98项程序检查通过；新增检查覆盖引用转义、模型与URL约束、来源原文一致性以及表格槽身份与非法组合。模型调用0次。源码模块citation-components.mjs/css、来源citation-sources.mjs。ES06.5完成；已有任务页保持本机状态机边界。

| ID | 当前路线 | 依赖 | 状态 |
|---|---|---|---|
| ES04–ES06.4 | 基础组件、阅读交互、不同职能页面 | 已有基线 | 已交付原型 |
| ES07.1–2 | 卡片/列表与完整Agent任务页 | 原有组件 | 已完成 |
| ES06.5 | 研究列表与Agent产物来源引用 | source-excerpt/任务页 | 已完成；当前位置v0.16 |
| ES07.3 | 多引用集中来源面板与往返定位 | ES06.5 | 下一建议，未实施 |
| ES04.3 | 长文PDF/跨页表格 | PDF引擎 | 暂缓 |
| ES05 | 真实执行与生产接入 | 明确后端范围 | 未实施 |


## 2026-10-10 · ES07.3 集中来源与阅读往返（v0.17）

当前行动：研究列表和Agent产物共用集中来源面板，引用精确定位提供的原文摘录，返回保留正文位置与触发焦点。输入沿用显式来源数组，不新增检索或虚构文档。引用采用已有Citation按钮，查看入口改用mountSourcePanel；既有就地摘录组件保留独立接口。研究列表面板只包含当前筛选范围，Agent面板包含该示例产物三条设计契约；“全部来源”入口显式携带当前来源id，不用全局默认来源。

布局：右侧原生dialog集中阅读，来源目录和原文区域独立滚动，原文按id高亮定位；页首与返回操作固定，细分隔线、衬线阅读与无衬线操作沿用语义主题。面板显示的是提供的摘录，不表示已加载全文。关闭返回第一触发点，连续换来源不能覆盖初始阅读位置；销毁/切换页面清理面板与事件，不将焦点移到已卸载节点。


接口：`mountSourcePanel(host,{sources,labels,scrollContainer})` 返回 `{open(id,opener),close,destroy}`；labels包含title/returnToReading/openSource/scopeNote/kinds，来源模型复用validateCitationSources。两个入口data-citation/data-source-panel都必须提供精确id。原生dialog负责焦点限制，回退点包含触发元素和滚动容器双轴位置，换来源不覆盖。返回/取消后两次恢复滚动，焦点以preventScroll恢复；destroy保留当前滚动并移除事件/恢复原ARIA。

实页检查：研究列表点击共同地带定位study-common，换至atlas后返回，滚动210→210、焦点study-common、0个打开面板。Agent引用表格定位rule-table，换页脚后Esc返回，滚动1282.5→1282.5、焦点rule-table、0面板。截图study/research-source-panel-v17.png、study/agent-source-panel-v17.png。102项程序检查通过，包括精确身份/重复来源/无默认替代/双轴返回坐标。未做所有浏览器或读屏矩阵；原文仍是调用方提供的摘录，不是全文加载。

ES07.3已交付原型；原始来源检索与生产接入ES05未实施，长文PDF ES04.3仍暂缓。下一建议ES07.4：为来源增加分组与页内检索（未实施，不计入本轮）。用户本轮额外指出iDA扩展设置的布局和主题，作为独立具体修复处理，不改这些来源规则。

## 2026-10-10 · ES08.1 研究报告阅读交互调研

用户确认当前交互后，将重点转为直观、美观、简洁、易懂的研究报告。已核对Anthropic研究概述与完整论文、Distill脚注、OWID图表/数据表与口径入口；实际操作与截图、观察边界、候选组件及最新队列见[REPORT_INTERACTIONS.md](REPORT_INTERACTIONS.md)。本轮是调研交付，未新增报告页面。下一具体项ES08.2：报告摘要、章节导航和图表/数据切换接入既有引用链。ES07.4来源分组保留后续；ES04.3暂缓、ES05未实施。


## 2026-10-10 · ES08.2 / ES08.3 完整报告与共用设计原则 v0.18

[完整研究报告](research-report.html)由摘要三条→连续三章→图表/数据→集中来源构成。独立页面复用工作台 Header、字体和语义主题；工作台与组件样册已加入口，不改变原有九个视图。原创设计研究样稿、5条演示数字和真实项目规则摘录分别标注，没有财务结论或检索能力。

mountReportReader提供双语、原生章节hash导航、滚动目录标识、固定高度的图表/数据、getState与destroy生命周期，集中来源沿用mountSourcePanel。当前内容为明确样稿，不是任意报告Schema；下一步从实际报告需求提取内容参数，不能把这个组合页称为完整生产报告引擎。

目标浏览器验证：摘要第二项定位章节顶139.914px；图表/数据切换区域280→280px、文档位置1406.5→1406.5；引用2定位表格原文，面板切到来源3后Esc关闭，1889.5→1889.5并恢复引用2焦点；切英文保留1889.5与数据模式，Mineral切换保留数据模式。原生历史返回恢复既有阅读位置，目录按实际可见章节更新。目录判定原先120px与锚点140px不一致，统一读取--report-anchor-offset后，重复第二章链接正确高亮第二章。移除pagehide时销毁正文，避免浏览器缓存返回空页。105项组件检查通过；没有全视口矩阵或生产检查。截图：[报告正文](study/report-reader-page.png)。

[编辑设计原则 v0.1](EDITORIAL_DESIGN_PRINCIPLES.md)给出ED01–08、主题/字体/间距/容器基线、不同任务页适配与五步设计模板，链接进Uteki界面style guide。明确原站观察、项目规则与设计建议；色彩自由定制，页面布局随任务变化，不追认成Anthropic官方规范。

### 最新路线（此前段落保留为阶段历史）

| ID | 名称 | 依赖 | 状态 |
|---|---|---|---|
| ES04–ES06.4 | 基础组件、双语PDF、媒体与职能页 | 既有基线 | 已有原型；长文PDF除外 |
| ES07.1–2 | 卡片、列表与Agent任务 | 基础组件 | 已有原型 |
| ES06.5 / ES07.3 | 引用、集中来源与阅读返回 | 列表/任务页 | 已有原型 |
| ES08.1 | 报告交互调研 | 公开原站 | 已完成 |
| ES08.2 | 完整报告阅读链 | ES08.1 / ES07.3 | 本轮完成样稿；当前位置 |
| ES08.3 | 共用编辑原则 | 已认可方向 / 原站观察 | 本轮v0.1；持续修订 |
| ES08.4 | 报告列表预览与阅读往返 | ES08.2 / ES08.3 | 下一具体项，未实施 |
| ES07.4 | 来源分组与检索 | ES07.3 | 后续，未实施 |
| ES04.3 | 长文PDF跨页 | PDF引擎 | 暂缓 |
| ES05 | 真实报告/执行与生产接入 | 明确后端范围 | 未实施 |
