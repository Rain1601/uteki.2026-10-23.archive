# 组件接入与边界

便携组件在 `../assets/editorial/`。入口 `starter.html`；用静态HTTP服务运行，ES modules不适合file协议。复制需要的模块、CSS和相对依赖；不要求复制全部页面。

| 用途 | 模块 / 接口 | CSS |
|---|---|---|
| Header/Sidebar/表格 | editorial-primitives.mjs / Header, Sidebar, DataTable | style.css |
| 卡片/列表 | compound-components.mjs / Card, ItemList | compound-components.css |
| 字段/菜单/反馈 | workspace-controls.mjs / TextField, ActionMenu, Notice, InlineAlert | workspace.css |
| 选中/详情/正负图 | workspace-components.mjs / ViewTabs, RecordDetail, SignedBars | workspace.css |
| 提示/展开/导航/分页/加载 | utility-components.mjs / Tooltip, mountTooltips, Accordion, Breadcrumb, Pagination, Loading | utility-components.css |
| 引用与来源 | citation-components.mjs / Citation; source-panel.mjs / mountSourcePanel | citation-components.css + source-panel.css |
| 正文媒体 | reading-media.mjs / createArticleVideo, createKineticFigure, mountMediaWindow | reading-media.css |
| 局部放大 | image-inspector.mjs / mountImageInspector | image-inspector.css |
| 数据点联动 | linked-charts.mjs / mountLinkedCharts | linked-charts.css |
| 文章/图解 | story-components.mjs / StoryLead, PullQuote, mountExplainer | story-components.css |
| 范围控制 | scope-controls.mjs / createScopeControls | scope-controls.css |
| 报告阅读 | report-reader.mjs / mountReportReader | report-reader.css + 来源CSS |

源码是当前接口依据；先看目标模块的签名与校验，不能凭类名猜参数。共享依赖 components.mjs、tokens.mjs、source-excerpt.mjs已附带。报告还依赖report-content.mjs与citation-sources.mjs；后者的命名样稿引用附带的项目说明，不是业务事实。使用新报告时显式传入模型，不靠旧命名样稿补内容。

## 状态与生命周期

安全 HTML 渲染器不持有业务状态。DataTable点击入口 `data-record`/排序`data-sort`，ItemList动作`data-item-id`；调用方按ID更新，不能按当前行号替换记录。内容字符串由组件转义。

挂载器返回对象按各模块签名使用。mountSourcePanel、mountTooltips等有destroy；报告有getState/destroy。卸载/重挂先清理监听、播放器与面板；同内容换语言先取得状态，换主题通常只写变量。图表 SignedBars 接受正/负/0/null；ChartFrame仅非负有限数，勿绕过校验。

来源输入必须明确id/title/text/caption/kind、可选locator/href，引用ID匹配本次来源集。kind使用组件已有枚举。面板只定位与筛选提供的摘录，不抓全文也不判断真假。关闭恢复首次打开时的坐标与引用焦点。保留陈述与原文出处身份。

报告合同当前限定authored-specimen，要求显式双语字段、章节/图表/来源ID；没有真实自动研究功能。用于生产内容时需要明确扩展合同，不把业务报告伪标为原创样稿。

## 原仓库与非便携能力

在Uteki仓库内，完整v1实例位于 `docs/design/dashboard-demos/editorial/`：system.html/QUICKSTART.md/EDITORIAL_DESIGN_PRINCIPLES.md。Agent/finance/portfolio/workflow等是固定模拟任务模板，不能作为真实模型或数据后端。中英两页PDF由PDF_LAYOUT_RULES.md/render_pdf_v03.py定义，长文分页未实施；便携包不包含该渲染器或77MB字体。

便携style.css将原型字体替换为系统角色回退，没有下载/复制字体；不是原型字体完全一致的承诺。使用已有产品时隔离基础全局规则，保留用户批准字体与组件框架。需要新增/改动API时改共同契约，不写样本ID或样本金额特例。

## 局部主题、Portal 与额外交互

来源面板默认仍挂到body。若配色只施加在局部宿主，调用 `mountSourcePanel(host,{sources,portalContainer:host,scrollContainer:actualReader})`，让dialog继承相同变量；也可传入同文档内拥有相同主题的portal根。传入其他文档或不能append的容器会拒绝。主题应用用applyPalette逐项写变量，不覆盖原内联布局；scoped CSS也应覆盖portal。

DataTable只有原生Tab/Enter/Space按钮基础；ArrowUp/Down选行或roving tabindex由具体应用实现，按当前筛选排序后的ID操作。Accordion只接受文本与安全链接，不是任意控件插槽；高级筛选用宿主框架的受控disclosure，保留展开状态，保证通用区域位置稳定。不要把这些适配行为称为组件已经提供。

来源面板可选 headerAction:{label,onClick} 提供宿主动作；mountReportReader 的 sourcePanelAction 透传。主题回调只更新变量并保持实例及阅读回程，详见 palettes.md。
