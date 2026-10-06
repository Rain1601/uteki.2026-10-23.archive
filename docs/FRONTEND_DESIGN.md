# Logo motion studio · 2026-09-24

## 2026-10-06：年报图表按阅读问题优化

用户要求只有明确指定时才使用 frontend-design；本轮不加载或应用。先以“现金为什么增加”和“谁为哪种服务付费”定义两个可观察问题，沿用 uteki-interface 的可追溯、原生阅读与显式点击约定。用 visualize 交付现金图的会话内对照，用独立 Mermaid 业务图控制阅读顺序，不重新设计项目页面。

交付见 [台积电年报图表优化第一轮](research_samples/TSMC_2025_CHART_REVIEW_v2.md)。现金对照采用冻结官网英文年报 §6.1.3 的相同六项合并数据，原文整数换算为十亿新台币展示。新版中间条从上一累计余额开始；原图从零起算作为对照保留。提供中英文、精确值和官方页码；累计端点不冒充实际时点余额，投资／筹资现金流不改名为资本开支／分红。业务图从客户、服务、交付展开，现金图独立呈现；原六图与冻结源文件保持不变。

本轮是呈现样本，尚未接入正式后台或更改 Data Agent Skill。检查覆盖源金额、现金勾稽、浮动条端点与脚本语法；不以这些检查替代浏览器或用户视觉验收。用户读图反馈后再收敛可复用的材料精编规则。

## 2026-10-05：按公司与材料组织真实数据查看

用户反馈现有“产物与覆盖 / 原文与解析”无法回答一家公司拿到了哪些文件、每个文件加工出了什么、如何核对以及 Agent 做过什么。本轮可见行为以“公司 → 材料 → 加工产物 → 处理记录”为主线：未选择材料时列出实际登记材料；明确选择后聚合原件、章节与表格、逐次财务提取、尚未生成的财报精编及处理入口。历史候选版本分别展示，不相加为独立事实覆盖。

布局计划：复用现有公司侧栏、原生阅读滚动、表格、折叠详情和来源链接；保留当前字体及 `--ink / --muted / --line2 / --rail`，焦点色继续用 `#355d9f`。主层用报告类型、报告期末和公开日期命名，技术 ID、哈希、原始 JSON 与解析诊断折叠。资料原文、机器索引、数据库事实、模型精编采用不同展示方式，缺失产物明确标示。本轮不做风格重构，不改公司名单或数据采纳规则。

运行详情新增可读的“任务与输入 → 实际模型与 Prompt / Skill → 已保存输出 → 未解决事项”，可展开查看实际输入表格及提示词文本。只有已保存证据才能展示状态；未保存检查不能显示为零问题，提取子步骤不冒充完整主 Agent trace。示例工作台侧栏增加通往真实材料与提取记录的本地入口，任务区域仍明确为 Demo。

同时修复历史短链接：已明确指定 dataset 和 run、但漏写 source 时，只从该次唯一且绑定校验通过的运行解析材料；未知、冲突、跨公司或空值继续拒绝。未选择运行时不默认第一份或最新材料。原用户 AMD 短链接已在重启后返回 HTTP 200，内容含实际现金数据与准确来源。

检查：Demo 原有 27 项交互检查通过；本轮整合后的 48 项定向检查通过，涵盖双公司来源隔离、重复版本不合计、明确材料选择、失败产物缺失、实际提示词与文本转义。真实 AMD、台积电的材料列表、材料详情、原文目录、提取过程和 AMD 历史短链接均返回 HTTP 200；错误的跨公司运行链接返回 400。源数据只读、候选采纳状态不变。按项目约定未进行浏览器视觉验收。

## 2026-10-05：主 Data Agent 真实提取结果登记

沿用既有只读财务矩阵和运行页，登记 `amd-fy2023-main-agent-v2` 的真实提取子运行及独立审核。10 条草稿、3 条规范化 DB 行、12 项程序诊断按原有字段展示；审核区说明单元格数值拼接、指标映射与历史实现归档的限制。公司范围和数据基线不变，候选未采纳；完整主 Agent Trace 另见[本轮运行说明](../experiments/architecture_baseline/2026-10-04-amd-tsmc-annual-v1/README.md)。

两页实际 HTTP 返回 200：矩阵包含本轮数值和跨单元格问题；运行页包含冻结的应用 Skill、方法及实际 System Prompt。第一次文本检查中的大小写和内部文件名预期不符合页面标题，已依据冻结文本修正检查，页面 HTML hash 未变。回执为 `ui-main-agent-v2-http-receipt.json` 和 `ui-main-agent-v2-http-receipt-v2.json`。本轮只登记真实产物，没有样式改动、截图或浏览器视觉验收。

## 2026-10-04：后台独立瑞士排版预览

用户选择保留现版、另建同一组任务与数据的独立预览。应用 frontend-design 与 uteki-interface 的交互基线；紧凑视觉计划为清晰网格、无衬线文字、克制分隔线和单一强调色，优先展示任务身份、输出与证据。入口为 [agent-workbench-swiss-v1](design/agent-workbench-swiss-v1/README.md)，原后台与前台保持原状，尚未将这次风格探索写入通用界面规则。

默认「工程阅读型」使用 22px 标题、15px 正文、24px 内容边距、240px 任务栏与 400px 产物栏，灰白底和蓝色强调；「编辑排版型」保留同一结构，使用 28px 标题、16px 正文、较窄阅读列与砖红强调。仅切换根节点的排版属性，复用现版 app / model / renderer / DEMO，不重建工作区。中英工具条、Agent 列表、悬停及键盘设置入口、证据追踪和原生滚动保留；窄窗口以横向滚动保留各栏，为待评审方案。

可观察验收：GOOGL 评审页写草稿 → 打开对应产物 → 切换两种排版 → 同一任务、运行、草稿和产物保持 → 切换中英，预览选项同步。沿用现版演示边界：全部为虚构样本，追加要求仅创建待执行尝试，当前页面记录刷新清空；未调用模型、修改真实数据或连接后端。

验证：现版状态与渲染检查加 4 项预览检查，共 **31 项通过**，覆盖样式切换不重建工作区、草稿与产物保持、中英同步、选项范围和本地依赖；脚本语法通过。入口、样式、共享模块和 Logo 共 9 个本地 HTTP 请求返回 200；首次检查受工具网络限制，获准后仅对本机服务完成只读验证。未打开浏览器做视觉验收或截图，测试不代表字体、窄窗口或阅读密度已获用户认可。入口版本 `20261004-swiss1`。

下一步：用户对照两种排版后再收敛密度与字体；真实 Agent 执行闭环仍为独立主线。

## 2026-10-04：买卖贴合收益曲线，持仓按日期查看

用户明确买卖应在线上、报告事件在下方；双击后的持仓变化需要更清楚的时间表达。沿用 uteki-interface 与已选明快色卡，不使用 frontend-design。紧凑方案：收益图保留多 Agent 对比；B/S + 公司 icon 贴在所选 Agent 曲线上，R 留在下方；展开持仓后用日期节点、公司占比横条、较前次记录变化和小趋势图呈现。

最小验收例子：North 年初至今 → 点击曲线上的 NVIDIA 买入 → 浮层显示该次准确日期、页面不移动 → 双击 Field → 选择 2026-06-30 → 显示当时公司与现金占比及相较 2026-05-31 的百分点变化 → 方向键到 7 月 → 返回同一 Field 组合。

新增共用 performance-geometry 坐标计算；曲线与交易使用同一数据范围，事件日在所绘制折线上定位，不推导实际日净值或成交价格。报告继续按日 / 周 / 月聚合；交易仅按日期距离做显示聚合，组锚点为组内最早真实事件日；两类不混合。浮层保留精确事件身份，尺寸变化仍可定位原事件。筛选和单击 Agent 保留原曲线节点，确保双击可用。

配置时间轴手动选择，不由 hover 切换。上方日期节点是逐条记录选择器，下方趋势按实际时间间距绘制，所有公司共用纵轴。显式零占比与现金保留；首个区间记录不伪造前序比较。公司色与饼图一致，变化使用百分点，不表示涨跌幅。当前持仓仍为期末快照，浏览历史不覆盖当前组合。既有收益、事件、配置和研究样本均未修改。

验证：performance-geometry、investment-event-view、allocation-history-view、institution-view、interaction 五个测试文件共 **104 项通过**。覆盖跨 Agent / 区间、空数据、事件保留与分轨、精确日期定位、窄宽度聚合、浮层、日期键盘及当前组合状态保持。按本轮“可以看一下”与实际定位需求进行了定点浏览器检查：修复覆盖层误用整条事件区域高度的问题后，当前窗口 10 个交易圆点与绘制折线偏差小于 0.02px；打开浮层前后曲线、组合区域与 scrollTop 均不变。实际双击 Field、日期点击 / ArrowRight、返回 Field 均成功，独立检查页无错误日志。没有进行多尺寸 / 多语言 / 多主题视觉验收。

入口版本 `20261004-investment-timeline2`。截图：[曲线交易](design/company-workspace-v2/curve-trades-preview.jpg)、[持仓时间轴](design/company-workspace-v2/allocation-timeline-preview.jpg)。本节替代下方旧版“B/S/R 都在底部”和“100% 堆叠阶梯历史图”的当前交互；旧记录保留作迭代历史。下一步先评审日期选择和占比变化的可读性，再决定是否另行设计个股涨幅。

## 2026-10-04：研究覆盖的当前、历史与未来关注

用户要求移除无意义的公司占位，将研究覆盖定义为该 Manager 的当前关注、历史关注和未来关注。沿用 uteki-interface 及已有工作台，不使用 frontend-design。三个阶段在桌面并排，卡片展示公司 icon、关注原因、阶段对应时间和已有报告数；历史报告可继续阅读，未来计划无报告时不显示空入口。窄窗口保留原生滚动。最小验收例子：North 覆盖只显示明确登记的 Alphabet / Microsoft / Arista，分别进入当前 / 历史 / 未来组；其余目录公司不被自动补入。

新增独立、冻结、版本化的前台关注样本 `uteki-manager-focus-ui-2026-09-30 / v1`。原目录只有 published / researching，不能证明关注阶段，故没有从报告、持仓或旧 coverage 推算阶段。两位 Manager 各三条明确模拟记录；来源必须显式传入，空清单与来源未连接区分，校验实体、唯一关系、阶段和截至日。原报告、公司名单、持仓与交易样本保持原状。

同步统一导航覆盖总数、标题当前关注数和上下文计数；报告筛选只列有该 Manager 报告的公司，概览去掉旧 coverage 生成的无报告占位研究事项。研究表继续呈现已有问题与产物，不把未来计划伪装成正在运行的任务。分组变更只涉及本地演示，未接入真实关注或执行系统。

验证：四个受影响测试文件共 94 项通过；最后文案与计数核对后，77 项展示与交互检查再次通过。覆盖独立合成目录、跨 Manager 隔离、未关注公司不自动加入、无报告的明确关注、缺来源与空清单、阶段日期、已有报告筛选、历史报告返回及页面计数。独立只读复核确认实际渲染的公司与清单一致。未执行浏览器视觉检查。入口版本 `20261004-focus-stages1`。

下一步：先评审三组关注的表达，再细化未来关注卡片需要呈现哪些计划信息。

## 2026-10-04：Manager 概览、研究覆盖与操作历史

本轮按用户反馈调整前台 Manager 右侧，保留三层工作台和公司名单，继续沿用 uteki-interface，不使用 frontend-design。可观察示例：North 概览看到收益区间、组合市值、持仓与现金配置，下方每页 6 条公司研究事项；打开研究覆盖后选 Alphabet 的「研究产出」，进入已按 Alphabet 筛选的 North 报告目录，阅读后返回保留筛选、焦点和位置。

视觉计划采用紧凑指标行、含现金的细比例条和有明确列宽的表格。研究覆盖用桌面三列两行公司卡片，报告按公司筛选，操作历史按全部 / 买入 / 卖出 / 报告筛选且每页 8 条；旧 holdings 深链接兼容进入操作历史。机构首页的 Agent 详情入口改为概览。配色沿用用户确认的明快分类色，现金中性灰，明暗主题分别映射。窄屏保留原生滚动，不用滚轮分页；一屏覆盖是设计目标，尚未做本轮浏览器视觉验收。

研究列表只投影已有未决问题、已发布报告和没有报告的覆盖关系，不伪装成实时执行任务；已发布但待复核的报告可同时出现在已发布与待跟进筛选。收益、持仓来自明确机构样本；买卖记录来自独立事件样本，不从持仓或收益反推。原始研究与组合样本保持不变；没有数据来源时明确展示未接入，不将未连接伪装成空历史。报告持续保留公司、作者、独立报告 ID、具体版本和已有正文。

验证：模型、Manager 数据投影与渲染、真实控制器的最小 DOM 模拟、受影响机构展示共 5 个测试文件 123 项通过。覆盖两个 Manager 的筛选分页隔离、全部事件不重不漏、报告历史与范围、覆盖到公司报告、目录返回、延迟滚动恢复、边界分页焦点以及导航收展时的阅读锚点。数据投影另含独立合成样本的范围校验。本地预览与 6 个相关资源 HTTP 200；首次本地检查被工具网络限制拦截，授权后的本机只读检查通过。未运行模型、修改后台或部署，未执行浏览器视觉检查。

入口版本 `20261004-manager-workspace1`。下一步先由用户评审概览密度，再看覆盖页的公司排列；真实任务和账户接入仍独立安排。

## 2026-10-04：后台 Agent 列表与只读配置面板

用户要求 Agent 平铺为列表，悬停显示设置图标以查看配置。仅修改 `docs/design/agent-workbench-v1/` 的这一入口：Data / Analysis 两行常驻，点击名称切换任务列表；齿轮单独占位，悬停、键盘聚焦或配置展开时显示，触屏常显。沿用已有灰白、蓝色强调、系统字体及原生滚动规则，不变动前台机构界面。可观察验收：正在评审 Data 任务时点 Analysis 齿轮，右侧显示 Analysis 配置，原任务、运行、草稿和滚动位置保持；关闭或 Escape 返回此前产物。

配置面板显示 Agent ID、职责、数据集来源、静态回放模式、该 Agent 已登记演示运行的模型与配置版本。System Prompt、Skills、工具权限尚未接入，明确标为未登记或未连接；不读取本机生产配置、凭证或修改运行设置。点击当前 Agent 名称保持正在阅读的页签。中英一致，打开配置与选中 Agent 是两个独立动作。

27 项本 Demo 状态、渲染与最小 DOM 事件检查通过，覆盖配置归属、只读操作不触发执行、列表选择、未知 Agent 拒绝、草稿和产物上下文保留；JS 语法及 CSS 静态检查通过。未执行浏览器视觉验收。下一步由用户查看列表密度及配置面板的信息是否够用。

## 2026-10-04：确认明快配色

用户确认选择「明快」。将共享默认色卡由经典改为明快，推荐标记同步迁移；饼图、持仓色标及历史配置图共用该色卡。保留手动色卡选项与已有本机明确选择，不改持仓或图表交互。沿用 uteki-interface；仅修改显示默认值和现有检查期望；5 项相关配色检查通过，不新增测试或执行浏览器视觉检查。

## 2026-10-04：图内事件浮层与双击 Agent 的持仓演变小样

可观察目标：点击曲线底部的公司事件标记，详情围绕该时间点浮出，曲线和组合不变宽、不换位；双击 North / Field，展开同一 Agent 在不同日期的公司与现金配置。沿用 uteki-interface 与现有组件，不使用 frontend-design；公司名单、研究内容及组合历史版本保留。

事件浮层优先位于标记上方，受正文可见区域限制，边缘自动避让；用竖向参考线连接时间轴。聚合组一次显示一条事件，前后按钮手动翻看，不自动轮播。报告保持精确作者、公司、报告 ID 和版本。点击外部 / 再点标记 / Escape 关闭；切 Agent 或期间关闭旧事件。浮层不占用研究侧栏，打开前后正文宽度和阅读位置不变。

用户新提出双击展开的探索方向，本轮以“持仓占比历史”作为可体验默认小样，尚不表示用户最终确认。单击立即选择 Agent，保留图例、曲线与缩略卡节点，避免第一击重绘目标导致原生双击丢失；重复单击已选 Agent 不重绘。双击或可见“展开持仓”按钮进入主区域的历史图；上方 Agent、期间仍可切换。展开时暂时隐藏当前组合，返回恢复它及原阅读位置。悬停日期区间 / 点击日期按钮只改变历史详情，不修改当前持仓。滚轮继续用于阅读。

图形为 100% 堆叠阶梯图，公司颜色与饼图保持一致，现金继承中性灰。新增独立版本化模拟配置 fixture：两 Agent 各 16 点，所有点公司 + 现金合计 100%，显式零保留，末日权重与当前演示持仓核对。历史逐点编写，不从买卖事件、收益或期末权重反推；未提供的时间边界报缺口。阶梯仅连接采样快照，不代表连续观测或准确成交时点。个股涨幅、收益贡献及持有区间仍未实现；这三者需要各自的价格与交易口径。

验证：9 个相关测试文件共 168 项通过，后续浮层紧凑展示及测量修复又运行 13 项受影响检查通过。覆盖数据范围、独立合成机构 / 公司 / 期间、100% 校验、日期命中与阶梯语义、无隐式回退、原生双击目标保持、展开 / 返回、事件聚合与原报告链。为验证原生双击及浮层几何进行了正常桌面窗口的定点浏览器检查：未选中的 Field 双击可打开历史、日期点击和返回有效、事件翻页与 Escape 有效，事件浮层打开前后图表位置与 scrollTop 相同。发现装饰箭头影响 scrollHeight 导致错误选择下方，已改测卡片矩形，确认能在上方显示。未做跨设备、多主题、多语言的全面视觉评审；美感仍由用户评审。

入口版本 `20261004-holdings-history1`。截图见 [持仓演变](design/company-workspace-v2/allocation-history-preview.png) 与 [事件浮层](design/company-workspace-v2/chart-popover-preview.png)。下一步先评审占比随时间变化是否容易理解，再确定是否增加单独的个股涨幅视图。

## 2026-10-04：鲜明饼图色卡与投资事件轴

用户希望配色更鲜艳、正、自然，明确无需与雨滴雾蓝主题一致；同时要求把收益时间轴连接到买入、卖出及报告事件。沿用 uteki-interface，继续不使用 frontend-design。紧凑视觉计划：保留已确认的曲线 / Agent 缩略页 / 持仓布局，在 Portfolio 底部放四个可点击小饼图色卡，在收益图下增加一条日期对齐的事件轨道，点击后复用右侧上下文。

配色为经典（推荐）、明快、宝石、活力；六个公司分类色与中性现金色分离，明暗主题各自取色。选择仅更新颜色变量，不重建主图、持仓或报告节点；本机显示偏好记住色卡，写入失败只保留会话内选择并给出反馈。色卡小图使用同一 Agent 的比例；跨 Agent 同公司沿用原目录颜色槽位，颜色本身不表示收益或风险。当前六色设计范围未宣称支持任意数量公司且无重复。

可观察例子：North / 近 1 月 → 事件轴显示公司 Logo 与 B / S / R 或聚合数量 → 筛选报告 → 点击一组 → 右栏按准确日期列出各版本，点击打开 North 的相应报告 → 返回原组合；切 Field 后事件跟随其身份，旧事件详情关闭。日 / UTC 周一 / 月分组、自动粒度和视图碰撞合并分开处理，所有底层事件均保留。聚合位置表示日期范围中点，不假装是一笔精确交易；缩窄时重新聚合，已打开明细保留原组快照。收益区间不改变当前持仓日期。

参考 [TradingView Execution marks](https://www.tradingview.com/support/solutions/43000763371-execution-marks/) 的密集执行标记合并与 [Marks](https://www.tradingview.com/charting-library-docs/latest/ui_elements/Marks/) 的时间轴图标和展开说明。Uteki 实现是自身交互设计，不是 TradingView SDK 集成；买入蓝色、卖出橙色、报告紫色为独立类型语义，不借用饼图公司分类色。

数据新增冻结 `uteki-investment-events-ui-2026-09-30 / v1`：41 条独立模拟事件，North 22 条、Field 19 条，含核对作者、公司、版本及发布日期的 8 条报告事件。买卖不从当前持仓或收益反推，不作为对账账本；原组合 v1/v2、公司名单及研究内容保留，无真实账户、模型调用或交易执行。最新授权允许在前台回看模拟买卖，替代旧版完全不展示交易记录的约定。

验证：135 项聚焦检查通过，覆盖模型范围、色卡同步及本机偏好、跨 Agent / 报告归属、日周月边界、事件筛选、聚合不丢失或重复、报告历史版本、控制器返回和宽度变化后的选中映射。视图检查遍历 1000 / 600 / 250 数值宽度的 288 种组合，计算相邻标记至少 64px；这是渲染与状态检查，不是浏览器布局验收。独立审查发现并修复右栏展开后标记重新聚合导致选中高亮消失的问题，按原明细事件 ID 映射当前分组。语法与空白检查通过；页面及 6 个相关资源本地 HTTP 返回 200。本轮未打开浏览器或截图，页面由用户选择配色并评审事件密度。

下一步：用户先比较经典 / 宝石，并体验近 1 月的事件标记、报告版本入口与返回；再决定是否需要进一步调整事件密度。入口版本 `20261004-palettes1`。

## 2026-10-03：互动配置图、紧凑标题与作者报告入口

本轮沿用已经认可的 Agent 曲线和手动组合缩略页，仅细化三处。采用 uteki-interface 基线，继续按用户要求不使用 frontend-design。输入仍为原 v2 具名模拟组合与既有公司研究，未修改数据或后台能力。

可观察例子：点击 North 饼图的 Alphabet 色块 → 中心显示 30.0%、Alphabet，下方 USD 180,000，列表同项强调 → 悬停其他色块临时预览，移开恢复 Alphabet → 点击列表中的 Alphabet → 打开 North 的 alpha-north-main / v2 → 返回投资总览，保留 Agent、区间、配置选择和阅读位置。

图形由独立填充圆环扇区构成，每块拥有自己的命中区域，避免完整描边圆环互相截获事件。图形使用可访问的分组与按钮语义；Enter / Space 和点击等价。列表行与色块共享临时预览，点击保留状态；点击与预览均原位更新图形、文字和列表，不重建节点。现金同样可查看，零权重不制造可见色块。动效仅轻微强调与淡化，响应减少动效。

新增作者公司报告解析器，校验 Manager、公司、报告和 currentVersion。唯一主报告优先；否则仅在作者对应报告只有一份时直接进入；多个候选需手动选择，无报告时名称旁标“暂无该 Agent 报告”。样本中 North 对 Alphabet、Microsoft 及 Field 对 Alphabet 有入口，其余保持缺口；不会借用另一位 Manager 的报告。公司全局列表与既有研究内容不变。

标题区由 64px 压到 44px；机构名称、可点击的模拟标记和截止日期 / 币种合并在一行。移除正文顶部重复说明行与面包屑里的重复机构名，详细样本信息仍在上下文。报告来源为机构总览时，返回文字明确为“返回投资总览”。版本入口为 `20261003-portfolio-detail1`。

验证：101 项检查通过（模型 29、机构模型 12、机构渲染 6、页面交互 54）。覆盖独立合成公司的报告作者选择、缺失与歧义、固定版本、悬停与选中分离、移开与失焦恢复、图形/列表一致、原位更新、键盘及重复取消、报告往返和现有研究边界。为核对新增 SVG 命中区域做正常桌面浏览器定点验证：实际点击色块与 Enter 均选中 Alphabet，金额与列表同步；点击公司进入 North 的准确报告，返回保留选择。未进行全主题或跨设备视觉验收。截图：[互动配置图](design/company-workspace-v2/portfolio-detail-preview.jpg)。

下一步先由用户沿“组合 → 该作者报告 → 返回组合”实际体验，再决定报告页的信息组织是否还需调整。

## 2026-10-01：Agent 曲线与手动组合缩略页

用户要求首页同时比较多个 Agent，但 Portfolio 一次只展开一个，旁边以方形缩略卡片及上下按钮手动切换，为更多组合预留入口。继续使用 uteki-interface 和现有主题，不使用 frontend-design。输入仍为明确授权的模拟设计样本，不涉及真实账户、模型或后台操作。

可观察例子：首页点击 Field 图例或缩略卡片 → 其曲线强调、标题变为 Field Portfolio，5 家公司及 15% 现金同步进入列表与饼图 → 点击 North 曲线 → 展示 North 的 4 家公司及 10% 现金。上下按钮及缩略图内方向键使用同一选择状态；没有自动轮播或滚轮切 Agent。曲线 hover 仅高亮，切换 Agent 清除前一个组合的配置选择；切收益区间保留 Agent 和配置选择，持仓日期仍为当前快照日期。

视觉计划与实现：机构页移除中间索引和单独的旗下 Agent 栏，保留全局导航，主区上方为多曲线比较，下方为 100px 缩略列和一个组合展示区。标题去掉重复雨滴，首页只保留全局品牌。图表、图例和缩略卡片的 Agent 颜色一致，同一公司在不同组合中保持同一配置颜色。组合容器桌面最小高度 360px，180ms / 4px 以内的淡入位移，响应减少动效。窄区域保留自然滚动，不隐去持仓或配置图；公司与 Manager 名单保持既有结构。

数据使用 `uteki-institution-ui-2026-09-30 / v2`，显式默认 North；保留不可变 v1。各 Agent 补充同日期、起点归一的示意历史，不修改既有期间收益及持仓。校验 Agent、期间、曲线日期、终点收益、跨期间路径一致性和持仓归属，独立三 Agent 样例验证非首项默认与另一组公司。首页不再显示一个合成机构收益；旧机构组合留在历史数据中，不从 Agent 平均推导。

验证：89 项模型、渲染和控制器检查通过（22 + 12 + 5 + 50），包含范围错误原子拒绝、曲线与图例 / 缩略图联动、手动循环切换、局部键盘、区间与持仓身份、公司和 Manager 往返及原报告 / 证据回归。按本次“帮我体验一下”的请求，在现有正常桌面窗口做定点浏览器检查：缩略卡片、下一项按钮、实际曲线点击均能切换所选组合；移除目录后发现正文落在零高网格行，已修复。1440 × 842 窗口下 North 页面内容高度与可视区域均为 734px，组合容器 360px，完整图表、持仓与页尾可见。没有进行跨设备或全主题视觉验收。

入口版本 `20261001-agent-slides1`；当前截图为 [组合缩略页预览](design/company-workspace-v2/agent-slides-preview.jpg)。下一步先由用户体验缩略选择与上下切换，再决定后续公司内多 Agent 报告的组织。

## 2026-10-01：独立 Agent 后台交互 Demo

用户希望以 ChatGPT/Codex 的 Agent 选择与任务列表为参考，先讨论再制作一版可点击后台。新增 `docs/design/agent-workbench-v1/`，不沿用旧评估页的信息结构。此次应用 frontend-design 及 uteki-interface 的交互基线，按本轮任务优先的后台需求组织页面；前台公司与报告工作区保持独立。

紧凑设计计划：固定左栏提供 Agent 与任务选择，中间用结果/过程/评审承载同一任务，右侧按需检查证据或产物；实验对照单独以表格呈现。视觉沿用系统字体、灰白底和蓝色强调，优先任务身份、版本和质量状态。各阅读区原生滚动，没有滚轮翻页；检查证据时保留主区位置。模型和配置版本在运行标题附近，详细步骤与 JSON 折叠查看。

可观察例子：GOOGL 现金流任务 → 写评审草稿 → 打开原文 → 关闭面板，草稿和阅读位置保留；切换旧运行可看到不同输出；追加要求创建待执行演示尝试，保留旧运行且没有新 Agent 回复或产物。Analysis 中关联 Data 任务，实验中的单条产物能回到对应任务和运行。任务、运行、证据以及评审标准按 ID 绑定，未知和跨范围引用拒绝处理。

输入为具名虚构数据集，包含两家公司、5 个任务、9 个产物及2道实验样本。所有界面提供中英文本；财务数字和判定为示例，不作为真实研究或模型评测。评审和追加要求分别处理，草稿与记录只保留于当前页面，刷新清空；没有模型调用、执行后端、发布或真实记录修改。

验证：23 项状态、渲染及最小 DOM 事件检查通过，脚本语法通过；入口、CSS、4 个模块与 Logo 本地 HTTP 均返回 200。静态审查了 26 个结果、过程和实验产物引用的任务/运行归属。未进行浏览器视觉验收，页面阅读体验由用户评审。说明及启动方式见 [Demo README](design/agent-workbench-v1/README.md)。下一步先评审此工作区的组织，再接入真实运行与持久化评审。

## 2026-10-01：真实 Data 产物的只读评估工作台

用户要求能看到材料具体解析成什么，并据此人工核对结果和运行过程。本轮在现有 `apps/review_workbench` 增加 `/evaluation`，沿用 uteki-interface 的单窗口、原生滚动和明确上下文规则；使用现有外框与样式变量，优先实现真实产物查看。功能结构为左侧公司/冻结数据版本，右侧材料与覆盖、原文与解析、数据与核验、运行回放四栏。未选择数据版本时只列选择，不自动选中某家公司；全局增加“数据评估”入口，不改变产品公司的研究名单。

可观察路径：选择 GOOGL 数据版本 → 数据与核验 → 找到 2024 年 operating_cash_flow → 同页查看 `125299000000 USD`、原值 `125,299`、scale `6`、原文现金流表与模型核验 → 沿块链接及上一原文块检查相邻单位/标题 → 查看当次实际工具输入和返回。MSFT 独立显示其 102 条候选记录和解析缺口，没有登记的运行保持空状态。列表每页 40 项；表格和 JSON 可原生滚动，详情锚点直接定位所选对象。

输入为显式登记且固定哈希的两个数据包、三份材料和一次历史 query/review 交接。GOOGL 有 253 条、MSFT 有 102 条候选行；当前内容核验覆盖该 GOOGL 问题的 7 条事实，回放为 25 个主角色步骤，未接入 Worker 独立步骤。材料页分别展示解析诊断及按材料/原因分组的全部处理缺口；未映射概念和图片未读取不能被“解析诊断为零”掩盖。冻结记录与 DuckDB payload、公司/来源字段一致性检查后展示，不声称所有物理列或语义已验收。

输入和输出采用转义文本，数值保持精确字符串。原始 HTML 字节在 sandbox iframe 和限制性 CSP 下展示，不加载外部脚本/图片；原文页面入口只接收登记的数据集和来源 ID。模型核验保持任务范围，候选、人工验收未记录、共享采纳未改变明确分开。此页不会运行模型、修订记录或保存人工判定；人工标错/复核、Gold 集和跨运行对比属于后续能力。

验证：23 项聚焦测试通过，覆盖两个独立合成公司的查看隔离、另一组合成冻结数据的哈希/路径和 DuckDB 一致性、精确数值、表格跨度与不可信文本转义、来源/记录绑定、未核验状态、完整缺口元数据。另完成 11 个真实视图渲染及本地 HTTP 检查，确认正常入口、错误范围拒绝、原件响应哈希和 CSP；没有模型调用或浏览器视觉验收。独立审查发现并修复 Schema 值展示错误和缺口未展示的问题。旧工作台历史 `review_excerpt.json` 第 90 段哈希不一致仍由预检查报告，未更改历史文件，新评估材料通过独立完整性检查。

下一步先用真实的一条现金流记录人工走通核验，再定义并加入可持久化的错误标注与复核记录；页面信息密度和实际阅读体验由用户评审。

## 2026-10-01：机构投资总览与前台边界

用户纠正首页主体：应为 Uteki 投资机构，展示机构收益、Portfolio 持仓、含现金的配置图，以及旗下 Agent 的收益和研究入口；后台另行设计，本窗口只做前台。本轮优先完成机构总览，不展开公司报告卡片、分页或多 Agent 切换设计。继续沿用已确认的三层工作台和 uteki-interface 基线，不使用 frontend-design。

用户明确授权模拟数据后，新增独立具名样本 `uteki-institution-ui-2026-09-30 / v1`，持仓截止 2026-09-30、币种 USD。机构 $1m、六家公司与 10% 现金；Agent 各自有独立模拟组合，非机构组合的子账户定义。机构曲线、基准和各收益区间从一致的示意路径重定基准，曲线横轴按真实日期距离排布。持仓数量与金额、权重含现金均校验；公司研究覆盖与组合持仓不混同。真实产品中的机构 / Agent 资金归属和收益计算口径仍需单独确认，不能把当前设计样本当作业务契约。

首页为 `#/institution/uteki?view=overview`，空 URL 通过明确演示配置进入；未知机构或混合公司 / 报告身份拒绝，原公司与 Manager 深链接保持。最左新增机构总览入口；中间为总览目录和 Agent 快捷入口；右侧上方为机构收益与模拟基准曲线，下方并列 Portfolio 列表 / 配置图以及 Agent 概况。近一月、年初至今、近一年切换同步更新机构、基准、曲线与 Agent 收益；选择持仓比例强调饼图对应部分，重复选择取消。所有指标明确标注模拟、非实盘、期间、日期和币种。

点击公司进入既有公司研究，点击 Agent 进入既有详情。为使路径一致，详情中接入相同设计样本的收益与持仓，并列出该 Agent 报告关联的待验证问题。组合样本仅在渲染器通过具名机构配置显式传入，原 `getManager()` 真实账户缺口仍保留；不借用报告证明持仓。前台移除操作记录入口，兼容旧地址时仅展示研究发布历史，不展示交易操作。阅读、证据与版本范围不变。

可观察路径：机构首页切“近 1 月” → 机构及 Agent 展示同期间收益 → 点选某持仓比例突出其配置 → 点击公司名称阅读研究 → 回机构总览保留区间与选择 → 进入 Agent 详情查看其标注清晰的模拟组合和研究。资源版本 `20261001-institution1`。

验证：84 项检查通过（原模型 22、机构模型 9、展示数据 5、页面交互 48），覆盖机构路由及无错误回退、模拟组合金额与比例、所有区间曲线与收益一致、按真实日期间隔绘图、持仓与现金选择、三种入口往返、证据与版本隔离、原生阅读位置及导航重排补偿。另核对本地 HTTP 返回新版入口。未运行模型或账户接口，未部署；测试是代码与最小 DOM 模拟检查，未进行浏览器视觉验收。

下一步先由用户评审机构总览的信息优先级与密度，再单独确定公司内多 Agent 的研究切换形式。

## 2026-10-01：公司栏目统一为列表与内容

用户希望四块概览按需展开，并明确选择手动切换；随后进一步要求公司各栏目复用左侧列表、右侧内容结构，顶部栏目保持稳定，压缩 Logo 和标题区域的空白。本次沿用 uteki-interface 和已认可的三层外框，继续在 company-workspace-v2 样板迭代。

概览左侧保留公司变化、研究报告、资料与数据、关注点四个标签及范围明确的数量，右侧仅显示当前摘要。悬停停留 140ms 后切换，快速经过取消；点击、标签方向键和前后按钮提供等价入口。移出后保留内容，不自动轮播，不劫持滚轮。面板使用 180ms 轻微淡入，并响应减少动效设置。每家公司在会话内记住所选概览栏目；键盘阅读时鼠标经过不能隐藏有焦点的正文或证据。

研究报告使用按 Manager 分组的左目录与右侧完整正文；选择报告后目录仍可直接切换，历史版本、审核状态和原文保持。资料与数据使用证据条目目录与来源详情，关注点使用问题目录与原因、前后判断、关联报告及证据。长内容通过点击选中；初次未选择时展示提示，不将第一条数据自动设为用户的研究对象。资料和问题的选择在会话内按公司与栏目分别保留，详情切换不替换外侧导航。

顶部工具栏、公司标识与横向栏目高度由 54 / 90 / 42px 压缩为 44 / 62 / 38px，共节省 42px；公司图标 36px、标题 22px。内层目录默认 210px，报告使用主要宽度。工作区宽度不足时证据上下文改为右侧浮层，避免再次压窄报告。原生正文滚动、目录独立滚动和上下文返回继续保留。数字仍分别代表事件、独立报告、证据条目和未决事件；不新增未读、自动执行或采纳状态。

可观察路径：公司概览悬停“研究报告” → 只显示该摘要 → 打开完整报告目录 → 选择具体作者的一份报告 → 左目录保留且右侧显示全文 → 查看历史版或证据 → 返回原文。资料和关注点用相同的列表选择方式呈现各自详情。资源版本为 `20260930-overview2`；数据仍为原具名虚构样本。

验证：42 项渲染与控制器交互检查通过，脚本语法通过；本地 HTTP 预览已返回新版入口。覆盖单面板可见、延迟悬停及取消、手动切换和键盘范围、各公司选择隔离、资料与问题的显式选择、无预选 / 跨公司错误、历史报告完整正文与版本、目录和正文滚动、重复点击保留位置及证据返回焦点。另进行代码审查并修复目录标识与选中样式同步。以上为代码和最小 DOM 模拟验证，未进行浏览器视觉验收；实际密度与过渡观感由用户评审。

下一步先评审这套统一结构的阅读宽度和选择方式，再根据反馈细化每个栏目的信息优先级。

## 2026-09-30：公司页内栏目与紧凑概览

用户认可三层导航后，要求逐块完善公司页：右侧也能直接切换栏目，概览在一屏内交代有哪些板块及各自值得关注的近况，提高信息密度。本轮保留 nav5 已确认的全局导航与对象列表，只改右侧栏目和公司概览；Manager 复用栏目位置，内容方案暂不扩展。

右侧实体标题下增加常驻栏目，与左侧悬停菜单链接到相同对象和视图；报告正文时“研究报告”保持选中。概览改为动态、研究报告、资料与证据、关注点四块，每块明确数量与状态、最多两条预览及完整入口。全部动态在右侧上下文列出；查看事件、证据后可逐层返回。完整报告、来源与版本不压缩为卡片正文。

消息式数字和色点表达数据中的变化类型或待验证状态，没有新增未读状态。报告按独立 reportId 计份，资料按证据条目计数；当前和历史待复核版本分别标注。预览顺序由当前公司的日期字段确定，空资料与未发布报告保留明确缺口。没有模拟运行任务或修改采纳状态。

视觉采用两列四模块、紧凑标题和行距，缩小工具栏与公司标题区域的冗余留白，保持原报告字号。目标为正常桌面的一屏概览；窗口较小或展开详情时保留自然滚动，不截断整块内容。资源版本为 `20260930-overview1`。27 项渲染 / 控制器检查及脚本语法通过，覆盖右侧栏目范围与激活状态、四模块完整计数和有限预览、全部事件可达、变化 / 事件 / 证据返回链以及原三层导航和阅读锚点。以上是代码与最小 DOM 模拟检查，本轮未进行浏览器视觉验收。

下一步先由用户评审 Alphabet 概览的信息优先级与密度，再进入 Manager 概览设计。

## 2026-09-30：三层工作台与最左导航 Hover 展开

用户明确确认“hover 展开最左侧导航；对象列表保持可见”。本轮把原先混合的侧栏拆成工作台导航、对象列表、右侧内容三层。品牌和公司 / Managers 分类入口移入最左导航；搜索、六家公司或两位 Manager 名单、对象内容目录留在独立列表。沿用 uteki-interface 与现有页面数据，不使用 frontend-design，不修改产品原型或新增后台能力。

可观察例子：进入 Alphabet 报告后，悬停最左窄栏 → 导航名称出现，列表与正文平滑向右让位 → 移出后回收；公司名单始终可见，当前公司、报告、版本和正文不变。点击 Managers 后，仅列表与相应内容按同一工作台更新；返回公司恢复此前阅读位置。

布局明确为三列：全局导航 60px / 184px、对象列表默认 232px、余下为正文。全局导航进入延迟 80ms、离开延迟 180ms，列宽过渡为 240ms ease-out；对象菜单保持独立的 160ms / 220ms 生命周期。无固定按钮或遮罩。图标位置不变，文字淡入；键盘焦点保持导航打开，Escape 收回，点击开关提供触屏等价操作。减少动效设置关闭过渡。

导航变化不重建正文或名单。宽度过渡期间根据可见段落补偿滚动位置，并让对象菜单跟随所属列表定位。全局导航临时状态不写入显示偏好；旧 sidebarOpen / sidebarPinned 偏好不再影响名单可见性。仍仅保存语言和主题。入口资源版本更新为 `20260930-nav5`。

验证：23 项相关交互检查通过（22 项整套检查，加 1 项新增键盘 / 鼠标交接检查单独运行），脚本语法通过。覆盖三层归属、独立 hover、旧偏好兼容、模式切换、两次宽度重排的阅读锚点补偿、键盘保持与退出、原公司 / 作者 / 报告 / 版本和证据隔离。另检查三列定位与减少动效规则。以上为代码和最小 DOM 模拟验证；未进行新的浏览器视觉检查，推动动效的实际观感由用户评审。

下一步先体验最左导航的推动幅度和对象列表密度，再进入右侧内容的细化。

## 2026-09-30：侧栏简化为展开即固定

用户认为“展开之后还需要固定”是多余步骤。本轮移除固定按钮、侧栏浮层、外部点击关闭、模态遮罩与焦点限制。侧栏只保留展开 / 收起：展开直接常驻左侧，收起让出正文空间。导航、点击正文与 Escape 不再收起侧栏；实体悬停目录和研究上下文仍可分别通过 Escape 关闭。

可观察例子：在报告中阅读 → 收起侧栏 → 展开 → 直接出现固定左栏，报告身份、正文与阅读锚点保持；切换公司或 Manager 后侧栏仍展开。展开状态在本机保存，旧版“未固定”偏好不再使新侧栏进入浮动或关闭模式。公司列表、透明 Logo、报告与证据范围保持原样。

沿用 uteki-interface，更新其样式指南中的侧栏规则。资源版本提升为 `20260930-nav4`，防止上一版浏览器缓存遮蔽修改。本轮脚本语法及 21 项相关交互检查通过，覆盖直接展开、关闭、阅读位置、导航、焦点和偏好迁移；未新增浏览器视觉检查。下一步由用户体验这一个开关是否符合习惯，再继续右侧内容设计。

## 2026-09-30：透明原图、悬停目录与点击浮动侧栏

用户要求先修正 Logo 底色与导航，并明确选择“点击左上角按钮，浮层展开；点击外部收起”。本轮只修改独立的 `docs/design/company-workspace-v2/` 样板，继续应用 uteki-interface；六家公司、报告、版本和证据范围不变。

可观察例子：收起侧栏 → 点击左上按钮 → 侧栏浮动覆盖正文 → 悬停 Alphabet 后在旁边显示内容目录 → 选择报告才切换正文；点击侧栏外部收起，固定按钮可恢复常驻侧栏。公司和 Manager 的实体菜单共用同一行为。菜单打开延迟 160ms、关闭延迟 220ms，跨越间隙不闪退，快速经过不打开；键盘 / 触屏保留显式按钮，Escape 取消待打开或已打开菜单。整个侧栏不由 hover 控制，原生滚动仍只用于阅读。

透明 Logo 使用已确认 JPEG 的 `[272,186,258,342]` 裁区。生成工具候选略微改变蓝色和高光，未接入页面；用户明确授权“直接程序抠底，保留原图颜色与纹理”后，采用连通白底移除和单像素边缘去混色，输出 `assets/uteki-drop.png`。96.28% 主体像素 RGB 完全不变，其余仅校正边缘；白底重新合成的最大误差为 0。来源、原文件哈希、参数及重现脚本一并保留。页面移除白色容器和旧 JPEG 定位裁切。

用户随后反馈“没有变化”。核对发现 Logo 接入尚未完成，且浏览器持有旧 CSS / 模块缓存；本地服务曾停止，已恢复 HTTP 200。接入透明图片并更新入口及渲染模块的资源版本。文件直开增加本地预览入口提示，避免停在加载文字。当前可评审入口为 `http://127.0.0.1:8769/docs/design/company-workspace-v2/?v=20260930-nav3#/company/alphabet?view=overview`。

验证：本轮 20 项渲染 / 控制器检查及 12 项悬停计时检查通过，脚本语法通过。覆盖侧栏状态、模式切换、阅读位置、键盘焦点、Escape 取消、菜单间隙与跨公司 / 作者范围。定点浏览器检查确认新版 PNG 实际加载、背景透明、点击收起 / 浮动展开 / 点击外部关闭、键盘打开公司内容目录；在当前桌面视口查看了透明 Logo 与菜单。悬停时序由自动检查覆盖，未宣称已经实际移动鼠标验证；未做多视口检查，视觉偏好仍待用户反馈。

下一步先由用户体验悬停目录与侧栏浮层是否自然，再细化右侧内容；此迭代不扩展数据能力。

## 2026-09-30：统一实体工作台与左侧二级目录

用户发现 Managers 入口带来整体架构跳变，并明确以实体组织其属性、关系和产出。确认问题是样板链接跨到原结构稿。此次在同一个 [工作台样板](design/company-workspace-v2/index.html) 中实现公司与 Manager 的共用外框，保留原公司入口 URL；原标注稿页头新增明确的统一样板入口。未修改产品原型或六家公司数据，不使用 frontend-design。

可观察例子：在 Alphabet 原始资料处滚动 → 顶部侧栏切 Managers → Field 的报告 → 阅读 Field 的 Alphabet 报告及引用 → 返回 → 切回公司。公司与 Manager 的导航宽度、工具栏、标题区和正文区域保持同一结构，最近对象、目录和会话内阅读位置恢复；从 Manager 报告更换版本时保持 Manager 身份。

左侧先采用同栏树形目录，侧栏上方切实体类型，下方是公司或 Manager，展开后展示该实体的内容类别；移除正文上方重复的页内标签。此细节已通过异步问题请求用户选择“树形或并排两列”，当前树形属于待评审实现。公司有概览、报告、资料、关注点；Manager 有概览、研究覆盖、报告、持仓与表现、操作记录。折叠不改变正文。报告正文、证据面板、语言和主题继续共用，不另造一套 Manager 阅读界面。

Manager 数据严格按作者过滤，报告入口显式绑定 Manager、公司、报告、版本及章节。研究覆盖、关注和持仓分开；当前仅有研究覆盖和虚构报告。收益 / 持仓 / 交易没有接入，显示缺口而非假数字或图表；操作记录中的报告发布历史单列，不能用研究事件替代交易。未对用户口述的“transfer report”猜测新的产物契约。

验证：模型 22 项和渲染 / 控制器 14 项聚焦检查通过，覆盖原公司兼容、双入口路径、Manager 作者隔离、历史引用、模式切换恢复、折叠不影响正文、固定版本与返回焦点。另对两位 Manager × 中英 × 5 个视图进行 20 次渲染、140 个链接归属检查。以上为代码 / 最小 DOM 模拟检查，没有浏览器排版、滚动重排或视觉验收；本轮按项目约定由用户评审。没有模型调用、真实交易或部署。

下一步先确认左侧树形目录是否符合实际使用；然后细化实体的二级内容和 Manager 账户有数据时的呈现。真实数据接入及产品原型迁移单独安排。

## 2026-09-30：公司工作台样板 v2（应用调研结论）

用户在 Anthropic 金融交互调研后同意继续推进。本轮交付独立的 [公司工作台样板](design/company-workspace-v2/index.html)，预览为 `http://127.0.0.1:8769/docs/design/company-workspace-v2/`。沿用 uteki-interface，不使用 frontend-design；原页面标注稿与 `apps/uteki_zero/` 产品原型不变。公司列表、原始雨滴及六个已登记的本地 icon 保留。

可观察行为：从 Alphabet 概览展开“扩建与成本缺口”，选择 North 主报告 v1 的投入回报段落，查看该版本引用，收起证据后继续阅读；切换 v2 后返回公司目录，恢复原行与滚动位置。Microsoft 展示不可用续约证据，其余公司的报告缺口保持明确，不能借用其他公司的内容。

视觉与区域决策：左侧固定关注公司，中间以变化简报和按 Manager 分组的报告为主，右侧上下文按需展开。保留冷灰背景、浅色纸面、细分隔和蓝色交互，正文 17px / 1.85、阅读宽度约 720px；提供亮暗主题、中英界面。完整报告和证据保留中文原版。概览、研究报告、资料与数据、持续跟踪通过明确点击切换，滚轮与触控板只负责原生阅读。设计标注收纳在“设计说明”中，描述各区域的问题、内容、动作与边界。

数据与状态：读取已有 catalog/research 的具名虚构样本，空 URL 通过独立 DEMO_LAUNCH 明确选择 Alphabet。无效公司 / 报告 / 版本返回错误，不替换业务范围。事件按唯一事件计数，不显示为未读；报告份数不重复计算版本，证据条目数不冒充原始文档数。主报告与专题身份独立；报告保存作者、版本、截止及审核状态，阅读不修改审核 / 采纳。持续跟踪页展示待验证问题，并明确自动任务未接入。前台没有模拟模型执行、财务数据查询或交易能力。

检查：15 项模型范围测试和 9 项渲染 / 控制器检查通过；另执行 64 个范围明确的页面 / 语言组合渲染及脚本语法检查。覆盖明确路由、历史全文、精确章节与版本链接、跨公司证据隔离、不可用证据、返回焦点与存储滚动位置。16 个预览资源均返回 HTTP 200，模块 MIME 正确。控制器检查使用最小 DOM 模拟，不等于浏览器实际排版及滚动锚点验收；按约定由用户评审视觉，未做截图或多视口检查。没有调用模型或部署。样板的阅读位置只保存在当前页面会话，显示偏好单独保存在本机。

下一步：先收敛这一张公司样板的密度和内容优先级；随后设计 Manager 表现总览及持仓 / 交易详情。组合数据、查询、自动监控、版本比较和实际执行仍不属于本轮完成范围。

## 2026-09-30：Anthropic 金融产品交互调研（独立观察，未改版）

用户希望风格参考 Codex、ChatGPT 或 Anthropic，并明确先调研 Anthropic 的金融设计交互。本轮聚焦公开官方材料；没有登录金融产品实操、安装插件、修改页面稿或运行金融分析。不使用 frontend-design。研究不是对 Claude 全量金融能力、引用准确性或 Uteki 后端的验收。

核对资料与观察：

- [Financial Advisors 发布说明](https://claude.com/blog/claude-for-financial-advisors)（2026-09-14）说明以连接器和工作流支持会前准备、组合分析等任务。[官方 45 秒演示](https://www.youtube.com/watch?v=oMpb-u6HZBQ)已通过浏览器查看约 10、20、25 秒画面：10 秒处展示连接状态；20 秒处右侧区分 Progress、Outputs、Context；25 秒处已有来源完成列表、独立简报文件卡片和并排展开的正文。属于官方演示画面观察，不是实际账户操作。嵌入播放器出现配置错误，经其正常“在 YouTube 上观看”链接成功打开。
- [官方组合报告 HTML 示例](https://assets.claude.ai/brand/artifacts/solutions/financial/v3/fsi-portfolio-reporting.html)已读取并目视：上方收益 / 基准 / 超额，中部行业贡献，底部风险指标。它是官网演示成果，所有数字仅作展示，不代表独立的金融终端或实际投资业绩。
- [投资 memo 教学](https://academy.claude.com/use-cases/draft-investment-memos)描述先明确公司、期间、数据和输出文件，交付摘要及 Word 文档，再继续核对来源或扩展分析；这是教学路径，不等于用户只通过聊天才能工作。
- [2025 Financial Services 发布页](https://www.anthropic.com/news/claude-for-financial-services)中的价格 / 事件图已打开查看。它是生成成果的宣传示意图，不能据此推断真实应用布局。来源回链能力属于官方功能说明，未验证逐条引用准确性。
- [Cowork 与金融插件说明](https://claude.com/blog/cowork-plugins-finance)介绍跨 Excel / PowerPoint 保持任务上下文。其一张 CDN 界面图被浏览器站点安全策略拦截，未查看该图、未绕过限制；不据此做视觉结论。

对 Uteki 的设计推论（均待评审）：保留公司 / Manager 的长期对象导航；让报告、证据或组合成为主要内容；进度、相关资料和可选追问作为可收起辅助区域。默认已完成研究直接可读，不因借鉴对话界面而新增必需问答步骤。Manager 总览按“表现如何 → 原因 → 风险”组织，详情连接持仓、交易与当时报告。颜色以中性纸面、轻分隔为主，强调色优先表达状态；前述观察不能替代对 Uteki 配色、密度和布局的具体评审。

下一步先共同看官方视频 20～25 秒及组合报告示例，选定要借鉴的区域关系，再只修改一张公司页面作为样板。当前 23 区域标注稿保持原样。

## 2026-09-30：独立的页面与交互标注设计稿 v0.1

用户同意先设计页面、交互和每个区域展示的内容，并询问是否需要文档插件。本轮使用本地 HTML 设计文档，不需要新增插件；应用 uteki-interface 与插件管理指南，不使用 frontend-design，不改变现有产品页面或公司列表。Agent 工程主线的同期文档改动保留，本稿作为独立设计支线。

交付入口：[页面与交互设计稿](design/page-blueprint/index.html)。包含页面地图、公司工作台、Manager 总览、Manager 详情、共享报告阅读、材料证据与能力边界，共 7 个文档视图、23 个区域标注。标注说明用户问题、字段、业务来源、点击行为和异常状态，区分已明确、设计建议和待确认。视觉采用冷灰文档框架、连续阅读、细分隔和蓝色编号，编号仅供评审，不进入产品。

最新优先级：公司看变化与研究；Manager 总览看表现，详情默认持仓构成（含现金）和交易，研究覆盖与持仓分开。示意比例、占位收益和报告内容明确标注，Field 用于表现 / 持仓数据缺失示例，不借用 North 的账户。公司主报告与专题保持不同身份，明确版本；公司报告的单公司归属与组合报告的跨公司归属单列待定。数据能力覆盖自主获取、监控、处理核验、查询计算和证据交付；技术执行概念不作为必经前台菜单。

可观察例子：由公司选 North 主报告，打开证据后返回；由 Manager 展开交易理由，打开固定 v2 依据；比较右列 Field 引用时左侧仍保留 North 入口；从资料目录进入证据不虚构报告采纳关系。正文 / 变化 / 比较、语言示意、版本、页内标签、交易展开、持仓列表选择与状态示例可点击。环图直接选择、生产阅读位置持久化、真实长文和真实数据接入未实现。

验证：脚本语法通过；以 Node VM 的 DOM/history 模拟核对 7 个文档视图、23 个标注字段、25 个状态组合、固定版本、主报告 / 专题身份、比较作者与入口隔离、引用上下文、缺失账户和返回路径；本地资源、六个 icon 路径与生成元素 ID 检查通过。只做结构及控制器检查，未进行浏览器视觉验收、研究模型调用或部署。下一步先评审公司工作台，再评审 Manager 两页，然后收敛报告与证据细节。

## Separate texture-slide option

User explicitly requested broad colour blocks sliding along the original texture,
as a new option while retaining the current effect. The existing selector gains
a third option, Texture slide / 纹理滑动; layout, artwork, typography and material
choices stay in the same places. This standalone logo study continues its approved
blue palette instead of adopting the research workbench's warm palette.

The new renderer follows separate curved paths for the two lobes. Source image
positions remain fixed; moving colour fields preserve photographic detail and
white negative space. This is an art-directed path, not recovered physical flow.
Color flow remains a separate renderer with its source SHA-256 unchanged:
`33da549522e26d1ee0cf4f284cdead81b30ee7a8f31c9b3df75e51aa9ef9d575`.
Each effect keeps its own play time and intensity, with the same pause, reduced
motion and original fallback controls. The inactive renderer is disposed.

Twenty-one focused controller checks pass, covering both effect lifecycles,
settings isolation, original fallback and old-renderer/V1 hashes. The mock
renderer checks do not establish GPU appearance or aesthetic acceptance.

Targeted browser runtime checks confirmed shader compilation, slide/flow/slide
switching on one canvas and both material uploads, with no recorded warnings or
errors. The 7.5-second new loop uses a small interpolated arc-coordinate map;
source image detail stays at its original resolution. No additional viewport
checks or changes to the existing color-flow shader were made.

## Additive color flow on the same page

Latest user instruction authorizes a same-page addition. The working page now
has Original / Color flow selection, defaulting to Original. The approved V1
release and its five runtime hashes are unchanged. Existing artwork, wordmark,
positions and crop coordinates remain the base; the new shader samples those
exact positions and outputs a blue-only color overlay. No UV warp,
geometry, new lighting or reconstructed material is used. Near-white highlights,
white background and negative space receive no overlay. The first 9-second
exposure-only loop was reported as imperceptible. It is now a 6-second curved
ice-blue front moving from tip to base with a deep-blue trailing region.
Screen/multiply colour operations preserve photographic pixel differences.
Maximum overlay alpha is 0.85; default strength is 0.8. The controller accumulates
play time; the renderer alone owns the period, avoiding a reset at 9 seconds.

Keep sidebar control space reserved when original mode hides motion controls,
so toggling does not move the title or logo. Original mode stops the frame loop
and hides the overlay; intensity zero is transparent and stops scheduling too.
Pause, background suspension, reduced motion, two materials, language and focus
view remain supported. Any GPU failure preserves the original image.

Verification uses focused behavior/rollback checks and V1 SHA-256 verification.
A targeted desktop browser comparison checks the previously reported material
loss: original detail, shape and the white opening remain visible in color mode.
No aesthetic approval is claimed for this new sample; the user judges it.

After the visibility feedback, all 13 behavior checks passed, including playback
past 6 and 9 seconds, pause/resume and frozen release hashes. JavaScript syntax
and diff whitespace checks passed. Targeted current-desktop GPU frames show the
bright blue region in different positions with stable shape and original detail.
The browser initially mixed new HTML with cached old scripts; versioned script
URLs now load the new description and 80% default together. No viewport expansion
or workbench regression was added.

Current status: the user approved the restored original-image page and asked to
freeze it. Five runtime files were copied byte-for-byte into
`apps/logo_studio/releases/v1-original-2026-09-24/`; its `manifest.json` records
and verifies SHA-256 and byte counts. No further visual change, Git delivery or
deployment was made. The accepted release includes both original JPEGs, language
switching and focus view, with no active motion renderer.

Next iteration is explicitly additive: create flow through local blue color and
brightness changes while preserving the original silhouette, central S-shaped
negative space, glass detail and wordmark. Keep the frozen directory untouched;
implement a separate variant with original-image comparison. No geometry warp,
silhouette reconstruction or replacement material. This direction was recorded during the freeze task; the later same-page
implementation is described above. See
`apps/logo_studio/RELEASES.md` for the acceptance boundary.

The experiments below were rejected. Nine checks previously passed, including
original-only restoration; the other eight cover the retained prototype branch.
Those checks do not approve the rejected motion effects.

User requested an attractive animated logo page using two supplied JPEGs, with
flow and breathing on the drop itself, and explicitly requested no reliance on
the frontend-design skill. This page follows the supplied images directly.

Scope: standalone `apps/logo_studio/index.html`; no workbench routes, company
list, research state or existing styles changed. No SVG, generated replacement
image, model call or deployment. Both JPEG assets retain their original SHA-256.

Visual choices: cold paper #F4F7FB, white #FFFFFF, deep blue #112B4E, secondary
blue-gray #64778E, water blue #2867AB, edge #DDE5EE. Original raster wordmarks
preserve the supplied typography; Songti/Georgia for the short title and local
Avenir/PingFang for controls. Large quiet logo stage with a compact adjacent
control column; controls stack beneath the stage on narrow screens. The image's
blue palette applies only to this isolated brand study.

The three effects are Flow, Ripple and Breathe. Following direct feedback that
image-based UV deformation lacked visual quality, the current renderer constructs
an actual rounded implicit volume from each raster silhouette. A 384px signed
distance field preserves the exterior and central S-shaped opening; only tiny
white flecks are repaired. GPU ray marching computes surface normals, simplified
blue absorption and broad photographic softbox reflections. The source image no
longer supplies baked lighting to the moving surface. Ground rings, motes and
sweep stripes have been removed; only a soft shadow remains.

Flow moves broad reflections and subtly shifts the curved volume. Ripple varies
the cross-section along the height. Breathe changes depth slowly with only a small
front-outline expansion. Pause, replay, 0.5–1.5 speed, two source silhouettes,
bilingual controls and focus view share one clock. Reduced motion starts paused;
background tabs stop drawing. Resource failures retain the previous image. GPU
loss has an explicit raster fallback. Focus view makes offscreen controls inert,
focuses the stage for Space pause/play and exits on Escape. The mark keeps its
accessible name when WebGL replaces the decorative raster fallback.

Validation: JavaScript syntax, local asset/DOM references, HTTP serving, original
image hashes and eight focused state/interaction tests. Following the user's
concrete visual feedback, targeted desktop browser inspection verified actual
GPU rendering and identified/fixed an overfilled central opening, purple color
cast and coarse distance-field normals. No additional viewport matrix or broad
workbench regression. User aesthetic acceptance remains distinct from tests.
This is a silhouette-derived 2.5D volume with simplified optics, not a recovered
3D source model, physical fluid simulation or rendered video.

---

# Company notebook · 2026-09-18

User selected the company notebook demo. This direction supersedes the earlier
blue-gray palette. Applied the official Anthropic frontend-design skill installed
at ~/.codex/skills/frontend-design/SKILL.md; original license retained.

Plan: paper #FCFBF9, reading surface #FFFFFF, ink #30312F, muted #71716B,
divider #E6E3DE, accent #8A7053. Georgia for the wordmark and company identity;
Avenir Next / PingFang SC for bilingual reading and controls. Dark ink actions,
bronze links and selection markers; semantic warnings remain distinct.

Layout: left aligned research with a white reading surface and quiet paper margins.

```
Global navigation / company identity
Research sections
Researcher index | continuous report | materials and version history
```

Brief review: preserve the selected notebook's calm reading hierarchy without
copying demo-only chapters, fake team events or decorative numbering. Home remains
an attention queue; structured data remains a table. Companies retain their current
list layout. Reading, review and adoption remain separate, and source documents
remain unthemed. Existing responsive layouts and reduced-motion support are retained.
Shared tokens replace old blue selections, with scoped workspace rules for embedded
page styles. No data, model output, routes or review logic changed.

Verification: 241 Python checks and 7 JavaScript checks passed. Browser inspection
used the production renderers with isolated, explicitly labeled fixture data:
desktop company overview, report directory and report reader; 390px report,
structured table, materials and attention dashboard. Report and data pages had
390px document width with no page-level overflow. Financial tables scroll within
their container. Verified bilingual switching and the daily-viewed checkbox;
the pending-review label remains after marking viewed. Fixed nested support labels
that previously displayed both languages. Reset viewport after inspection.

Limitations: the original complete data/ and experiments/ inputs remain unavailable.
The temporary preview does not implement research mutation or annotation APIs
(the reader correctly reports unavailable annotations); evidence integrity and
review behavior were covered by existing offline tests, not full live-data browser
acceptance. Source documents and legacy experiment pages were not visually checked
in this pass. No model calls or deployment.

---

# Research archive visual direction

## Independent annual narrative · 2026-09-15

Applied frontend-design to the actual Single Agent candidate reading page. Reuse
white #FFFFFF, ink #243347, secondary #68768A, blue #285DB0 and soft #F7F9FC;
Avenir Next/PingFang SC, left-aligned continuous prose with a sticky 220px contents
rail and a mobile horizontal contents list. No dashboard cards or decorative
metrics. Preserve model titles and paragraphs, even when verbose: this is an output
review, not editorial correction. Cap visible source links at three and retain
ellipsis/hover quotes; unread references explicitly say unverified. Fold call
purposes and per-call cost records below the report. Browser screenshot verified
desktop spacing and successful local route rendering. Runner's three tests pass.
Only report generation used the model; presentation involved no additional calls.

## Researcher streams · 2026-09-14

Backend-first change. Preserve white #FFFFFF, navigation #F5F7FA, ink #202B3B,
secondary #596779 and blue #275DAD; keep Avenir Next/PingFang SC. One material row
per selected researcher/scope, left aligned; candidates and immutable history fold
into the report rather than multiplying sidebar cards. Native selects and existing
dialogs are sufficient; no new visual system or company-list redesign. Review
against brief: identity separation belongs on the server, not just a UI filter.

Verification: 197 offline tests passed, including researcher isolation, concurrent
replacement, migration preservation and HTTP review/replacement. Browser QA used
an isolated archive for adoption and editing; confirmed researcher switching,
one material row, pending revision text and the original remaining effective.
The production archive migration preserved all four snapshots and their statuses,
comments and underlines with a byte-exact backup. Production screenshot verified
the selector and unchanged evidence-failure gate. No paid model calls.

## Reading underlines · 2026-09-13

Keep the quiet white/blue-gray workspace, existing Avenir/PingFang type, and no
additional permanent panel. Selected claim text reveals a compact floating action;
saved marks use a thin amber underline, not a large filled card. Clicking an
underline offers removal. Keyboard selection and Enter on a saved mark work too.

Reading marks are not opinions, adoption decisions or source annotations. Store
them separately from snapshot contents, with independent revision checks, Unicode
code-point offsets, exact quote and claim hash verification. Keep creation/removal
timestamps in the audit history; never inherit marks into another snapshot or
analysis context. No model calls. D0 supports one claim paragraph per selection;
overlapping marks are rejected with an explanation. Deleted snapshots are read-only.

Verification: 182 tests passed. Browser QA on an isolated archive confirmed Chinese
text selection, save, persistence after reload, removal and persistence of removal.
Fixed a collapsed-selection event that prematurely dismissed the removal toolbar.
The production-local page was reloaded to confirm the annotation entry point; no
test marks were written into the user's archive.

## Unified workbench · 2026-09-13

Scope now explicitly includes the companies list and all local workbench page
families: archive, data inventory/status, navigator, business result, Cloud views,
and served experiments. Raw SEC source pages and iframe documents are excluded.

Tokens: white #FFFFFF, navigation #F5F7FA, ink #202B3B, secondary #596779,
interaction blue #275DAD, warning #85531E. Avenir Next / PingFang SC throughout.
Layout stays left aligned: navigation, quiet filters, continuous content. Use
spacing and subtle hover/selection backgrounds rather than boxes and ruled cards.
Keep borders where they encode actual financial table cells or focus affordances.

Review against brief: no terminal restyle, decorative hero, wholesale route
redesign or animation on every row. Existing snapshot, search, filter, pagination,
translation and evidence behavior stays intact. A shared presentation module/CSS
is applied explicitly to renderers, never to source renderers. Archived experiment
files remain immutable; the served presentation receives the style at runtime.
Transitions are 140ms on controls; user-triggered drawers/previews reveal over
160ms. Reduced-motion preference disables both. Desktop archive remains two
independently scrolling panes. Narrow readers stack without horizontal page overflow.

Verification: 169 tests passed. Desktop visual inspection covered companies,
research archive, data inventory, document navigator, business map, Cloud data,
Cloud analysis and served experiment comparison. Search and pagination, node
selection, original-layout switch and table-cell evidence navigation were checked.
The browser viewport override did not change actual viewport dimensions, so mobile
CSS is implemented but not claimed as visually verified; override was reset.

## Chinese evidence reading · 2026-09-13

Preserve the existing palette, typography, fixed rail and compact citation row.
Chinese mode uses a short translated excerpt; focus/hover shows the complete
Chinese translation followed by the unchanged English quote. English mode shows
English. Exact normalized quote matches select a versioned presentation-only
translation catalog, not source block IDs or fuzzy matches. No source snapshot,
model answer, evidence URL or validation flag is changed. Translations are
assistant-authored, explicitly pending human review, not official filing text.
Unmatched new quotes show a missing-translation label and English fallback.
No paid model calls. SEC source document remains unchanged in the evidence drawer.

## Compact evidence previews · 2026-09-13

Keep the existing six-color palette and Avenir Next/PingFang type. Replace long
multi-line citations with one-line excerpts capped at 28ch visually, alongside
the unchanged material badge. Preserve first-three disclosure and ellipses.
Hover or keyboard focus opens a readable full recorded quote; click still opens
the original source. The preview is viewport-constrained, scrollable, hoverable
and dismissible with Escape. Mobile uses the same direct source link.
Review: compact evidence supports reading the judgment, without replacing useful
words with IDs. No invented Chinese translation, model call or answer rewrite.

Validation: 18 UI/route tests passed; inspected the requested team snapshot in
the browser. Keyboard focus revealed all 618 characters of its first citation,
Escape dismissed the preview, and clicking still opened the anchored source.

## Fixed snapshot rail · 2026-09-13

Keep the approved paper/rail/ink/secondary/blue/warning colors and Avenir Next /
PingFang typography. Only change scrolling: company header and tabs stay in place,
with a fixed-height workspace beneath them. The left snapshot list and right
research document scroll independently. Use viewport flex/grid layout rather than
hard-coded fixed offsets so bilingual text, feedback and the evidence drawer fit.
On phones, retain the compact stacked list and normal document scroll.

Brief review: this preserves the researcher's place in the snapshot timeline while
reading long evidence-backed results; no new panels, decoration or data changes.

Validation: 17 UI/route tests passed. Browser scroll check moved the research pane
1,928px while the snapshot rail stayed at scrollTop 0 and the same viewport top;
header and company tabs remained visible. Screenshot reviewed after scrolling.

## Citation disclosure · 2026-09-13

Keep the existing palette, type and left-aligned evidence sentence. Show the first
three distinct references per claim; an inline bilingual Show more/Show less button
reveals the rest in place. Each claim controls its own disclosure. Preserve long
excerpt ellipses and all source links; this is presentation only. Keyboard focus
stays on the toggle and aria-expanded/aria-controls describe its state.

## Content-first citations · 2026-09-13

User correction: source links must read as evidence, not opaque IDs or numbered
buttons. Keep existing paper/rail/ink/secondary/blue/warning tokens and typography.
Each claim is followed by a left-aligned sentence: Based on [recorded excerpt]
[2025 10-K]; [another excerpt] [2026 Q2 10-Q]. The words open the original source.
The material tag uses the report period, never the filing year; unknown metadata
stays explicit. Source drawer captions show material and content instead of IDs.

No generated summaries or numbers: the recorded quote supplies the link text,
with an explicit ellipsis for long excerpts. Images without text stay labeled as
chart data with no excerpt. Failed-citation warnings remain; rendering does not
certify model quotes. Exact duplicate references collapse only in the display.
No model answers, original citations, or archive states are rewritten.

## 2026-09-13 · frontend-design first application

Audience: one researcher comparing time-versioned company judgments with source evidence.
The page is a reading and review tool, not a promotional dashboard.

Tokens: paper #FFFFFF; navigation #F1F4F8; ink #202B3B; secondary #566477;
interaction #275DAD; warning #85531E. Borders derive from the navigation palette.
Type: Avenir Next with PingFang SC/Microsoft YaHei fallbacks for interface text;
the same family for headings and reading. No downloaded font dependencies.
Numbers use tabular figures, not decorative monospace. Body line length <=76ch.

Layout: left-aligned, compact source/version rail and a readable continuous research
column. Opening evidence gives the source its own right column on wide screens;
on smaller screens it is an explicit closable overlay.

```text
Company identity                  Language
Research archive | Company data
Source / run rail | Question and provenance      | Source (on demand)
                 | Claims + evidence references |
                 | Changes, gaps, human review  |
```

Review against brief: a dark finance terminal or serif newspaper would be generic
here and harder to read for long bilingual claims. Use a quiet document workspace.
The distinctive focus is the selected source/version rail paired with precise
evidence, not color decoration. Remove decorative claim numbers; keep citation
numbers because they identify multiple sources. Fold pilot/provenance explanations
into a disclosure while leaving failed-validation warnings visible.

Scope: archive styling and company-data visual consistency only. No companies-list
redesign, altered model answers, adoption semantics, new model runs, or publishing.

Validation: 18 focused UI/route/data tests passed. Browser inspection covered the
desktop view, Chinese/English chrome, exact source highlight, and narrow layout
(390px override; 375px content viewport with no horizontal page overflow).
The viewport override was reset. Original model text and failed-citation state remain.

Skill installation: user-supplied body preserved at the local skill path. Removed
the frontmatter reference to an absent LICENSE.txt; no license terms were invented.
The bundled validator could not run because PyYAML is absent; frontmatter was
manually reviewed and file content compared against the supplied text.

## Earnings P0 reader / 2026-09-15

Apply the existing frontend-design system, not a new dashboard. Palette: paper
#ffffff, ink #202b3b, secondary #566477, evidence blue #275dad, selection #f1f5fb,
PDF evidence marker #bd8c21. Keep Avenir Next/PingFang SC for controls and text.
Left-aligned continuous transcript, expandable speaker/exchange sections, with a
sticky original-PDF page on the right. Native source typography stays intact in
PDF renders. Original English is explicit; controls are bilingual.

```text
Material type / year filters (existing company data page)
Call title and provenance
Prepared remarks | Q&A | Closing | Search
Readable turns and questions | Original PDF page + exact region highlight
```

Brief review: avoid report cards, new company navigation or artificial paragraph
tiles. Each click answers “where was this said?”; the source page is the primary
visual. No autonomous animation, visible keyboard focus, single-column narrow
layout. Company list and adoption/snapshot rules unchanged.

Verification: 205 tests passed. Browser verified native material filtering,
English/Chinese controls, call search, PDF p.14 selection/highlight, release
original tables, and 390px layout. Original page dimensions drive the overlay;
hide both old image and highlight while a new page is loading. Viewport reset.

## Researcher rail and annual baseline / 2026-09-15

Second review: keep the three-column layout. Right rail uses plain material headings with indented timestamp/version rows and a status filter, not tinted cards. Move candidate/history/audit disclosures out of the central report into the right rail. Palette and Avenir Next/PingFang remain unchanged. Selected text opens a compact note dialog; existing underlines remain and can receive notes. Review against brief: navigation belongs in the rail, research and anchored feedback in the center. No automatic model invocation.

Verified selected-text drag → feedback dialog → editable textarea → cancel in the real browser, without saving test text to the user's report. Backend tests cover atomic note save, edits, withdrawal, stale conflicts and rerun input freezing. Full suite: 222 passed, including offline model-stage input tests; no paid model requests.

Follow-up correction: the materials are a separate **right sidebar**, not a list above the report. Desktop wireframe: Agent list | report | material list. Both rails scroll independently; a narrow screen stacks navigation before the report. Keep paper #ffffff, rail #f4f7fb, ink #202b3b, muted #566477 and blue #275dad, with Avenir Next/PingFang SC. This corrects placement only, with no backend or report changes.

Verified in the local browser: Single Agent ↔ Team A filters material rows; material selection opens its report; ZH/EN controls work; evidence drawer opens and closes with its original source URL. Desktop and 390px layouts checked, viewport restored. Existing reports and user decisions were not changed.

Plan: retain paper #ffffff, ink #202b3b, muted #566477, blue #275dad and rail
#f4f7fb. Avenir Next/PingFang SC remain the reading/control family. Fixed-width
Agent/Team rail left; on the right a compact material/report list followed by the
selected report. Left aligned, no empty reserved evidence column until opened.

```text
Agent / Team list | Research topic + material/report list
Single Agent     | 2025 10-K   Annual research    Effective / Pending
Team A           | 2024 10-K   Annual research    Effective / Pending
                 | Selected report, sources, review and revision controls
```

Review: researcher identity must be visible, not hidden in a dropdown. Materials
belong in the right workspace; keep history collapsed within the selected material
and preserve one effective result. A wide empty status/evidence rail is not useful:
move status beside the report title and size text naturally. No company-list or
company-data redesign, no fake quarterly/peer analyses. Annual research establishes
hypotheses; supplemental analyses primarily test them, without automatic adoption.

## Codex sequential hypothesis MVP / 2026-09-15

Applied frontend-design to a separate review artifact, not the company workspace.
Visual plan: paper #ffffff, ink #233249, muted #65758b, blue #285db0,
evidence surface #f2f6fb. Avenir Next/PingFang SC; left-aligned continuous
research with a sticky three-stage navigation, one comparison table, and a
source dialog opened only on demand. No dashboard cards or auto-approval controls.
Review against brief: prioritize how a hypothesis changes, not a list of facts;
use semantic Chinese links with material labels, first three visible and the
remainder under More. Bilingual navigation; research Chinese and sources English.

Browser verification: stage links, Q2 segment-table evidence in the original
SEC HTML with visible highlight, dialog closure, and 390px body without horizontal
overflow (table independently scrollable). Temporary viewport restored. A rounding
correction is visible and links to an addendum; frozen research is not overwritten.
All source/answer/read hashes and original DOM quotes are checked by the artifact
validator. No company snapshots, decisions, or adopted contexts were changed.

## Annual revision interaction demo / 2026-09-15

Applied frontend-design to revision-demo.html using the three frozen real research
reports from the sequential hypothesis experiment. Plan: continuous white reading
surface, sticky report/version rail, semantic Chinese evidence links with period
labels, first three references visible, and a two-column before/after editor.
Palette: #ffffff paper, #233249 ink, #65758b secondary, #285db0 action,
#f2f6fb comparison surface. Namespaced CSS variables prevent shared-theme clashes.

Interaction review: Q1 suggestion -> human judgment/test/reason -> candidate ->
explicit demo adoption. Annual originals and Q1/Q2 answers stay immutable. Q2
becomes stale after adoption; no new Q2 output is simulated. The input preview
excludes unadopted drafts, old Q2 answers and old Q2 review opinions. Q1 remains
the historical basis of the revision, avoiding a circular dependency. This is
retrospective review, not a blind historical test or autonomous fact checking.

Verified in browser: candidate versus active distinction, explicit confirmation,
preserved v1 and active v2 after reload, Q2 stale message, before/after content,
context preview, and Q1 source-table highlight. 390px viewport has no body overflow;
temporary viewport restored. A test-labelled v2 is left for review in this browser.
Seven state tests and all 228 existing Python tests pass. State exists only in
browser storage with export; no formal archive mutations or model calls. Q2-based
editing and real re-execution are deliberately outside this demo.

## Annual-only reading view / 2026-09-15

User requested returning to the initial 10-K thesis, without quarterly results or
revision workflow. Plan/review: retain white paper, Avenir Next/PingFang and blue
evidence links; reserve #089981 green and #f23645 red for numeric sign, with explicit
plus/minus rather than relying on color alone. Put the plain-language thesis first,
then its three supporting questions, and annual-only metrics last. Label Search &
other as part of Services instead of implying parallel segments. No added dashboard
cards. The display rewrite preserves original answers and introduces no new research.

Added annual-report.html; original comparison remains available with signed colors.
Browser verified single-period metrics, green positive values and clear nested label.
Tests check annual-only citations, absence of quarterly result sections, preserved
original title, and red negative values in the comparison page.

## Five-part owner-oriented annual report / 2026-09-15

Plan reviewed against the user's brief: research should read as an argument about
the business, not a repeated validation form. Use a 210px quiet sticky contents rail,
an 850px maximum narrative column, a restrained company heading, and an introductory
thesis followed by Business, Industry, Earnings, Valuation, and To watch. White
#ffffff, ink #243347, secondary #68768a, links #285db0, detail surface #f7f9fc;
signed numeric green #089981 and red #f23645. Avenir Next/PingFang carries both
headings and prose. No card grid; one compact disclosure tree explains why Search
is nested within Services. Verification details and metric table are optional opens.

Preserves frozen answers; editorial module reorganizes existing annual research
and checked annual source blocks only. Industry confidence and valuation remain
explicitly limited rather than invented. No quarterly outcomes, new model runs,
adoption actions, or future green/red verification scores introduced.

Browser checked: current-section navigation, readable desktop and 390px mobile
layout without body overflow, and annual segment-profit evidence opens the actual
SEC table with one highlighted source target. Sources remain semantic and period
labelled. Responsive viewport is restored for handoff.

## Annual reliability comparison / 2026-09-16

Follow the same reading palette: white #ffffff, ink #243347, secondary #68768a,
source blue #285db0, separators #e0e6ef. Avenir Next/PingFang, left-aligned narrative
within 52em and a horizontally scrollable results table. The meaningful visual is
the side-by-side actual run comparison; no score cards, decorative animations or
green success banner that could imply research approval. Failed samples stay visible.

Reviewed against the brief: compare failure types and cost, preserve each original
model conclusion, clearly separate citation checks from semantic/numeric review.
Existing companies and research archive were not changed. Added bilingual navigation
and records links, keyboard focus outlines, responsive padding. Browser desktop
screenshot checked: all six completed runs visible, clear costs and pending review.
New derived report views show percentage coverage warnings; frozen raw outputs stay
unchanged. Narrow-screen visual testing remains pending for this comparison page.


## 2026-09-18 · Report editing and revision provenance

Plan: retain the approved reading workspace, with the report in the center and material/version history at right. Use the existing white #ffffff, blue-gray rail #f5f7fa, text #202b3b, muted #596779 and action blue #275dad. Diff removals use #fff1ed and additions #edf5f3, always accompanied by explicit before/after text. Keep Avenir Next / PingFang SC, left-aligned continuous report text with a 76ch measure. The report edit dialog uses a large body field and a short required reason, not a separate generic dashboard. Preserve the companies page.

Review against the research workflow: keep original evidence and historical reports visible; save as a new candidate, never replace adopted content on edit. Agent revision identity belongs to each revision, separate from the researcher stream. Show human/agent, timestamp, reason, before/after text, ancestors and model/run/artifact provenance. Raw JSON was replaced with readable text diffs.

Implementation: Markdown report rendering escapes raw HTML; safe external links only. Existing claim editing remains supported. Human browser requests cannot impersonate agent edits. Local agent revision handoff checks artifact integrity and writes a candidate with provenance. The existing archive rerun entry point now persists its answer as a child revision. No model call starts on human save.

Validation: core archive tests and isolated human → agent revision chains, stale-edit conflict, unchanged source content, source artifact integrity, HTML escaping, and browser API identity controls. Visual browser verification was blocked because the browser tool could not verify its admin-enforced security policy; no workaround was attempted. Full test counts are recorded in the delivery response.

## 2026-09-18 · Site hierarchy and home

Plan: a research desk, with global navigation Home / Companies / Reports. Company overview leads to Materials / Structured data / Research reports; a report leads to its outline, evidence and revision history. Keep raw source views free of application chrome. The home opens on the most recent available report, with an explicit candidate/adopted label and a compact list of ongoing company research. Avoid summary tiles that suggest the 50-company watchlist already has research coverage.

Tokens: white #ffffff, paper rail #f5f7fa, ink #202b3b, muted #596779, blue #275dad, divider #e1e7ef. Retain Avenir Next / PingFang SC and left-aligned reading text. The memorable element is a continuous research path from source material to data to report, backed by actual counts. Layout: global nav; breadcrumb; page title; broad report list with a narrow context column. On narrow screens stack the context column and allow tables to scroll.

Review: the old company page confused source structure with business-semantic data and exposed experiments as top-level product objects. Separate source indexes (inside Materials) from metrics/business map (inside Structured data); group report revisions under one report lineage. Old links remain valid. Company membership and labels do not change. User explicitly requested the company hierarchy, so its navigation is now in scope.


### Scope correction: company-first hierarchy
The user explicitly rejected adding more landing pages. The company list is the homepage (`/` and legacy `/companies`). There is no separate global report dashboard. Enter a company before opening materials, structured data or reports. Alphabet's business map is a child of Alphabet data; document indexes remain children of individual source documents. Existing experimental and legacy URLs remain available for provenance, but are not promoted in product navigation. Other watchlist companies show their actual empty coverage. Previous homepage dashboard proposal is superseded. Changes remain staged, not deployed.

Validation of the company-first revision: 269 tests passed; seven canonical HTML responses and their seven inline JavaScript blocks passed structural/syntax checks. Routes verify company isolation, PDF registry boundaries, document return links, report detail/history, and legacy redirects. Visual verification remains blocked by the previously reported browser policy verification failure. Original running project unchanged.


### Attention dashboard v1 — latest agreed hierarchy
The user now explicitly wants a dashboard homepage separate from the company directory. This supersedes the company-list-as-home decision. Home answers what deserves attention today; company detail prioritizes reading and editing analysis reports. Supporting materials, source indexes and structured metrics remain company-scoped.
Palette: paper #ffffff, rail #f5f7fa, ink #202b3b, muted #596779, action #275dad, review #85531e. Type: Avenir Next / PingFang SC; 32px page heading, 19px sections, 14–15px rows. Left aligned daily attention queue, a compact research-update rail, and subordinate expandable watchlist. Avoid large metric cards: the useful unit is a company plus a specific reason to open its report.
Plan review: no invented market alerts, newcomer counts or real-time dates. Existing priorities seed focus; report timestamps/audit events supply research updates. Missing company-added dates are explicitly unavailable. Local daily checkmarks are labeled as this-browser view state, not archived research approval. Company page gives most space to reports and places sources in a supporting rail.

Dashboard v1 verification: 274 tests pass, including grounded additions, timezone boundaries, exclusion of future updates, priority ordering, version grouping, and local-view checkpoint invalidation. Seven canonical pages and fifteen inline scripts pass response/syntax checks. Browser visual verification remains unavailable: CUA getTab reports the administrator policy cannot be verified. User's affirmative response and revised brief authorize applying this code-only version to the original project; report import remains excluded.


## 2026-09-19 Direct report review workspace

User requested fixed company tabs, left report navigation, direct middle report editing and right source snapshot. Plan: white #ffffff paper, #f1f4f8 rail, #202b3b ink, #566477 secondary text, #275dad selected state; reuse Avenir Next/PingFang SC. Layout: report list 250px | flexible reading/editing | source metadata 280px. All text left aligned. Retain document/researcher scope and revision provenance.

Brief review: remove overview feature cards and separate company report directory; render the existing archive immediately. Move material/report choices to the left, put source identity on the right. Editing is inline and saves through the original revision API. Catalog hashes are explicitly labeled catalog metadata, not falsely described as frozen run inputs. Companies list unchanged. Mobile order is list, report, source. Browser verification and regression results recorded in delivery.

Verification: 54 archive/UI/route tests and 5 report-revision tests passed; extracted JavaScript passed node syntax checking, empty report rendering passed, and git diff whitespace check passed. Restarted local server. Browser getTab was blocked because the admin-enforced security policy could not be verified; no visual/interactive browser pass is claimed. Existing paragraph-90 excerpt integrity gap remains unrelated to this layout change.


## 2026-09-19 Sidebar simplification

User explicitly prefers Claude/Anthropic styling. Reference: https://www.anthropic.com/ (text reference accessed; no claim of screenshot matching). Plan: warm paper #f5f4ef, reading #faf9f6, rail #eeede7, ink #30302b, muted #77766d, terracotta #a65d43. Use Avenir/PingFang for controls and Georgia/Songti for report headings. This intentionally follows the requested visual direction. Left rail contains only a researcher selector and one title per research material; scope, status filters and all historical versions remain accessible in collapsed right-side settings. Review against brief: hierarchy reduction is the main change, with quiet typography supporting reading. No company list or research data changes.


## Stable inline editing and fixed operations

User rejects layout replacement and scrolling to find actions. Reuse warm palette and existing typography. Keep the rendered document in place; editable text nodes preserve heading, paragraph, table and citation structure. Map Markdown blocks/cells back to source lines, leaving unchanged lines byte-for-byte intact. Plain-text paste and single-line block editing avoid browser-created structure changes. Save/cancel/revision note share a sticky toolbar; secondary actions remain in More. Existing revision API retains provenance and conflict guards. This pass edits text within existing blocks, not document structure. No visual verification is claimed while browser policy verification remains unavailable.

Validation: 54 archive/UI/route regressions and 5 revision tests passed. Heading/list/table source mapping and bold rendering checked; JavaScript syntax check passed. Browser interaction remains unverified under the existing policy restriction.

## Paragraph highlights and revision locations

User requested soft whole-block hover/focus instead of a left rule. Apply #eeeae2 without padding or font changes so editing does not shift layout. Revision history now projects persisted before/after values into individual changes, labeled by claim paragraph or Markdown source line, and displays save time. Preserve human/agent attribution and revision lineage; record on confirmed save, not each keystroke. Existing 54 archive tests and 5 revision tests passed; checked paragraph location, unchanged-block omission, additions and HTML escaping. Browser visual verification remains unavailable.


## Block review lifecycle

Hover highlights a text block; double-click (keyboard Enter) edits that block directly. A nearby acceptance control persists the block hash, actor and timestamp under the snapshot transaction/revision guard. Toolbar shows content acceptance count. Content approval is distinct from validated report-baseline adoption. Human/agent revision inheritance retains only unchanged block hashes; claims include citations in the hash. Markdown table cells are review units; headings and text lines correspond to rendered blocks. No automatic approval or model call. Browser visual verification remains blocked by the existing policy check.

Validation: 54 archive/UI/route tests plus 9 block-review/revision tests passed. New cases cover persisted acceptance, undo, stale revision rejection, changed-block invalidation with unchanged approvals retained, citation-sensitive hashes and table cell mapping. Extracted JavaScript syntax and whitespace checks passed. Whole-report baseline adoption moved into More so the primary workflow is block review.


## Lower-right acceptance and review sidebar tabs

User requests an unobtrusive lower-right acceptance control with a brief dismissal delay. Anchor below each claim (including citations) or rendered report text block; reserve whitespace, retain for 800ms after pointer exit, cancel dismissal while hovered/focused, hide on scroll. Do not move upward over text when viewport space is insufficient. Right rail now has accessible Sources, Revisions and Cross-review tabs. Cross-review is a clearly marked future execution entry: no fabricated results or model invocation. Proposed unit is a frozen whole report with paragraph-level findings and model/evidence provenance. Existing visual verification restriction remains.


## Text-local feedback

Anchor the compact acceptance/like/dislike control near the pointer over the actual text, not the containing claim/citations card. Dislike opens an inline reason form and freezes the target while entering text. Persist feedback through the existing opinion pipeline with source answer, block hash, researcher, vote and timestamp; mark carry_forward for the existing reanalysis context. Preferences are pending feedback, not automatically adopted general rules. User's negative assessment of Team's first paragraph is recorded in the task feedback below without guessing which historical version or detailed reason was intended. No new model run.


## Stable paragraph footer, replacing pointer-following controls

User screenshot shows cursor-adjacent controls obscuring prose. Remove pointer coordinates, fixed positioning and mousemove listeners. Reserve a 36px footer immediately after each text block, before claim citations; align controls right. Table cells share a footer after the table to preserve valid markup. Hover changes opacity over 140ms with no translation; dismiss after 600ms, retain during focus/feedback. Feedback form expands in document flow, never overlays prose. Editing hides controls but retains the footer space. Reduced-motion disables fades. Visual verification remains unavailable; screenshot diagnosis is user-provided.


## Insert and delete content blocks

User requests hover plus between paragraphs, typed insertion and persistent top-right deletion; dragging deferred. Insert facts, inferences, hypotheses or questions in-place as an unsaved draft. Save/cancel uses the fixed toolbar. Server derives structural changes from the persisted answer and validated indices; existing citations are preserved, inserted claims have no fabricated citations. Deletion removes a block from the new revision only. Unchanged unique content hashes carry acceptance across shifted positions. Table deletion is whole-table. New content remains unverified; no automatic fact approval. Visual verification remains unavailable.

Validation: 54 archive/UI/route checks and 14 structure/feedback/acceptance/revision checks passed. New cases cover insertion without citation mutation, acceptance migration across shifted indices, original-version retention after deletion, invalid positions/types/empty content, stale versions and Markdown table removal. JavaScript syntax and whitespace checks passed. Structural editing handles one insertion or deletion per confirmed save; cancel restores the draft.


## Selection endpoint polish

Shortened block acceptance label to 采纳 / Accept. Annotation feedback toolbar anchors above the selection focus endpoint, with backward/multiline fallback and viewport clamping; no change to annotation content. Deferred editorial bold/keyword emphasis to future report authoring as requested. JavaScript syntax and 26 annotation tests passed; browser visual verification remains unavailable.


## 2026-09-19: production home card workspace

User-approved direction supersedes pagination and expanding the whole layout. The real home now uses fixed card boundaries: reading queue, company research changes/recent/history, new companies/watchlist, and explicit disconnected news/portfolio states. Hover reveals a short excerpt inside the item; click reads inside the same card. No popup, backdrop or neighboring card reflow. Local read marks bind to report revision, not daily company checkboxes, and do not approve research. Full report links preserve the established evidence/edit workflow.

Palette: paper #F3F1EC, card #FCFBF8, ink #302F2A, muted #716D64, line #DFDBD2, accent #96503B. Songti headings with system fallback; compact sans-serif body. Main card occupies two rows; remaining modules use smaller cards. Native local scrolling; mobile uses horizontal card browsing. Shared navigation is sticky with restrained compact typography on scroll, reserving its height to prevent jumps. All text bilingual. Unknown company additions remain unknown; historical records exclude future/deleted records.

Source render and focused tests required; browser visual verification unavailable under current browser policy, so actual viewport/trackpad review remains manual. No model calls, financial data generation or deployment involved.


## Company directory compact pass

User explicitly requested company directory optimization. Remove duplicate product header, oversized hero and four KPI blocks. Compact heading, existing search/index/attention/holding filters, horizontally scrollable theme filters, then one continuously scrollable company table. No pagination; all 50 recorded companies remain filterable. Sticky table headings and shared navigation stay visible. Redundant sector/tag display is removed from rows; tags remain searchable. Selection policy and dated source links remain under Scope and sources. No company data, holding labels or research decisions modified. Palette follows shared paper/ink/line/accent tokens; 23px Songti heading, 13px company titles, 11–12px metadata. Code and rendering checks performed; browser visual review remains manual under current policy.


### Reference calibration

Read the local uteki research-exoskeleton mock styles and production company workspace, viewed its saved 2026-05-31 harness desktop screenshot, and read rain.blog global/article styles. These are references, not user-confirmed favorite screens. Preserve this app’s single-window table workflow; borrow restrained surfaces, stronger company names, neutral secondary text and cohesive controls. Avoid copying the screenshot’s large hero or sidebar, which conflict with the current request. Corrected a bilingual heading span selector that shrank the title. Applied a page-scoped six-color palette and compact segmented controls. Current page has not been visually verified in-browser; do not equate unit tests to design approval.


## Versioned style baseline

The maintained interface baseline is [Uteki interface style guide](../skills/uteki-interface/references/style-guide.md), loaded by [the reusable skill](../skills/uteki-interface/SKILL.md) and repository AGENTS.md. Historical notes above are implementation history; the maintained guide and latest user requests govern future decisions.

Home hover now reserves two lines for the excerpt, avoiding height changes and row displacement. Mouse focus does not leave a focus ring; keyboard focus remains visible. Only a subtle background/opacity change remains. This is not final visual approval.


## System-wide interface consolidation

The shared style guide now has an implementation token file: `apps/review_workbench/design_tokens.css`. Theme injection loads it before component styles. Company/research/home color forks are removed or mapped to shared tokens; retired homepage renderer and early company universe styling removed. Company detail headings, report rails/body spacing, source/data tables and shared controls are consolidated. All original snapshot, citation, review and edit behavior is retained. See [interface review matrix](INTERFACE_REVIEW.md). Browser visual review is still pending under current access policy; automated tests do not constitute visual approval.


## Company brief: judgments before metadata

Company overview now renders the selected recorded report’s actual judgments immediately, preserving original wording and status. Compact company heading; author, revision, report date and source identity in the right context rail. Subsequent judgments expand with a 200ms height transition within the reading region; reduced motion switches immediately. Archive is disclosure-only; full report and evidence links remain. Explicitly not a newly generated recent-performance brief. Dedicated company_brief CSS/JS avoids changing other workspaces. Browser visual review pending.


## 2026-09-20 批阅交互收尾

沿用正文、段落操作条和修订历史；操作为采纳／拒绝／编辑。淡绿 #e8f4eb 表示采纳，淡红 #fbe9e7 表示拒绝，保留文字按钮及按下状态。两种决定均计入已批阅（n/N），全部处理后为已完成批阅。旧撤销记录不算拒绝。编辑复用新候选和差异记录，变更块的决定失效。引用点击只展示记录中的摘录，可点外部、关闭按钮或 Escape 关闭，不加载整篇文档；保留主动打开来源入口。浏览器策略校验不可用，实际视觉验收待用户反馈。

## 2026-09-22：合并重复的研究导航

问题：公司根路径和 `/reports` 都展示同一套报告阅读、编辑与证据界面，却分别标为“研究详情”和“分析报告”。

视觉计划：复用现有公司导航及三栏阅读布局，左对齐保留“分析报告 / Reports、原始材料 / Materials、结构化数据 / Structured data”三个入口。沿用背景 #FAF8F4、表面 #FFFFFF、主文字 #26231F、次级文字 #6B655D、边线 #E5E0D7、强调色 #A45E3C；控件使用 PingFang SC / 系统无衬线，标题沿用 Songti SC 回退及当前字号，不新增视觉样式。

流程复核：研究者选择报告后直接阅读、批阅并核查来源；同一工作区不需要两个并列入口。旧公司根路径、报告深链接和筛选参数继续可用，统一高亮“分析报告”。公司名单、报告内容、证据、快照及采纳规则保持原样，无模型调用或部署。

验证：23 项既有报告 UI、主题、公司导航与深链接路由检查通过，`git diff --check` 通过。重启本地 8765 服务后，在 1231 × 994 浏览器视口截图检查中文和英文：只展示三个公司入口，报告列表、正文与来源栏位置稳定；旧公司根路径仍展示报告并将“分析报告”标为当前页。语言切换已恢复中文。此次没有改动 CSS；窄屏、触控板与减少动效未另做专项复核。

## 2026-09-22：提取产物可视化

视觉计划：在当前对话展示真实实验候选，左对齐以“财务表 → 管理层指引 → Q&A 构成”组织首屏。财务值保留期间与百万美元单位，指引并列金额与条件，投资构成使用一条约 60/40 的分配条；点击展开逐条记录、原话、限定条件及分析师问题。两组 prompt 和两次重复可切换，另设变化对照。产品基准仍为背景 #FAF8F4、表面 #FFFFFF、文字 #26231F、次级 #6B655D、边线 #E5E0D7、强调 #A45E3C；本次为对话内数据展示，使用宿主对应主题 token 与系统字体，保留紧凑层次和双语标签。

流程复核：主对象是已提取的记录，不设泛化评分或业绩仪表盘。默认改写组第一次，共 20 条记录，其中同一 CapEx 指引的 CEO/CFO 两次披露分别保留，不能解释为 20 个独立事实。ML compute 的“略高于一半”与总投资 60/40 分母分开；不将原始 value=50 显示为精确预测。基础组为新建的同 schema 对照，不标作历史解析器。中文标签是展示释义，英文原话保持不变。保留来源索引与候选状态，不改动产品快照或采纳规则，不发起模型调用或部署。

实现与检查：由 `scripts/build_extraction_visualization.py` 读取冻结的 12 份输出及 3 个来源包生成展示，逐一检查证据/限定是来源原文子串、问题引用存在，并记录输入与模板 hash。默认 20 条；基础版两次分别 23/22 条；改写版两次均 20 条。全量 85 是跨运行记录次数，不作为独立事实总数展示。浏览器验证 4 个组别/重复组合、前后变化切换、原始记录与单位证据展开，无页面脚本异常。财务表调整为期间逐行，320/360px 窄屏不需横向滚动；780px 桌面、320px 手机、浅色/深色截图已实际查看，原文可读，无内容遮挡，未加入动效。使用临时独立 Chrome 与本地预览，无账号访问。此检查不表示研究候选已经被采纳。

## 2026-09-22：实际查询、数据库明细和逐行溯源

视觉计划：沿用公司导航和结构化数据入口。查询页面以“问题选择 / 执行版本 → 返回值 → SQL 与对应返回行”组织；数据库页面以可筛选、原生横向滚动的工作表为主，固定表头、行号和处理过程入口，逐行展开来源、解析表格、抽取与规范化字段。Schema、信息损耗和新增数据更新方式在同页可达。原文不翻译改写，界面标签双语；沿用 #FAF8F4 / #FFFFFF / #26231F / #6B655D / #E5E0D7 / #A45E3C，系统/PingFang 正文与控件、宋体/Georgia 标题。

流程复核：研究者需要知道“这行是什么、哪里来、如何变化、是否完整”，因此展示真实表和字段对照，不新增评分图或装饰性统计卡。不会默认选第一条记录冒充用户选择。37 行含重复披露，明确不是独立事实数；候选未采纳、未通过的历史用例、缺失 SQL 轨迹、未知期间和覆盖缺口都保留真实状态。登记文件显式绑定公司、运行和输入指纹。全程读取已有冻结产物，没有模型调用、数据库写入或部署。

验证：56 项聚焦测试通过，包含查询与对应行匹配、物理数值与 payload 一致、来源指纹、独立两家公司隔离、原文转义、旧快照不被覆盖及相关页面回归。离线重建验证保留历史输入并加入已有电话会材料后，旧快照文件不变且能继续读取。

浏览器实际检查：正常桌面截图查看 Q1 结果、SQL/参数、CapEx 条件、数据库表和收入原始表格；验证指标筛选、文本筛选、空状态、阈值 >50 的分母/语气、原始 scale=6、来源定位、字段对照、Schema 键盘展开，以及更新/损耗页内链接。中文/英文均检查并恢复中文。曾补做 380px 窄屏与横向滚动检查、未见页面级溢出；用户随后明确不需要手机/H5 验收，已恢复正常桌面并将“默认只按桌面验收”写入维护中的界面规范，今后不主动切换手机视口。上述验证不表示全文信息损耗已量化或候选已采纳。

## 2026-09-23：让每一步可由研究者核验

视觉计划：沿用公司数据工作区，新增只读「步骤验收 / Step walkthrough」。首屏解释本阶段输入、变化、边界；左侧窄步骤目录，右侧按「输入与条件 → 动作 → 实际返回 → 核对点」阅读。结果用表格、原文和计算式呈现，SQL、字段及指纹折叠展开。复用共享暖白/棕色 token、系统/PingFang 正文和宋体/Georgia 标题；不改公司名单，不增加指标仪表盘。桌面验收，原生滚动、键盘链接和 details 展开，无新动效。

流程复核：本次展示明确登记的离线脚本样例（年报及电话会），不是将来仅限年报的大问题验收。已有解析块和候选记录是输入，历史模型提取未重跑；真实六次决策和结束后的宿主打包分别展示。原文、表格、图片引用、候选值与计算结果不得混称结论。目录可用不等于正文已读，出处回读不计 Agent 阅读覆盖。区分返回状态、证据缺口和语义完整性，不以测试通过宣称研究完成。每个里程碑以后先提供这一验收入口再推进下一项。

实现：新增显式登记的只读步骤页面，检查 session、dataset、spec 和验证记录的指纹；不执行模型、SQL 或来源下载。原始工具结果与打包后证据分别展示，保留候选状态及 4 项证据缺口。加入独立合成公司/期间、错误登记、篡改产物、来源转义和不写入/不执行 SQL 的检查；600 项 Python、7 项 JavaScript 回归通过。没有改变冻结数据和历史运行。

桌面实际检查：输入范围、步骤切换、原文、图片引用、取数行与 CFO 限定条件/字段对照、解析表格展开均可达；修正固定导航遮住步骤标题的滚动位置。表格保留原始列和单元格合并，使用原生横向滚动；去除空白占位列的最小宽度，避免人为撑大。已查看中英文页面并通过 Enter 切换步骤，恢复中文。这些是用户调整验收方式前已经执行的检查，不再继续扩大视觉检查。

用户随后明确反馈页面 review 耗时过多。已更新 AGENTS.md 和项目界面 skill：以后默认核验数据结构、字段映射和代码逻辑，页面视觉 review 交用户；只有明确要求或具体浏览器问题才进行定点视觉检查。交付不以视觉验收为前提，不重复扩大自动检查。

## 2026-09-23：工作台代码与展示资源分离

本轮问题是页面、共享组件、CSS 和 JavaScript 混放，维护同一个研究页面时难以定位。可观察验收：原页面路由仍返回同样的公司/证据/引用与操作，修改样式和交互可分别在 `static/css/`、`static/js/` 定位。

视觉计划沿用既有公司优先、单窗口、触控板优先基线；背景 `#FAF8F4`、表面 `#FFFFFF`、文字 `#26231F`、次级文字 `#6B655D`、边线 `#E5E0D7`、强调色 `#A45E3C`，字体和间距沿用现有 tokens。对照研究工作流后，本轮仅整理实现位置，不重新设计版式或增加视觉状态。

- `pages/` 集中 13 个页面模块，`components/` 集中 5 个共享展示模块，`data/` 集中 2 个查询/导入辅助模块；HTTP 入口仍为 `app.py`。
- 现有独立资源迁入 `static/css/`、`static/js/`，原 Python 内 26 段样式/脚本抽为资源文件，按原次序嵌入输出。两个动态脚本用显式 JSON 占位注入，保留原转义。
- `assets.py` 只接受本地 CSS/JS 文件名；旧 Python imports 映射到相同模块对象，保留调用方和 mock/patch 行为。详见 `apps/review_workbench/README.md`。
- 定向验证覆盖 124 项 Python 页面、路由、引用、数据映射、电话会、工作台 readiness 和兼容边界；新增测试中一个大小写断言修正后单独重跑 3 项通过，其余 123 项首轮通过。7 项 JavaScript 交互检查、18 份脚本语法检查通过。
- 未进行浏览器/截图/视觉验收，未调用模型、部署或更改研究采纳状态。动态 HTML 仍由 Python 生成；模板引擎及服务器路由进一步拆分不在本轮范围。

## 2026-09-24：首页注意力结构稿

用户确认每家公司维护一份主报告，追踪记录和专题研究围绕它展开；首页先看已有判断的变化，再看新公司的研究机会。核心问题是：哪家公司值得看、发生了什么、原判断如何受到新证据支持或挑战、与持仓理由有什么关系。自主决策和委托经理的组合管理保留独立视角。

本轮输入为显式虚构的 6 家公司研究示例，身份取自已有公司名单；不改原名单或生产数据。输出为 `apps/attention_studio/` 独立可点击结构稿，使用共享 `static/css/design_tokens.css` 中的暖白/墨色/棕色与现有蓝色雨滴资产；不依赖 frontend-design skill。公司条与变化卡片在左侧，右侧固定阅读上下文；原生滚动，点击展开，中文/英文界面可切换，示例研究正文保留中文。

可观察验收路径：选择 Alphabet，角标初始为 2 条未读变化；点开云业务卡片后可在右栏看原判断与新信息、2 份明确标为虚构的证据、主报告因素及追踪任务，角标减少 1。留待复核和个人笔记是独立本机状态，不代表采纳或报告修订。Costco 提供无新变化但可读主报告的情况。经理视角可切换两份示例组合，查看持仓加现金、以百分点表示的仓位变化、计划/已执行动作，并进入同一公司的研究。

范围：没有连接实时新闻、真实持仓、收益计算或后台追踪；没有报告编辑、专题报告编辑和版本对照。本页不会触发模型、交易、生产写入或部署。已同意的 Logo 演示和 PDF 水印不受影响。

检查：13 项模型测试通过，覆盖独立合成公司、单一主报告、变化去重、已读/收藏独立、筛选/空状态、跨公司引用拒绝及组合含现金合计 100%；3 个运行模块语法检查通过，HTML 资源路径与 Logo 文件存在。源码审查修复了整页重绘丢失未保存笔记的问题，草稿按变化 ID 在当前会话内保留，显式保存后写入独立的本机命名空间。预览 HTML 和 JavaScript HTTP 200、模块 MIME 正确。未进行浏览器交互/截图/视觉验收，未将这些检查视为真实投研能力验收。

## 2026-09-25：从零重做固定单屏工作台

用户否定上一版，要求放弃既有实现的路径依赖，随后明确：一屏内完成主要浏览；左列表选对象，右侧标签切内容；公司与组合是两个工作区；同级条目支持点击和达到阈值后的吸附翻屏。此次不沿用上一版两栏卡片队列或既有配色，也不使用 frontend-design skill。

输入为全新编写、显式虚构的六家公司与两份委托组合；输出为独立 `apps/uteki_zero/`。原型只引用目录内自己的 HTML/CSS/ES modules 和用户原始 JPEG 的副本。视觉采用白底、浅灰蓝画布、蓝色文字与小范围语义色；固定品牌栏、对象列表、内容标签和阅读画布。公司标签为总览/变化/主报告/追踪，组合标签为总览/持仓/动作/表现。经理是组合属性，持仓来源不与自主研究混合。

可观察验收：在 Alphabet 总览上滚动达到阈值后切到相邻公司；在变化页切换同公司的两条变化；标签区滑动只切标签，工作区选择区滑动只切公司/组合视角。点击、前后按钮、圆点和区域方向键提供同样入口。工作区和对象分别记住位置。每个区域的 pager 跨重绘保留，整段惯性最多翻一页；翻屏 360ms，响应 reduced-motion。报告按章节、任务按因素逐页展示；持仓含义和证据进入独立阅读屏，避免把全部字段堆成长页。

15 项滚动手势单元测试通过，覆盖阈值、停顿、惯性、边界、方向反转、滚轮单位、Ctrl 缩放和区域隔离；运行模块语法检查通过，预览 HTML/JS HTTP 200。源码复核发现并修复两项行为错误：画布重绘后丢失键盘焦点；正文阅读的滚动余波在末尾转成翻屏。

针对上述两项浏览器相关错误进行了定点核对，没有截图或多视口视觉评审：正常的 643 × 852 应用内浏览器中，连续两次方向键从 Alphabet 到 NVIDIA，焦点仍在画布；一次较长滚动只到相邻 Costco；长正文滚动到末尾后保留当前变化，停顿后的新手势才翻到第二条。随后将较长解释移入独立阅读屏，NVIDIA 变化页内容高度与画布高度均为 578px，文档高度等于窗口高度 852px。此为布局/交互检查，不表示美感已被用户认可。其他内容在极小窗口或缩放下仍有内部阅读兜底。

本轮没有连接真实研究、账户、后台追踪或收益计算，不触发模型或交易；没有修改旧首页、原公司名单、Logo 封版和水印 PDF。完整公司搜索、关注管理及全局复核队列留在后续范围。


## 2026-09-28：纠正 NVIDIA 公司标识

用户指出新单屏原型的英伟达标识不正确。核查发现原型没有接入公司 Logo 素材库：英伟达使用绿色 N 占位，Alphabet 与 Microsoft 为 CSS 近似图形，其余三家公司为首字母。

本轮以 NVIDIA 官方新闻中心提供的完整彩色 PNG 替换 N。保留原始文件、品牌颜色、图形与字标比例，使用本地资产和 object-fit: contain；沿用已有标识槽位，在公司列表、标题和持仓条目共享同一渲染函数。公司名单、研究示例和交互状态保持既有行为。素材页面、下载 URL、日期与 SHA-256 记录在 apps/uteki_zero/assets/companies/SOURCES.md，其他公司的标识明确列为待替换占位。未使用 frontend-design skill。

验收：两个修改模块的 JavaScript 语法检查通过；确认 NVIDIA 数据映射到有效 1920 × 1607 PNG，且不再带 N 占位；本地预览素材返回 HTTP 200 / image/png，响应内容哈希与磁盘文件一致。已查看下载原图，未进行浏览器视觉验收。后续统一核实并替换其他公司的官方素材。


## 2026-09-29：统一公司标识与域名注册表

用户要求修复全部公司，并进一步明确未来公司也需要泛化接入。输入是显式公司官网域名与来源可核实的原始图像；验收是同一机制按域名匹配任意新增公司，缺失不误配，失败不破坏已有素材。沿用单屏结构，使用较宽的统一标识槽位保留完整横向字标，以 contain 展示。没有使用 frontend-design skill。

当前六家公司均已接入核实的官方本地图片，Alphabet 使用母公司字标；Costco、Arista、Eaton 不再使用首字母。列表、标题和持仓共用 brands.mjs 与 registry.json，移除了 Google/Microsoft 的 CSS 近似图形及按公司名称分支。原图、地域来源、URL 和哈希保留；未改变公司名单或研究数据。缺失与图片错误使用中性公司图标。

通用导入器以调用者提供的 HTTPS 官网 origin 为输入，自动发现官网 icon，或导入显式指定的已核实原图。官网图标与已核实 Logo 分开标记；发现失败不覆写旧记录，自动流程不降级已审核图像。不依赖在线 Logo API，页面只读本地素材。生产新增公司后台尚未接入，不能将 CLI 接口视为完整新增公司功能。

检查：7 项品牌域名/来源/路径解析测试、14 项导入器离线测试通过；修改的 JS 语法通过。全部六家公司域名解析、文件存在和 SHA-256 一致性核验通过。名单外 Apple 官网实际自动获取 favicon，写入临时注册表，未加入页面公司名单。没有浏览器视觉验收。用户进一步要求的 TradingView/其他来源比较与批量管线已拆为独立后台任务，批量覆盖尚未声称完成。


## 2026-09-29：按用户截图纠正为 icon

用户明确需要 TradingView 列表中的 icon 类型，而非完整横向字标。新验收是圆形固定槽位、紧凑图形、公司名另列；此规则适用于未来公司的批量获取。继续应用 uteki-interface 基线并将该反馈写入其风格指南，不使用 frontend-design skill。

当前六家公司使用各自 TradingView 证券页面实际引用的 600 × 600 PNG，逐张查看原图并核对证券身份；保留图像本身的背景与留白，仅在容器边缘使用圆形遮罩。列表 32px、标题 42px、持仓 28px，窄侧栏 26px。Alphabet 的 G 是该证券页采用的图形；Costco、Arista、Eaton 保留供应商紧凑图标中的品牌文字。来源标记为 TradingView，不能描述为本轮直接获取的官方媒体图。旧官方完整字标与来源保存在 wordmarks.json。

注册表新增 presentation，渲染只接受 icon；wordmark 和未分类旧资产不进入图标槽位。导入器自动发现标记 icon，手动输入默认 wordmark，需显式选择 icon 并通过基础宽高比校验；该校验不代表品牌正确性。图标要求写入 tools/ICON_REQUIREMENTS.md 和 README，作为独立批量任务后续接入的约束。

检查：8 项 JS 映射/来源/图标与字标隔离测试通过；21 项导入器离线测试通过。六份本地图像均为 600 × 600，哈希与注册表一致；本地 HTTP 注册表及六份图标均加载成功。查看的是素材原图，没有进行浏览器视觉验收；跨公司批量覆盖继续是独立任务，不能用这六项成功替代。


## 2026-09-29：Logo Studio 墨滴与明暗切换

用户确认水墨概念稿后要求在 8767 原动效展示页增加水墨材质、亮暗主题，并解释技术演进。沿用现有控制和固定轮廓工作流；新增第三个墨滴材质、亮色宣纸/暗色夜墨按钮，未采用 frontend-design skill。输入为已认可的生成图原文件；展示以 CSS 裁区和 WebGL 单色叠层实现，不覆盖旧 Logo 或封版。

可观察验收入口：`http://127.0.0.1:8767/?material=ink&view=slide&theme=light`；选暗色后整页变为炭黑/银墨，播放时间不重置。主题本机保存，参数链接可直接选中材质/动效/主题。水墨 Shader 以 12 秒周期推进沿瓣色场，固定原图采样；不是新宣称的真实液体、纸面渗透或 WebGPU 模拟。

25 项控制器行为检查及脚本语法通过；覆盖新材质双向切换、失败回退、主题/暂停独立、减少动态、参数链接以及原颜色 renderer / V1 哈希。8767 页面、JS、新 PNG HTTP 200。没有执行浏览器视觉评审或真实 GPU 编译检查。技术研究使用 MDN、Three.js 与 NVIDIA 一手资料，摘要位于 apps/logo_studio/MOTION_TECH.md。

## 2026-09-29：落墨成形入场实验

用户希望墨滴冲入水中、晕开后恢复 Logo。输入沿用已认可的三套原图，新增独立「落墨成形」选项；控制区调整为两行两列。设计为一次约 6.8 秒的下落、晕散、聚拢、停稳，完成后直接显示原图，字标在后段淡入。接受示例：打开 `?material=ink&view=impact&theme=light`，播放一次后停住，点击重播再次开始；明暗主题均适用。未使用 frontend-design skill。

实现为 WebGL 程序化墨团与恢复原图的采样变换，是艺术化模拟，不是真实流体求解。画布四周增加 30% 空间承接晕散；仅播放入场时临时覆盖静态雨滴，失败、强度归零与完成后恢复原图。减少动态需手动播放，后台暂停不跳时。共享 canvas 保持 alpha 支持，原蓝色两个 renderer 和 V1 封版不改动。

28 项控制器测试及修改脚本语法通过，覆盖完成停帧、原图恢复、重播、减少动态、暂停/主题保持、失败回退和切回旧效果的尺寸恢复。测试使用模拟 renderer，未进行真实 GPU 编译或浏览器审美验收；视觉节奏与墨团效果仍由用户预览评价。

## 2026-09-29：按认可的黑蓝分镜重做入场

用户否定上方噪声墨团实验，明确认可随后生成的黑、蓝两张三阶段分镜，并要求开始实现。目标改为保留分镜的细墨丝、半透明卷边与双瓣流向。新增原画完整副本至 `apps/logo_studio/assets/motion/`；重做原 impact 选项为「入水成形」，旧颜色/纹理滑动及 V1 封版保持不变。未使用 frontend-design skill。

输出是原画驱动的 10 秒 2.5D WebGL 动效：入水纹理由上而下显露，双瓣附近做小范围局部流动，外围丝缕逐渐收束，再沿空间遮罩过渡到固定原图。末段字标淡入，单次结束停住。不是视频生成、光流重建或真实三维流体。亮色为认可分镜对应的主方向；暗色沿用旧主题反相，并未另行绘制暗色原画。素材按首次选择的颜色加载，失败保持此前画面且可重试。

画面下方增加可拖动进度、就地播放/暂停/重播；拖动暂停并保留阶段文字。右侧可查看完整分镜，便于对照视觉目标。34 项控制器测试通过，覆盖异步素材匹配、失败重试、进度边界、旧 renderer 恢复和封版哈希，脚本语法通过。针对已反馈的视觉失败，仅在当前浏览器定点看水墨入水/舒展/成形和蓝色舒展帧，实际 Shader 已编译绘制，未记录 warn/error；修复了过渡中原图纸底矩形提前显露，并让外围墨丝收束。没有多视口回归或宣称用户已认可连续动效。

### 按“保留四秒舒展，改善组成感”修订

用户认可约 4 秒的画面，指出后段仍是生硬切换。保持前 5.5 秒，后段改为原画纹理随网格向目标 Logo 的颜料分布移动。双向累计密度映射采用平滑和背景约束，保持有序、防止网格翻折；拉伸稀释在共享顶点平滑，避免宽灰雾和三角形明暗接缝。约 8.65 秒先完成轮廓与留白收束，再过渡到原始材质，最后显示原图。黑蓝共享机制，所选原图决定目标。

41 项检查通过，含新增 7 项几何映射检查。针对衔接反馈，在当前浏览器定点查看四秒和聚拢中的水墨/蓝色画面，修复逐行锯齿、拉伸灰雾；实际新 Shader 编译绘制，切回旧颜色流动再进入新动画正常，最终检查窗口没有新增 warn/error。早期热加载未完成代码导致的 `rebuildFormation` 缺失已恢复。仍为 2.5D 几何运输，连续观感由用户评价；无新原画生成、无封版覆盖、无发布。

### 本轮取舍：停止成形动效探索，回到工作台

用户最终反馈整体仍不连贯、像幻灯片，明确表示原始静态 Logo 与颜色变化已满足需要，重点转回网页产品。成形实验没有通过用户审美验收，暂不继续投入，也不把它作为工作台的品牌入场效果。保留实验文件与已认可分镜供参考，品牌应用沿用原始静态标识和已认可的变色方向。后续优先推进公司变化、判断与证据的阅读交互，以及独立的组合/经理维度。

## 2026-09-29：取消工作台滑动切换

用户明确反馈滑动切换不自然，要求取消。可观察目标：在工作区、公司／组合列表、内容标签或正文上滚动，当前选择都不变化；长内容正常滚动，到边界也不翻页。页面保留点击按钮、页码圆点和方向键导航，沿用现有单屏布局。

`apps/uteki_zero/zero.mjs` 移除滚轮监听、惯性状态和手势模块导入；导航区域改用 `data-nav`，保留焦点恢复及笔记编辑行为。中英文提示、ARIA、README 和界面规范同步调整。旧手势模块与测试仅作为未加载的历史实验保留。未使用 frontend-design skill。

模块语法与改动格式检查通过。本机 8768 预览服务返回 200，确认提供无滚轮监听的新版脚本。临时 Node DOM 模拟加载真实页面模块和示例数据，检查无滚轮／触摸导航注册、点击公司／组合／标签／前后项／页码、方向键与焦点恢复、笔记编辑键不被拦截，以及正文溢出时保留 `overflowY: auto`，均通过。未打开浏览器或进行视觉验收；模拟检查不代表真实浏览器滚动与动画观感。

## 2026-09-30：报告工作区与双主题改版计划

依据前后台工作区草案制定 [网页改版计划](design/UTEKI_WEB_REDESIGN_PLAN_v1.zh-CN.md)。用户确认统一规划前后台、分期交付完整交互原型，增加适合长时间阅读的排版、减少堆叠、日间／夜间切换，并调研 GitHub UI skills。本轮只新增计划，没有更改网页或安装 skill。

方案以公司＋Manager＋正式版本的完整连续报告为核心，先打通报告、比较、证据返回，再扩展注意事项、Manager／行业与工程诊断链。恢复上次阅读、证据占用当前阅读区是未答问题的可调整默认方案，不作为已确认偏好。视觉起始值采用 17px 正文、1.85 行高、720px 阅读宽度和独立日夜配色；移除整屏推移和报告强制分页列入后续实施，不描述为已完成。

GitHub 调研核对了 Vercel Web Design Guidelines 规则、UI UX Pro Max 技能及检索入口源码；计划分别用于质量审核和专项设计参考，不依赖 frontend-design。计划本地链接和格式通过，候选文字配色在对应背景上的最低计算对比度日间 5.64:1、夜间 7.97:1。独立只读审查未发现范围、默认值或假成功承诺问题；未执行 UI 测试和浏览器视觉验收。

## 2026-09-29：Agent 契约与前后台功能设计

用户明确本阶段不使用 `frontend-design`，重点是功能、核心交互和注意力管理，并要求独立提出取舍。已按此调整设计范围；沿用公司主入口、双视角同一案例、点击导航和原生阅读滚动，仅产出功能文档与文字线框。未制作样式或新页面。

产物见 [设计入口](design/README.md)、[Agent 任务契约](design/UTEKI_AGENT_CONTRACTS_v1.zh-CN.md)和[前后台交互稿](design/UTEKI_WORKSPACES_v1.zh-CN.md)。首版提案：首次阅读先定位业务与 thesis，回访突出判断变化；后台优先异常与待审事项，按案例、任务、运行、产物逐层诊断。用户正式证据和实质缺口保持可见，过程产物留在内部；用户账户仅展示比例及归一化表现。新路由、发布投影和按 Skill 模型路由均未实现。

验收例子：同一事项的重复更新合并提醒；风险已读仍未解决；新更新不抢阅读焦点；候选修订保留旧版本；发布预览保留业务缺口、排除内部过程。已核对相关模型/Skill/封存代码边界、18 个本地文档链接、代码围栏和空白格式。属于设计与静态核对，没有运行投研模型、应用测试或浏览器交互验收。持久化恢复与局部动态 UI 只列为有一手依据的实验选项，未作框架迁移决定。

### 后续澄清：报告是核心交付

用户明确希望减少与 Agent 的交互，核心交付为报告。据此将动态 UI 移出当前方案；公司与 Manager 两个入口提供完整正式报告，比较、引文和变化摘要读取固定发布产物。新的解释性结论先经内部研究与审阅，不在用户阅读时临时生成。内部 Agent 的分工继续服务于报告生产；下一步先明确报告交付标准，再反推 Agent 任务契约。本次只同步设计文档，没有修改页面或执行模型。

## 2026-09-30：按逐项问答确认报告交付边界

已确认五条规则并记录于 [设计入口](design/README.md)：首次研究与审阅完成后才发布，此前显示研究中；重要新证据出现时保留旧报告并标注待复核、受影响部分和截止；共同必答问题下允许 Manager 灵活论证；公司报告回答是否买，组合报告回答买多少；质量问题必须处理，预测与风险取舍分歧由 Manager 回应并负责，可保留分歧发布。同步纠正了旧草案中有限研究先发布、公司报告直接包含目标权重、重要质疑一律阻断发布的表述。

本次仅更新设计文档，规则不代表生产接口或页面已实现；八部分报告组织、具体审阅方式和技术方案继续保留为提案。需求澄清继续一次一个问题，用户同意推进不代表全部细节已确认。

### 后续问答：独立审阅与首次资料准备

已进一步确认完整审阅先独立初判、再读作者报告，按实质变化决定完整或局部审阅。基础资料持续维护并按需补采，采集与内部研究并行，首份报告发布前仍需必需资料、核心研究和审阅完成。用户倾向 5 年/8 季度目标，尚未作为已生效配置；实际公开历史不足可以研究，但获取失败不能当成历史不存在。后台相应区分未公开、获取/解析失败、已可读及覆盖状态，前台首次研究期间不展示过程产物。本次仅同步文档，未改动页面、采集程序或模型运行。

### 后续问答：核心财务包、共享核验与批量选项

用户要求后续所有待确认问题使用选项交互以加快推进，替代上文的一次一题方式；当前按相关主题每批 3～4 张可点击选项卡推进，已确认内容不重复询问。完整待确认范围及先后顺序归入 [设计入口](design/README.md)，技术调查与产品取舍分开。

已确认保留原始资料及索引，先整理附期间、口径和原文的核心财务包，其他按需补充；按需取得的新事实核验后进入共享数据底座，Manager 观点与采纳仍独立。全部结构化数据先做程序检查，模型提取、口径转换及影响核心判断的数据增加内容核验，通过后用于正式分析。数据核验状态不等同研究报告审阅状态，工程后台应能区分；本轮仅同步设计契约，未改动页面或运行模型。

### 补充前台与后台的使用者视角

用户追问前后台是否已有具体 UI/交互设计。本次核对既有功能稿，明确其交付程度为页面职责、信息排序、动作反馈、状态及两份文字线框，尚无对应的可点击交互原型或生产隔离。沿用 uteki-interface 功能基线，未使用 frontend-design。

在 [前后台交互稿](design/UTEKI_WORKSPACES_v1.zh-CN.md) 增加两种使用者视角的并列表，并将最新已确认的数据规则映射到后台 E1：资料覆盖、核心财务包、分层核验、按需补充与共享。前台的报告状态和投资影响，与后台的任务/数据/核验状态分别表达；模块的具体排列和操作权限仍为提案。本次只补充文档，没有新增页面、调用模型或进行浏览器检查。

## 2026-09-30：Figma 功能交互稿（部分交付）

用户显式选择 Figma 制作设计稿。使用 figma-create-new-file、figma-use、figma-generate-design 及必要的局部组件能力，沿用 uteki-interface 的功能边界，未使用 frontend-design。新建 [设计文件](https://www.figma.com/design/0SogEfR3y4xLDl9YB5RbOQ)，前台 10 屏、后台 9 屏、阅读指南及组件已填入可编辑文字和 Auto Layout；点击目标与滚动容器已设置。中文采用可用的 Noto Sans SC，样例明确标注全部财务数字、摘录与判断为虚构。

创建中修复了远端组件临时节点 ID 失效和同屏 NAVIGATE 被拒绝问题；改为每次通过 library key 引入，并跳过当前屏导航。创建结果返回结构证据，但内容审阅发现阶段性 Manager 的组合/历史路由会进入长期视图、后台 Manager 归属不清、待复核画面缺完整旧版，尚待修正。

追加 U11/U12 空框架后 Figma 明确返回 Starter MCP 调用额度耗尽，后续读取及修改受阻。再次查询账户确认当前为 Starter / Full seat；不推断恢复时间。修正脚本、实际节点 ID、已知缺口与续接说明保存到 [Figma 交付目录](design/figma/uteki-v1/README.md)。没有将未执行脚本描述为已生效，没有运行模型或发布应用，也未执行截图/浏览器视觉验收。当前稿不能标为完整交付。

## 2026-09-30：第 1 阶段报告阅读样板

用户批准改版计划后，在 `apps/uteki_zero/` 同一路径实施完整报告阅读。沿用 uteki-interface 与已制定视觉计划，不使用 frontend-design。原 `index.html` 另存 `legacy.html`，原 `zero.*` 与旧状态键不改动；公司列表仍为原六家，沿用本地 TradingView icon 和原始静态雨滴素材。

本轮可观察示例：Alphabet / North / v2 从目录进入正文，点引用后在主阅读区看证据，返回原段落和焦点；两位 Manager 的 v1/v2 可并排独立滚动，右栏引用保持自己的身份和版本。Microsoft 的另一位 Manager 未发布，North 的一条原文不可用，均显示明确缺口。五份报告、证据、日期、Manager 和发布身份全部是命名演示资料；无真实研究、价格、模型调用、交易或发布。

视觉采用连续纸面阅读区、细分隔和留白，主正文默认 17px / 1.85、约 720px 宽；日间冷灰与蓝色强调，夜间独立炭灰配色。支持跟随系统、双主题、16/17/18px、双语界面；中文原文保留并标明语言。取消报告强制分页、整屏推移与方向键导航，滚动只阅读。旧版待复核保留全文、截止与可定位章节；本机已读状态不改变 unresolved。

显式 hash 路由包含公司、Manager、版本、视图与比较两侧；错误对象不回退到示例或另一家公司。正文引用与事后事件引用分别检查所属版本，刷新和历史导航保留阅读位置；本机写入失败保留当前页状态、提示尚未保存并允许重试。主题脚本先于样式加载，以减少错误主题首帧；其实际浏览器表现未作验证。

检查：56 项相关自动检查通过，覆盖命名数据、状态、模型、渲染、本地图标及控制器；以 Node VM 模拟 DOM/history 执行真实控制器，不等同浏览器布局测试。校验日夜主文字、次文字、链接在纸面、背景、选中、hover、soft 底色上的最低计算对比度分别为 5.20:1 与 6.02:1；警示文字与警示底色分别为 5.52:1 与 7.54:1。原 8768 服务已停止，本轮重新启动仅监听 localhost 的预览服务，主页面、新模块、样式、图标注册表和旧版入口返回 HTTP 200。未打开浏览器、截图或声明美感通过；下一步由用户查看样板，再进入计划第 2 阶段。

## 2026-09-30：按公司／Manager 双入口重组报告目录

用户指出此前公司选择直接绑定一位 Manager 与报告，缺少对象目录层；确认公司与 Manager 多对多、报告唯一属于一个公司和一个 Manager。本轮采用已推荐的主报告＋专题报告，各自版本独立。首个可观察变化：左侧选 Alphabet，右侧同时展示 North 与 Field 的研究分组；切换 Manager 并选择 North，右侧按公司组织同一批报告，云专题与主报告分别可读。

目录使用标题、一句话判断、日期、状态与细分隔；报告份数不把版本重复计数。保留六家公司及本地图标、原始静态品牌、阅读字号与明暗配色。点击明确报告才进入正文，两种入口共用 reportId 与已读状态，返回恢复目录筛选、原行焦点与滚动位置。比较右栏证据时，证据作者与左侧入口对象分别保存，不误切 Manager；滚动和方向键仍使用浏览器原生行为。未使用 frontend-design，也未执行浏览器视觉验收。

新增命名目录 `catalog.mjs`：5 份独立报告、8 个正文版本、9 条证据、5 个事件、12 个覆盖关系。三份主报告保留原版本全文与截止，两个新专题明确为虚构演示。同事件影响主报告与专题时只计一次；未知或冲突的公司、作者、报告、版本与入口对象均明确失败。Manager 组合与表现独立设置入口，本轮没有接入持仓／动作／收益数据，页面明确展示这一缺口。

新工作区使用 `uteki.workspace-prototype.v3`；只有显示偏好从 v2 继承，不把旧 case 状态扩散到多份报告。原第 1 阶段页面及控制器保存在 `reader-v1.html` / `reader-v1.mjs`，早期 `legacy.html` 保留。旧 case URL 使用命名映射转换为原主报告和原版本，不替未知对象挑默认报告。

验证：60 项聚焦检查通过，覆盖目录数据、独立合成的多公司／三 Manager 范围、双入口路由、报告和证据归属、生成链接、真实控制器的 DOM/history 模拟、位置与焦点恢复、已读隔离、存储失败及图标映射；脚本语法、HTML 资源和文档链接检查通过。测试不是浏览器布局或触控验收。8768 当前本地预览入口与新模块返回 HTTP 200，未部署或运行模型。下一步先由用户检查双入口结构，再推进 Manager 的真实组合与表现及后续页面。

## 2026-10-04：真实抽取运行的只读验收入口

新增独立 `/extractions`，复用工作台主题、双语、表格和手动折叠阅读组件。上方按公司／材料筛选登记运行；选中后先展示状态、草稿数量、规范化数量及缺失产物，再阅读任务、版本化提示词、实际系统提示词、输入块、原始草稿、规范化结果、数据库实际 payload、引用上下文和独立 Codex review。修订通过显式父运行关联，不以新旧文件日期猜测。原公司名单、材料目录和 `/evaluation` 行为不变。

只读取显式登记及 SHA256 固定的产物，拒绝 URL 文件路径和跨公司／来源拼接。原始失败运行保留缺失状态；候选与完整性核验不等于语义通过或采纳。页面默认空注册，不制造运行；原文快照尚未包含在运行中时标明仅核验 packet 引用。自动验证覆盖空状态、失败产物、HTML 转义、哈希与路径边界、公司隔离、数据库 payload 不一致和 review 归属；8 项聚焦测试及 9 项既有评估页检查通过；未入库草稿也保留引用上下文与 quote 未找到的状态。未调用模型，未打开浏览器或截图，未声明视觉验收。


## 2026-10-04：瑞士风格独立试稿 A

用户在调研后明确授权复制前台，制作一个可以比较的瑞士风格版本。本轮只新增 [Swiss study A](design/company-workspace-swiss/index.html)，原 `company-workspace-v2` 的复制基线 37 个文件哈希保持不变。本稿是探索，不代表风格已被采纳。依据本轮工作约定阅读 frontend-design 与 uteki-interface；具体 token 与工作流复核记录在 [VISUAL_PLAN](design/company-workspace-swiss/VISUAL_PLAN.md)。

视觉集中在网格对齐、清楚字级、等宽数字、紧凑页眉、连续纸面与结构分隔：机构首页保留曲线上方比较与下方手动组合，研究页保留索引加正文，Manager 表格与关注阶段有一致基线。Helvetica Neue / Arial 与中文系统字体配白纸、深色文字及清楚的蓝色交互；明快图表色卡、原雨滴与公司 icon 保留，暗色有独立变量。顶部原版入口保持当前路由。

业务模型、字段、公司名单、报告正文及版本、持仓、收益、事件几何与全部原交互均沿用副本，模拟身份与日期不删减。仅新增样式及一个比较链接，未重做待讨论的持仓图逻辑。89 项既有机构渲染、Manager 渲染及控制器检查通过，新增渲染语法、HTML 静态资源和本地模块路径检查通过；自动检查不是美感验收。子任务没有打开浏览器，视觉比较由主任务和用户进行。无模型调用、真实账户接入或部署。

## 2026-10-04：瑞士风格独立试稿 B

用户要求后台 Agent 继续制作瑞士风格试稿。本轮复制当前 v2 到 [company-workspace-swiss-b](design/company-workspace-swiss-b/index.html)，保留 v2 与 A；两者合计 92 个文件哈希核对未变。阅读并应用 frontend-design、uteki-interface 与最新机构首页约定，具体方案与工作流复核见 [B 的 README](design/company-workspace-swiss-b/README.md)。

B 重点降低标题和装饰分隔的视觉重量：22–23px 实体标题、16–19px 区块层级、24px 统一页面基线、等宽数字、固定占比列、薄线区分持仓与配置图；控件保留小圆角。机构页仍无无效中栏，公司和 Manager 保留既有对象索引与更大内容区域，长报告仍按 17px / 1.85 阅读。鲜明分类色、真实品牌 icon、原透明雨滴、亮暗主题、模拟标签和来源说明不变。

仅新增独立样式、同路由原版对照入口，以及 B 专属显示偏好键。公司名单、实体关系、报告版本、收益/持仓样本、线上 Buy/Sell、下方报告事件、事件浮层、手动 Agent 切换、历史展开和报告返回沿用原行为；百分比条保留原比例语义，没有按当前样本最大值归一化。

89 项既有机构/Manager 渲染与控制器检查通过，脚本语法及 82 条本地模块和 HTML 资源引用通过。检查为静态和 DOM 模拟，未运行浏览器或截图，未声明视觉通过；样式的最终美感由用户比较。未接入模型、账户或部署；本稿也未重做持仓历史的图形逻辑。

## 2026-10-04：真实财务事实矩阵与原表追溯

本轮主对象是显式选择的「公司数据包 → 材料 → 提取运行 → 候选事实」。复用 `/evaluation` 的对象目录、标签、原件隔离阅读和原文块组件，以及 `/extractions` 的冻结产物读取；公司名单不变，不另建后台平台。材料页并列表达原始材料、原文检索底座、财务事实、财报精编四层状态。精编明确显示「未生成」，解析块不充当精编报告；本轮没有实现精编阅读器。

紧凑方案先按现有工作流复核：查看财报数据应直接读数并回到原表，因此采用指标行 × 实际期间列，不把 JSON 折叠项当作主要体验。保留既有页面 token 和系统字体：纸面 `#faf8f4`、表面 `#ffffff`、主文字 `#26231f`、次文字 `#6b655d`、分隔 `#e5e0d7`、焦点蓝 `#355d9f`。表格数值右对齐、等宽数字；指标列与期间表头固定，正文原生滚动，全部选择依靠点击。不添加动效、主题或另一套视觉规范。

财务事实页先列出已登记运行，要求显式选择，不静默使用 latest。模型原文候选（reported draft）与单位转换后的规范化候选分成两张矩阵；数据库 payload 是否可核对另行显示。按实体、指标、币种/单位、会计口径、维度和数值性质区分行，实际期间区分列；重复候选保留为单元格内的多个链接，不相加、不覆盖。精确小数字符串保留，不经浮点数转换。

点击数字进入同一页的候选详情，显示原始字段、期间、单位、规范化前草稿、该 draft 的 unresolved、明确对应的独立核验及原文表格；可定位原文结构，再返回原 dataset/source/run/fact。未入库草稿和无完整草稿的失败运行都可查看，run 级未解决项和模型覆盖缺口另外保留。程序检查、数据库一致性和内容审核分别表达；「金额/期间核对匹配」「需补证据」「未核验」不改写成财务语义通过或已采纳。

运行与数据包只通过明确登记的 dataset ID + manifest SHA256、company ID、source ID、source SHA256 关联，打开时另查原文块哈希。缺少绑定不推测对应关系，其他公司和来源不作为回退。逐条审核仅认可带明确运行/公司/来源身份及对应 draft_id/record_id 的 facts 条目，不将总体 verdict 扩散到每条数据。每次矩阵注明实际输入块数量及选取范围，局部表格运行不冒充全文完成。

检查：37 项聚焦自动检查通过，覆盖合成多公司/多期间、精确小数、不同实体/币种/口径不混合、重复单元格、零规范化但保留草稿、缺失产物、错误引文、候选与原表往返、身份/哈希绑定及逐条审核隔离。另直接用已冻结 AMD v3 两次真实运行检查页面生成与失败状态；未调用模型、未修改原始运行或登记、未打开浏览器或截图，未声称视觉验收。服务重启与 HTTP 检查由主任务统一完成；后续接入精编阅读器前先确认精编产物契约。

本轮独立审核补充：事实矩阵下方直接显示 coverage_findings 的可读结论，以及 verdict 为 incorrect / insufficient 等的关系问题；每条保留原文块入口与字段展开。逐条金额匹配与本次范围完整性分别呈现，不能用已匹配数字掩盖比较年度遗漏或错误目标引用。新增覆盖/负向关系可见性检查，12 项矩阵聚焦测试通过。

服务由主任务统一重启后，完成 16 项本地 HTTP/DOM 内容验收，全部通过：四层产物状态、真实单表批次的 16 条草稿与 9 条数据库候选、reported/normalized 单元格的值/单位/实际期间/审核、两类候选到原表并返回、旧 35/0 与失败 0/0、TSMC 无运行、跨公司/来源/未知候选和错误层级拒绝、实际系统提示词完整保存内容、可读覆盖与负向关系。登记文件检查前后 SHA256 一致。记录见 `experiments/architecture_baseline/2026-10-04-amd-tsmc-annual-v1/ui-http-verification-v2.json`。首轮 v1 的一条旧 verdict 标签预期失败记录保留，v2 按已更新并冻结的审核身份复验；该旧断言未证明页面缺陷。仍无浏览器或视觉验收。

## 2026-10-04：瑞士风格独立试稿 C — 重新组织机构首页

用户反馈 B 只做了表层调整，要求先解决瑞士风格的核心表达；能力差距分析与财报链路的进一步设计后置。本轮从 v2 另建 [Swiss study C](design/company-workspace-swiss-c/index.html)，保留原版、A、B。视觉计划与工作流复核见 [VISUAL_PLAN](design/company-workspace-swiss-c/VISUAL_PLAN.md)。

可观察变化：机构首页由全宽曲线、下方多列组合，重组为顶部单组 Agent 比较卡，宽窗口下左侧大曲线与事件、右侧当前组合的约 8∶4 布局。选择 Field 后，右侧持仓、环图、报告归属和曲线状态联动；没有重复的第二组 Agent 卡片。Helvetica Neue 与系统中文字体、30px 比较数字、18px 区块标题、等宽占比、连续网格共同形成阅读层级，配色继续保留明快分类色。组合次要配色选择用手动 details 展开。窄窗口自然上下阅读；公司/Manager 的三层外框及报告阅读尺度保留。

不仅改变 CSS：重排机构页 DOM，横向卡片支持前后按钮和左右键；显示偏好使用 C 独立存储键。曲线、SVG 和交易锚点共同采用 1000×480 坐标，按真实日期间隔定位；事件聚合读取实际曲线列宽度，避免双栏布局后误用整页宽度导致事件重叠。报告事件仍在曲线下方，报告入口仍指向选中 Agent、公司及版本。日期与收益含义、模拟身份、公司列表、数据与业务范围校验不改。历史持仓图沿用既有实现，未宣称重做完成。

验证：99 项聚焦机构渲染、真实控制器 DOM 模拟、事件和坐标测试通过；包含新图表的交易锚点与渲染折线相符、双栏实际宽度参与事件合并、配色折叠标题随选择更新、单组 Agent 卡片点击/双击/键盘和报告返回。脚本语法、86 条本地静态引用通过，141 个 v2/A/B 原文件哈希保持不变，现有 8769 预览服务返回 HTTP 200。没有运行模型、接入账户或部署。按仓库约定未打开浏览器或截图；静态与 DOM 模拟检查不代表美感或真实布局验收。

下一步先由用户比较 C 的构图与阅读顺序；确认方向之后再限定页面细化。能力差距和数据层对齐仍是后续独立讨论。

## 2026-10-04：C 版获采纳，增加字体对照

用户明确采用 C，并随后确认其他页面的整体方向也不错。后续前台入口固定为 `docs/design/company-workspace-swiss-c/`，在此基线上持续优化。标题改为「Uteki 投资工作台」，页面主标识改为「Uteki 工作台」，旧版对照链接独立保留。已同步界面 style guide、C 说明和研究页中的采纳状态。认可范围是当前整体方向，不自动扩展到所有细节/视口和真实数据接入。

用户提出 Times New Roman 与宋体，希望研究瑞士字体。先核对 MoMA、Monotype 和 Microsoft 官方说明：Helvetica 的均衡无衬线方向、Univers 的系统字族、Times 的报刊起源，以及 SimSun 的中文衬线风格。研究与设计推断分列在 [字体对照说明](design/company-workspace-swiss-c/TYPOGRAPHY.md)。本机确认存在 Helvetica Neue、Times New Roman 和 Songti 字体文件，未将文件存在视为浏览器实际字体命中检验。

本轮复用 C 的颜色、网格、数据与组件，只新增字号/字族层面的可选比较。默认「瑞士」保留已确认的 Helvetica 系西文与中文无衬线；「书刊混排」将实体标题、报告标题/摘要/长文换为 Times New Roman + 宋体，长文按 18px / 1.9；「经典宋体」扩大到区块标题和部分内容说明。导航、控件、表格、独立金融数值与日期维持无衬线和等宽数字。字体选项是建议而非已采纳的默认变更，色彩与布局保持。

右上角 Aa 原生选择器直接切换根元素字体属性，不重建报告或图表，保留阅读锚点。偏好保存在 C 自己的显示设置中，随页面、主题和界面语言继续使用；非法值拒绝，存储不可用时显示为本次临时选择。只引用本机字体序列，没有下载、复制或远程加载字体。

验证：73 项控制器与路由检查通过，包括新增的字体持久化、语言/主题切换保持、报告/曲线节点与作用域不变、阅读锚点补偿、无效值和存储不可用。脚本语法通过。检查是 DOM 模拟和静态核对，未打开浏览器或检查具体字形；字体气质及实际换行由用户切换评审。无模型调用、部署或账户动作。

下一步优先让用户比较同一份研究报告中的瑞士/混排字体；选定后再细化标题字重和正文节奏。已确认的 C 构图保持，数据层能力差距分析继续后置。

### 2026-10-05：正式 Skill 提取运行接入现有查看页

未改变布局与公司列表。登记 `amd-fy2023-formal-batch-00-v1` 的冻结候选及独立审阅；财务矩阵显示 9 条草稿/9 条 DB 行，运行页保留实际 Skill＋Prompt。两个页面 HTTP 200，核对来源绑定的新运行、原文数值、覆盖审阅及真实方法文本；回执：`experiments/architecture_baseline/2026-10-04-amd-tsmc-annual-v1/ui-formal-run-http-receipt-v1.json`。只读页面不触发模型，候选未采纳；浏览器视觉评审仍由用户完成。

## 2026-10-05：C 侧栏复用原始丝绸蓝雨滴

用户认为当前玻璃雨滴形态别扭，进一步明确先改 Logo、再看其他页面优化。本轮以导航中的品牌图形为唯一对象；视觉方案是复用已封版的丝绸蓝原始轮廓和连续渐变，减少玻璃高光在 26px 显示宽度下的视觉干扰。现有 C 字体、配色、三层工作台和布局不动。此前用户明确要求过「直接程序抠底，保留原图颜色与纹理」，本次沿用此处理方式，没有生成或重画品牌图形。

从 `apps/logo_studio/assets/uteki-silk.jpeg` 的 `[316,253,296,382]` 区域取得雨滴，在白底及明确定位的 S 形留白内做连通背景移除，仅在单像素边界去除白色底色贡献。输出独立 `uteki-drop-silk.png` 与可复现脚本/来源记录；旧玻璃 PNG、原 JPEG 和冻结的 V1 全保留。渲染器更新为对应 intrinsic 尺寸，CSS 仍以原 26px 宽度等比显示。

核对：透明 PNG 本地查看完成；54,264 个内部像素与原图 RGB 完全一致；边缘重合成到白底最大通道误差为 0；S 形开口和四边透明，原图封版文件哈希匹配。机构、公司、Manager 的两种界面语言均只渲染一次新资源，现有服务返回 HTTP 200。没有浏览器、截图或新一轮页面视觉验收；透明资源核对不代表用户已接受侧栏效果。

下一步先由用户看 Logo 的小尺寸效果，再处理首页重复品牌标题与无效留白。字体对照继续保留，未改持仓或研究行为。

## 2026-10-05：C 首页精简重复标题与顶部空间

用户认可新的丝绸蓝侧栏 Logo，并授权继续此前提出的首页精简。本轮对象是机构投资总览，输入、收益区间、Agent 选择与明确模拟快照保持原契约。视觉计划先记录在 C 的 VISUAL_PLAN.md：复用纸白、浅灰、深文字、蓝色交互 token 与 Helvetica 系，保留三种字体对照；通过减少重复内容腾出空间，而非缩小收益数字或正文。

机构路由专用页首合并原工具栏和机构标题，从固定 40px + 76px 改为最小 56px、窄宽度可换行的一个区域。「Uteki 工作台」「工作台 / 投资总览」和机构大标题合为一个 20px「投资总览」标题；机构全名保留在可访问名称中。模拟按钮、快照日期和币种直接可见，日期来自原 simulation 字段并使用 time 元素。旧版对照移入设计说明；字体、语言、主题、上下文入口保留。公司和 Manager 仍使用原工具栏、实体标题与栏目，隐藏机构空标题行后阅读区仍明确处于 grid-row:4。

去掉 Agent 比较和当前组合上非步骤性的 01 / 02，比较卡最小高度 92px 调为 80px，去掉紧邻页首分隔的重复横线；比较带、主体、图表控制区间距收紧。数字仍为 30px，约 8:4 主体、图表尺寸比例、事件定位和组合交互不变。没有改公司目录、报告归属、收益/持仓样本、执行能力或业务默认值。

验证：84 项既有 institution-view / interaction 检查通过，脚本语法通过。另直接核对中文/英文唯一页首、模拟按钮、日期币种、设计说明旧版入口，以及公司/Manager 页头未合并；25 条入口和变更模块本地引用解析通过。预览服务 HTTP 200，入口响应与本地文件一致。初次沙箱内回环访问失败，获准通过本机只读访问后确认成功。没有打开浏览器、截图或运行模型，未将检查等同于真实布局或美感验收。

下一步：用户查看本轮首页精简；后续按具体反馈处理组合说明和内容节奏，暂不扩大到新页面或数据层。

## 2026-10-05：公司与投资 Agent 沿用精简主页层级

用户明确评价主页效果最好，并授权检查公司、投资 Agent 页是否一并优化。源代码检查发现旧实体页仍有工作台标识、对象面包屑、单独实体大标题三层重复，且公司概览与 Manager 栏目中还有泛化说明或重复标题。视觉方案已先记录于 C 的 VISUAL_PLAN：沿用色彩/字族/明快分类色，以 20px 对象标题、28px 对齐边线、最小 56px 工具栏和 38px 栏目组织页面，删除冗余而不压缩正文。

实体身份移入工具栏；公司保留 icon、名称、代码和简介，Manager 保留名称、风格和期限。研究数量和模拟身份移到固定栏目尾部，报告份数继续由报告 tab 显示，Manager 当前关注与覆盖总数继续区分。空 company-header 节点保留但隐藏，栏目与正文显式定位 grid-row 3 / 4。工具和栏目可换行，阅读区继续原生滚动。旧版对照进入设计说明。公司名单、全局导航、对象切换、内层目录和栏目路由保持。

公司概览去掉独占一行的研究概况/泛化副标题，直接进入四栏目与摘要。Manager 概览去掉研究进展的泛化副标题，收紧摘要与列表前留白；研究覆盖、研究报告和操作历史的重复 h2 改为 sr-only，保留语义标题，并以计数、模拟身份和筛选直接引出正文。报告的计数与公司筛选同一行；三类关注阶段、原因、日期和缺口不删。研究表格的字号、完整标题、6/8 行分页、数值和长报告尺度不变。没有改持仓/收益/研究样本、报告归属或来源版本，没有增加业务默认值。

验证：94 项既有 institution-view、manager-view、interaction 检查通过，覆盖选择、报告历史、证据和返回位置、范围错误、字体/语言/主题切换等。另检查 64 个中文/英文实体视图的唯一主标题、模拟身份、旧版入口与 DOM ID 唯一性；机构页双语工具栏、栏目、主体及设计说明渲染的 SHA256 与本轮开始前一致。脚本语法通过，现有预览入口 HTTP 200。独立只读代码复核确认网格和可访问性边界，并修正 Manager padding 的选择器覆盖。没有运行浏览器或截图，程序检查不代表真实页面视觉验收。

下一步先由用户查看公司与 Agent 的统一节奏，再按具体阅读反馈处理局部内容密度；主页维持已认可状态。

## 2026-10-05：瑞士参考与当前页面实图对照

用户明确要求再次打开参考网站比较舒适度。本轮只做研究及独立对照页，没有修改工作台实现或用户字体偏好。重新核对此前 Niggli 书籍和 Poster House 海报参考的范围，并补充 SBB Lean 数据表格与排版规范。Niggli 商品页用于观察主次关系，SBB 用于观察功能性数据排列，不将两者与金融工作台等同，也不将当代瑞士机构界面称为历史瑞士风格的唯一表达。

实际浏览并保存 Alphabet 有内容、NVIDIA 无报告、已认可机构主页、Niggli 商品页、SBB 可排序表格例图五张截图，放入 [实图对照页](research/swiss-comparison-2026-10-05/index.html)。当前 Uteki 字体实测为经典宋体；同字体下主页仍有更明确的视觉重心，因此没有把问题归因于字体本身。设计判断集中在重复栏目权重偏高、容器留白与内容数量不匹配、主内容与元信息层级接近。后续建议先用相同内容做公司概览和空状态对照，再考虑延伸到 Agent；这些是待讨论建议，尚未采纳为新规则。

检查：在浏览器确认对照页及实图显示，点击切换 Uteki 与参考页面后，图片链接、来源和说明对应更新，已恢复初始比较组合。截图保留实际来源及窗口差异说明；SBB 展示的是规范内例图，不是已验证交互的数据表。没有模型调用、部署、真实账户操作或工作台回归改动。


## 2026-10-05：Swiss C 完整体验审查与报告呈现

### 基线、目标与实施顺序

依用户批准的实施计划，本轮先冻结已采纳的 Swiss C，再以首次投资者与连续研究者两种角色实际浏览走查，之后修改。输入是现有具名模拟组合、研究目录、关注记录和报告版本；输出是原生网页优化与 Alphabet / North / alpha-north-main / v2 / zh-CN 的同源 PDF 样稿。公司名单、研究判断、财务值、事件日期、明快配色、手动切换、首页构图及操作历史组织均保留。后台、真实账户、公司空白区的新业务内容继续后置。

修改前的 102 个页面和静态依赖文件已归档至 [基线归档](design/baselines/20261005-before-ux-review/README.md)，包含 SHA256 清单与恢复说明；归档内全部文件重新核对匹配。改动后的依赖哈希比较确认 `apps/uteki_zero/`、具名组合/事件/关注 fixture、公司图标与丝绸 PNG 未变。

视觉方案沿用已确认的 Swiss C 网格和三种字体：覆盖内容集中在同一组等高卡片；筛选靠近产出目录；报告以具体版次标题、判断、正文、证据依次阅读。正文最大 760px，无衬线 17px/1.85，宋体/Times 18px/1.9。导航沿稳定窗口断点推动，宽度变化不改变首页主结构；交易绿/红浅底使用同一语义 token。没有增加框架、后台 API 或品牌循环动画。

### 走查发现与复查记录

问题记录区分真实浏览器观察、静态机制分析和控制器模拟。截图位于 [review-20261005](design/company-workspace-swiss-c/review-20261005/)。

| 编号 | 操作与证据 | 实际问题及影响 | 处理与复查 |
|---|---|---|---|
| UX01 · 高 | 1200×820 的投资总览，展开导航；[修改前](design/company-workspace-swiss-c/review-20261005/before-nav-expanded.jpg) | 实际双栏 `696px 348px` 变成单栏 `952px`，阅读锚点补偿把图表推到屏外（chartTop -451.4）。 | 机构及其内部响应规则改为窗口断点。实际复查收起 `696px 348px`、展开 `600px 320px`，保持双栏、图表位置和滚动；[修改后](design/company-workspace-swiss-c/review-20261005/after-nav-expanded.jpg)。 |
| UX02 · 中 | 读事件时展开/收起导航；代码检查 ResizeObserver，控制器记录每帧 DOM | 原机制在宽度每变 10px 时重建标记。重聚合可能让正在阅读或键盘聚焦的标记消失；这是静态风险，未把它写成修改前浏览器逐帧性能结论。 | 240ms 过渡期间保留原标记与原聚合锚点，仅跟随几何移动；transitionend/兜底结束统一重算。密集组跨 1000/760/620/500 宽度的测试保留弹层和事件焦点。实际 Microsoft 6月18日事件被合并后仍显示原日期与详情。 |
| UX03 · 中 | North → 研究覆盖；[修改前](design/company-workspace-swiss-c/review-20261005/before-coverage.jpg) | 三个阶段列分散、卡片高度与入口不统一，未来关注无报告时更难横向比较。 | 全部/当前/历史/未来四个计数标签，默认全部，同一网格 280px 等高卡，六项分页；完整原因在上下文可读。实际验证 Arista 无报告仍有关注详情、没有无效报告入口；[修改后](design/company-workspace-swiss-c/review-20261005/after-coverage.jpg)。 |
| UX04 · 中 | 公司、Manager 的研究报告目录；[修改前](design/company-workspace-swiss-c/review-20261005/before-report-directory.jpg) | 无标题和类型联合筛选；公司无报告目录及上下文把历史占位关系当成研究覆盖，页头统一显示 2 Managers。 | 共享严格作用域目录：公司 Icon/作者、类型、关键词联合筛选，八项分页，当前版次去重，发布日期倒序＋ID稳定排序。无匹配显示条件和清除，未产出单独提示。公司页头与上下文只计真实报告作者；NVIDIA 实际显示 0 作者，关注阶段回各 Agent 的明确记录查看。 |
| UX05 · 中 | 打开 North Alphabet v2 并阅读 | 主要标题仅为通用“公司研究”，具体版次判断不突出；引用编号在各章节重新开始。 | 改用原 report.title，文档标签保留；返回、版本、章节和对应 PDF 集中。证据全文按 ID 编号，同名不同定位分别保留。[实际阅读截图](design/company-workspace-swiss-c/review-20261005/after-report.jpg)。原正文、表格和判断未改。 |
| UX06 · 中 | 公司 → 资料与数据 | 同名同日的联合简报两条记录难以区分，必须逐条打开。 | 列表增加原文定位。实际可直接区分“客户使用部分 2—3 段”与“建设安排部分 6—7 段”；不合并不同证据。 |
| UX07 · 中 | 改动后事件详情打开，点击导航开关 | 复查实际发现全局点击外部逻辑关闭弹层，虽然只是在展开导航。 | 导航开关豁免该关闭规则，其他外部点击仍关闭。实际重走保留原 NVIDIA/Microsoft 日期、详情、聚合选中；Escape 和关闭入口仍可用。 |
| UX08 · 高 | 控制器模拟：North 中文 compositionstart → 切 Field → 迟到 compositionend | 自动测试复现旧输入节点把关键词写入另一位 Agent；没有收到 compositionend 时还可能锁住新页面输入。未声称浏览器输入法实测。 | 只接受当前输入节点，切路由释放输入状态；迟到事件丢弃。正常输入、光标、跨 Agent 不串值回归通过。 |
| UX09 · 低 | 展开品牌及查看买卖标记 | 品牌字标被通用标签字号覆盖，图形与文字基线不统一；交易色义未贯穿所有入口。 | 原 PNG 静态 24px，字标 23px，同轴对齐，投资总览换统计图标。Buy/Sell/Report 共用绿/红/紫 token，10%/16%浅底；混合中性。实际暗色操作历史与浅色事件可读，布局未重做。 |

### 行为与实际浏览分开验收

- 程序检查：现有 Swiss C 全集 **257/257** 通过，其中控制器 83 项；新增联合筛选、跨实体状态隔离、恢复焦点/滚动、IME、防止导航重建、重聚合焦点和减少动效立即完成等行为检查。目录用独立合成多公司数据验证六/八项分页、条件变化重置、稳定排序、无报告阶段和错误 scope；没有靠扩大当前演示数据凑通过。53 条静态文件引用可解析，PDF 预览链接 HTTP 200。
- 实际浏览：修改前和后均走投资总览→选 Field/持仓→指定作者报告→历史版本→引用→返回；返回保留 Agent、配置选择和报告入口焦点。报告事件进入 North v1 后返回保留 1月区间、按日粒度与事件标记焦点。明确的“展开持仓”入口仍可替代双击。
- 公司与 Agent：概览、覆盖、目录、材料、关注点与操作历史均经过浏览；按公司＋主报告＋“需求”搜索后进入阅读，切版本再返回保留过滤与行焦点；清空、无匹配、NVIDIA无报告、未来关注无报告均可理解和退出。长文第4节目录定位、摘录缺口说明、Escape关闭并恢复引用按钮已实际观察。
- 显示：1200×820 中文浅色与 960×760 英文暗色实际检查；窄窗口卡片减少列数、表格可局部阅读，页面无横向溢出。保留原生长文滚动和三种字体选择，未把测试次数当作美感结论。审核期间浏览器未记录 JS error/warn。
- 边界：没有通过工具更改 macOS 的减少动效偏好；此项为控制器 matchMedia 与 CSS 验证。侧栏实际检查通过点击/键盘开关及鼠标进入导航时的展开完成；纯悬停延迟与动画中每帧的保留由控制器测试覆盖，未声称逐帧浏览器性能验收。报告超过八项/覆盖超过六项的完整翻页由合成数据检查，当前报告样本数量不足以冒充真实多页视觉验收。后台与真实业务数据质量未在本轮验证。

### 同源 PDF 样稿

[PDF](../output/pdf/uteki-research-sample.pdf) 的明确 scope 为 Alphabet / North / alpha-north-main / v2 / zh-CN。网页和 ReportLab 使用 `buildReportPresentation` 的同一份完整投影，包含 8 节正文、4 个不同证据 ID；样稿链接仅出现在该报告版本。静态样稿共 5 页，A4 竖版、宋体/Times正文与无衬线元信息、可点击目录、表头重复配置、页码与引用附录。87项源文本逐项核对保留；五页实际渲染逐页查看，修复首次附录跨页孤行后复查，无缺字、裁切与孤立来源标签。哈希/scope 见 `output/pdf/uteki-research-sample.manifest.json`，QA见同目录 `.qa.json`。

这份报告和引用均是原有具名虚构研究样本。只有本报告PDF可下载，没有虚构来源的“原件下载”，也没有新增全量导出服务。正文未翻译，英文UI明确说明原报告为中文。

下一步优先由用户比较新版报告阅读和PDF气质；后续再单独讨论公司空白区域内容与持仓历史图，不扩展本轮业务范围。

## 2026-10-05：真实 Data Agent 材料工作台

### 本轮工作对象与视觉选择

按用户确认的计划新增 `/data-workspace`。工作对象是“公司的一份已获取材料及其加工结果”；使用已登记、经过来源校验的真实数据，不把静态 Agent Demo 任务接成真实执行。

布局为左侧公司、顶部可折叠材料目录、材料标签、并排原文和产物。默认按报告期结束年份倒序，发布日期独立显示，可搜索和按文件类型分组；缺失报告期不推断为最新。目录基于现有注册，未改变持续研究名单。原件标签全宽；财务、章节等标签并排核对。主数据口径、金额、来源、核验状态优先，长 ID、哈希和保存路径置于展开详情。

瑞士风格本轮参数：背景 `#f4f5f6`、纸面 `#ffffff`、正文 `#252b33`、次级文字 `#66707e`、分隔 `#dfe3e8`、操作强调 `#355d9f`；Helvetica Neue / PingFang SC，正文 15px、标题 22px、数字等宽排列。固定网格、细分隔，hover 不切换对象；原生滚动不翻页，分隔条支持拖动与键盘调整。复用现有产物读取与表格渲染，不加载新的 UI 框架。

### 展示与数据边界

- 财务表只合并明确选定的任务版本；基础数据库是显式独立入口。没有选择时显示版本选择器，不默认挑最新。任务注册依据真实 job/packet 输入与哈希，AMD、台积电各 4 项任务，共 12 次已保存尝试。
- 精确期间、单位、币种、会计口径、实体和维度参与分组；不同候选不相加，冲突并列。金额只做千分位与无效末尾零的显示处理，原值与有效精度保留。
- 运行没有写出规范化数据、材料精编尚未生成、缺少逐条核验分别说明。处理页读取已保存的任务、Prompt/Skill、输入块、数据库输出和审核；完整主 Agent 获取/处理 trace 未接入时明确告知。
- 展示选择和可恢复归档保存到独立、忽略提交的 `data/review_workbench/ui-state-v1.json`；初始无选择。只归档未选中的提取版本，不归档公司或材料，不改变正式采纳和 MCP 查询范围。历史链接继续可读。
- 原件在禁脚本 iframe 中展示。HTML 高亮只在响应副本注入，经原始 DOM 路径和块文本核对后定位；当前 AMD/台积电核验达到整表精度，未声称单元格定位。PDF 必须有真实页码映射才跳页。
- 同材料切换标签保留原文 iframe；产物列表/表格位置、筛选与已选事实恢复。跨页面重新打开原件恢复至已选证据块，不声称记录了隔离 iframe 中任意手动滚动的像素位置。
- 旧 `/evaluation` 与 `/extractions` 保留；旧评估页和 8769 静态 Demo 增加/更新真实工作台入口。页面查看不调用模型。

### 验证边界

独立合成双公司测试覆盖相同局部 ID 的隔离、来源冲突、精确金额、显式选版、归档恢复、并发修订、保存失败，以及冻结数据/MCP 字节保持。真实 AMD 与台积电经营现金流原件定位成功并核对原文件哈希不变。交互控制器测试覆盖异步原文请求先后顺序、无证据时清除旧高亮、返回导航、筛选、键盘调整与滚动恢复。

本轮不进行浏览器截图或视觉验收；视觉由用户 review。后续优先根据实际阅读反馈调整信息密度，再考虑按需加载完整记录详情；本轮不新增模型提取、人工评分或重新运行调度。

本轮最终检查：100 项针对性 Python 检查、10 项新工作台控制器检查与 27 项旧 Demo 检查通过。最新服务启动后，AMD/台积电财务候选页、同源整表定位、禁脚本响应头和旧链接均通过实际 HTTP 检查；跨公司及无效状态请求被拒绝。测试没有替用户选版或归档，真实 UI revision 保持 0。旧 Alphabet 摘录第 90 段的历史完整性警告保留，不通过改原文或哈希消除。

## 2026-10-05：材料工作台 A+B 样式与财务核对优化

用户认可现有“公司 → 材料 → 产物 → 原文”结构后，选择同时推进财务核对交互和全页视觉层级。可观察的验收例子是：打开 AMD 年报财务数据，连续选择不同期间的数值，在同一张表旁核对原件；选择动作不主动滚动表格，不把详情展开到整表末尾。公司名单、材料组织和读取范围维持现有规则。

### 本轮选择

- 全页延续灰白蓝、Helvetica Neue / PingFang SC 与细分隔线，统一标题、元信息、输入控件、材料列表和栏目间距；财务数值右对齐，表头和指标列固定。未增加框架或新的视觉主题。
- 财务结果区改成上方表格、下方核对区。桌面预留 38%（最低 140px），窄屏预留 220px；空状态和选中状态使用相同尺寸。详情独立滚动，选中行和单元格都有标记。选择数值不调用自动滚动；只有明确点击“回到数值”时才定位该单元格。
- 清除选择恢复原表格按钮焦点且不主动滚动，移除旧详情、摘录和高亮；筛选排除当前行时同样清除。保存的筛选与直达事实冲突时不展示隐藏记录的证据。
- 展示范围收为常显摘要：明确区分选定任务版本、注册基础数据库、单次历史预览和未选版。完整版本及归档历史按需展开；展开内容超过右栏时允许原生滚动，避免底部操作被裁掉。
- 原件展开按钮显示“展开阅读／返回对照”；全宽原件标签隐藏该按钮。定位提示区分核对位置、加载原件、定位结果和失败；语言切换同步更新提示。异步旧请求不能覆盖新选择，清除选择后迟到响应不恢复旧证据。
- 本轮只改展示与交互。原文禁脚本隔离、来源校验、原始金额与口径、展示选择和正式采纳的边界不变；不调用模型，不重新提取数据。

### 检查与剩余 review

40 项针对性 Python 检查、19 项工作台交互控制器检查通过，覆盖页面范围、财务口径及路由、固定核对区状态、筛选清理、异步隔离、加载提示、键盘定位及状态写入冲突。最新本机服务的 AMD 与台积电页面、核对区结构、同份原文整表高亮、禁脚本响应头和历史链接经过实际 HTTP 检查；跨公司请求被拒绝，真实展示选择未被检查程序更改。

本轮没有打开浏览器或做视觉验收。固定区域的比例、实际阅读密度、短窗口和长指标名的体验仍由用户 review；程序与静态布局检查不代替这些结论。原文仍按已保存证据提供整表或块级定位，不承诺单元格精度。下一步优先人工连续核对两个数值，再根据反馈调整核对区比例和字号。

## 2026-10-05：Portfolio / Risk 协作产物前台（Swiss C）

用户明确先忽略技术执行，批准先体验「组合决策」。可观察路径：首页选择 North → 近期组合决策 → 配置变化／研究依据／风险与回应 → 固定版本研究报告 → 返回同一决策、标签、阅读位置和焦点。

- 保留首页、公司列表、Manager 实体与操作历史布局；Manager 增加「组合决策」，概览、选中组合、操作历史均有入口。首页入口随选中的 Agent 联动。
- 左侧按日期选决定，右侧默认显示最终目标、调整前比例、百分点变化、现金与原因；初稿对照按需展开。风险意见与 PM 回应相邻，已回应仍显示持续观察。
- North 3 个、Field 2 个具名虚构情景，含调整与维持不变。调整前／初稿／目标分别含现金合计 100%。它们是独立设计情景，不是连续账户历史；不与既有持仓、收益或交易样本建立虚假的执行关系。
- 研究依据固定公司、Manager、报告与版本；未附本经理报告的资产明确显示缺口。没有修改报告原文或借其他作者补位。Manager 间决策、标签选择在本次页面会话独立保留。

代码与数据审查发现并修复：决策页未继承已选色卡；新阅读区缺少导航／字体重排的位置锚点；容器断点可能使 Sidebar hover 触发左右结构跳变。前两项有控制器验证；后一项改用稳定窗口断点。上述属于静态与程序证据，没有宣称浏览器复现。

Swiss C 现有与新增 281 项测试通过，覆盖归属与日期、权重、风险回应与执行状态、精确报告往返、不同 Manager 的状态隔离、首页联动和阅读锚点。原有首页、报告、事件、覆盖与操作历史测试同时通过。语法检查通过，本地预览恢复在 127.0.0.1:8769，页面 HTTP 200。修改前主要文件及哈希保存于 `/tmp/uteki-decisions-before/`。

本轮没有运行模型、接入账户或构建真实 PM / Risk 服务；没有浏览器视觉验收。下一步先由用户沿上述路径体验，确认配置变化和风险回应是否直观，再打磨信息密度。真实研究驱动决策、行情与执行账本属于后续独立范围。

## 2026-10-06：持续 Risk Manager 跟踪（Swiss C）

本轮在已批准的「组合决策」上补充持续风险产物。可观察路径：选中 Field 组合 → 风险摘要 → 交付风险 → 两次决策中的 Risk 意见与 PM 回应 → 固定版本报告 → 返回原风险。已回应但尚未解决的问题继续显示。

- 机构当前组合与 Manager 概览新增紧凑摘要；Manager 增加「风险跟踪」。沿用 Swiss C 的左列表／右详情，手动选择全部、待复核、持续观察、已结束；筛选与风险选择按 Manager 独立保存。
- North 三条、Field 一条具名虚构风险，具有独立身份、开始／更新时间、明确公司范围、证据记录与复查条件。Field 的一条风险显式对应两次决策，不按标题或相同公司推断关联。
- 单次决策保留当时的风险与回应，并提供持续风险入口；风险详情可进入该决策及报告。报告、决策、风险之间返回恢复原筛选、标签、滚动及焦点。导航／字体重排复用阅读锚点，结构断点依据窗口。
- PM 回应与风险结束状态独立。结束必须有具名日期、说明和可用证据；无记录不等于零风险。证据严格绑定公司、作者、报告、版本、章节与引用，时间不超出对应截止范围；不可用原文继续标明缺口。
- 对照表明确为相关决策的初稿／最终目标，不把全部变化归因于单一风险，不伪装成成交；「未修改初稿」与「维持原持仓」分别表达。原研究内容、公司名单、模拟收益、持仓与交易事件未修改。

### 发现与修复

静态审查发现风险详情 DOM 与控制器的阅读锚点选择器最初不一致，已补齐；对照呈现中初稿等于最终目标可能被误标为维持持仓，已修复并由独立调仓样本验证。首页新增风险摘要的测试首次点击默认 North 没有发生切换，模拟 DOM 不提供嵌套 innerHTML，已改为分别核对初始输出及 Field→North 实际切换。这是测试环境问题，没有误报成浏览器缺陷。

### 检查与边界

- Swiss C 全集运行时 309 项通过；随后新增的独立路由文件 6 项单独通过，合计 315 项不同测试。覆盖旧报告／决策链接兼容、错误及跨 Manager 范围拒绝、筛选空状态、证据缺口、多次审查、报告／决策嵌套返回、Agent 摘要联动、主题／语言状态与阅读锚点。独立 2024 和 2025 公司及期间样本验证没有原演示对象回退。
- 8 个变更模块语法与 41 条本地导入解析通过。入口、新风险渲染、CSS 与样本模块实际 HTTP 200，响应逐字节匹配保存文件；预览仍在 127.0.0.1:8769。
- 本轮无浏览器视觉验收，实际列表宽度、短窗口和新增摘要密度由用户 review。没有调用模型、建设后台服务、执行交易或更改账户；收益样本与独立决策场景没有建立虚假执行关系。
- 用户追加询问价值投资的止损职责，已按投资判断失效、组合约束与价格触发复核分开讨论。本轮没有新增自动止损比例、Risk 否决权限或执行规则；这类权限应由后续明确的投资政策决定。

修改前原文件与哈希保存在 `/tmp/uteki-risk-before-20261006/`。下一步先体验 Field 风险到两次决策的往返，再确定投资判断失效和组合硬限制如何表达；无需重做已认可的主结构。
