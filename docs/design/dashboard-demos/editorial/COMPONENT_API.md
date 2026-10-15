# Editorial 四组件契约 v0.2

> **历史记录**：以下保留各阶段原始范围、接口和验收，文中的“当前／下一步／未完成”属于当时状态，不代表 v1 最新清单。当前以 [系统样册](system.html)、[使用说明](QUICKSTART.md) 和 [交付记录](DESIGN_SYSTEM_DELIVERY.md) 为准。

当前 ES04.1：Header / Sidebar / Table / PDF 可复用样册。入口 `editorial-primitives.mjs`；`components.mjs` 保留原导出并转导这四项。现有 vanilla 页面已使用这些组件，尚未迁移生产页或提供 React 包。

## 风格与来源边界

参照 Anthropic 文章页导航、Project Swap 目录、Haiku 5.5 的表格与 Project Swap PDF 两页。组件数据、品牌及内容由调用方提供；英文使用本地 Liberation Sans / Serif，保留发行包许可。中文网页固定 Noto Sans SC / Serif SC，PDF 限英文两页。色彩属于项目主题。

## 输入与职责

| 组件 | 必需输入 | 可定制部分 | 明确失败 |
| --- | --- | --- | --- |
| Header | brand、brandHref、links、label | action、mountId；导航字号/高度/边距 tokens | 无文案、不支持的 URL 或非法 id |
| Sidebar | entries[{id,label}]、label | currentId、showIndex、workspace/article | 重复 id、未知当前项 |
| DataTable | rows、columns、rowKey、caption | numeric/interactive/descriptionKey、sortKey/direction、selected、locale、ruled/grid | 缺失/重复行身份、重复列、未知排序字段、非有限数字 |
| PDFPreview | model、layout、locale | 显式内容、类型角色、Letter 几何与主题 | 非支持的两页英文版式、非法尺寸/字体角色 |
| PDF generator | 同一 model + theme JSON、字体目录、layout JSON | 页面/边距/字级/表格/页脚/样册标签 | 字体缺字、非有限数字、正文或表格溢出 |

Header 返回完整 header。Sidebar 返回 nav；工作台的 aside 和粘性容器由布局持有。DataTable 返回表格与滚动容器。组件只渲染，不隐式读取实体、修改数组或拥有业务状态；组合页绑定 data-action/data-section/data-sort/data-record，并保有选中身份。

## 使用示例

```js
import {Header, Sidebar, DataTable} from './editorial-primitives.mjs';
import {themeCSS, componentCSS} from './tokens.mjs';
// CSS 入口为 style.css。本样册尚未完成对生产 CSS 的隔离。
document.body.style.cssText = themeCSS('mineral') + ';' + componentCSS({
  headerHeight:68, sidebarWidth:240, tableText:15, rowInset:12
});
const html = DataTable({
  rowKey:'key', caption:'Explicit fictional sample',
  rows:[{key:'zero',label:'Zero',value:0},{key:'gap',label:'Missing',value:null}],
  columns:[{key:'label',label:'Item',interactive:true},
           {key:'value',label:'Amount',numeric:true,sortable:true}],
  sortKey:'value',direction:'asc',selected:'zero',locale:'en-US',variant:'ruled'
});
```

主题可传预设名或完整语义色对象，所有角色必须给齐，只接受六位十六进制。尺寸只能覆盖已声明 token，禁止将任意 CSS 字符串作为尺寸。字号、行距与间距可分别调整；版式变化不改变行身份、零值、缺失与负值。

PDF 生成命令（Python 环境须含 reportlab）：

```bash
python render_pdf_v02.py explicit-input.json fonts --layout pdf-layout.json --output output/pdf/custom-specimen.pdf
```

输入 JSON：`{model:{title,date,kind,summary,note,rows:[{label,value}]},theme:{...完整主题...}}`。`specimenLabels` 是明确的虚构样册文案配置，使用者须给出适合自己的配置。原件、HTML 与 PDF 各自渲染；共享契约不等于逐像素一致。

## 本轮验证

`node --test components.test.mjs` 检查独立行键、选择身份、零/负/缺失、不变排序、安全转义、完整主题、安全尺寸、导航与 PDF 支持范围。浏览器实测 Header 68px、目录内容 172px、紧凑行 inset 10px；三主题保留表格文本、当前记录和详情，双语切换保持实体身份。PDF 最终两页渲染实看并检查文字在页内；过长段落和中文缺字输入显式失败，不产生最终 PDF。

发现并修正的共同机制：Sidebar 的变体名 workspace 与页面布局类同名，导致目录继承 48px padding。已改为 sidebar-workspace 并回归宽度。密度切换曾被内联默认 rowInset 覆盖；现在样册 apply 根据密度给唯一 token 值，实测 14→10→14px。未以缩字或隐藏列缓解。

尚未完成：中文 PDF 字体适配、任意长度 PDF 分页、跨页表格、浏览器打印输出核验、生产样式隔离/接入、其他 22 类组件同等深度原站对照。当前样册通过不代表跨浏览器、跨视口或生产环境完整验收。

### 中英文字体版本

英文固定本地 Liberation Sans/Serif；中文固定本地 Noto Sans SC/Serif SC（完整官方可变字体，非样本文字子集）。文件摘要和来源见 `fonts/manifest.json`，对应 OFL 文本已保留。原 TTF 共约43MB，当前服务从本地读取；生产迁移前需要生成适合部署的 WOFF2/按完整语言范围拆包，并保持来源与字体版本。缺少 fontTools 的压缩尝试未修改字体文件，当前不声称已优化字体包大小。字体文件固定不等于跨平台光栅化完全一致。

## v0.3/v0.4 最新入口

中文PDF已完成并获用户确认；双语生成规则见`PDF_LAYOUT_RULES.md`，旧v0.2 HTML预览仍明确限英文。完整页面见`workspace.html`，组合契约见`WORKSPACE_DESIGN.md`。

新增`workspace-components.mjs`导出ViewTabs({entries,selected,label,panelId})、RecordDetail({record,labels,locale,first,last})、SignedBars({rows,label,unit,locale,selected,missingLabel})。事件data-view/data-record/data-step/data-read/data-close由页面绑定，组件无隐式状态。SignedBars使用明确value数值、null表示缺失、零显示数值但不造条形面积；负值向零轴左侧延伸。适用于小量对照记录，不声称时间趋势或虚拟列表。

## ES04.5 最新增量

整体页面风格获用户认可，沿当前样式参考MUI官方表单/菜单/弹层/反馈行为。v0.5新增显式关联私人笔记、就地验证、本机保存与撤销、键盘菜单及范围导出。组件契约、来源、验证和当前路线以`INTERACTION_COMPONENTS.md`为准。下一ES04.6日期区间/多选/全局检索，生产仍未迁移。


## 2026-10-10 · ES04.7a 案例阅读与分步图解

新增StoryLead/事实栏、PullQuote与mountExplainer，已组合到所有记录的阅读视图；原数值、记录身份与笔记保持原范围。用户要求先将案例/动效入页，ES04.7a完成、ES04.7b为下一项，ES04.6保留队列。来源、API、实际检查及未完成媒体能力见[组件记录](STORY_COMPONENTS.md)。


## 2026-10-10 · ES04.7b 正文媒体交付

正文内视频/曲线/轨道均可展开，关闭暂停且回到正文。新增createArticleVideo/createKineticFigure/mountMediaWindow；原生视频与原创7秒素材已实际播放。ES04.7b完成，下一ES04.7c，ES04.6保留队列；详见[复用接口与检查](READING_MEDIA.md)。旧图解拖动先读值再暂停，避免重绘覆盖输入。


## 2026-10-10 · ES04.7c 图片局部与图表联动

新增mountImageInspector与mountLinkedCharts，组合至阅读页#read-inspect。圆形局部镜与双图共享参考线各用不同形式；系列按id连接，缺失/零/负值保留。鼠标/键盘与文档切换检查通过，42项组件测试通过。当前位置ES04.7c已交付，下一ES04.6，生产未迁移；最新完整队列及接口见[检查组件说明](INSPECTION_COMPONENTS.md)。此前阶段记录保留为历史。


## 2026-10-10 · v0.14 常用组件与任务页面

已落实日期/多选/快速检索（ES04.6）、资源目录/可调分栏/PDF图像预览（ES04.7d）、财务应收分析（ES06.1）、工作项看板（ES06.2）、投资贡献/散点/持仓联动（ES06.3），及视频启发的证据复核（ES06.4）。它们使用不同布局，来源观察与原创适配分别记录；固定模拟内容不等于真实产品能力。

用户提供金融服务视频后，抽样检查30–55秒工作台：阶段、异常、过程轨迹、来源摘录和复核交接。Academy文字页面不再被当作实际App交互证据。网页小工具箱实见闭合/露出工具两种动态帧；新增原创createEditorialPictogram，实际放入档案页，有暂停和reduced-motion。资源视频字幕随语言切换。

当前接口、逐项实页检查、来源等级、完整任务ID和未完成范围统一见[页面范式与当前路线](PAGE_PATTERNS.md)。这些阶段的旧队列保留为历史，不代表当前未开始。没有安装MUI、调用外部模型或迁移生产。


## 2026-10-10 · v0.15 卡片、列表与 Agent 任务页

新增独立 Card/ItemList（compound-components.mjs/css）和 mountAgentTaskPage（agent-task-page.mjs/css），并组合为 workspace.html?view=agent 第九个工作台视图。卡片覆盖附件、任务摘要与产物，列表用于可展开的过程记录；状态与本地化显示文本分开。任务输入→手动推进→待确认→产物预览，含暂停、取消和一次模拟中断恢复，跨主题/语言/视图重挂保留状态。固定产物和附件元信息演示不表示真实Agent分析或上传。

91项程序检查通过，目标浏览器路径与产物切换已回放。独立接口、参考依据、检查范围和当前路线见 [v0.15 交付记录](PAGE_PATTERNS.md)。ES07.1/ES07.2完成；下一ES06.5；真实生产接入ES05未实施。


## 2026-10-10 · v0.16 引用与原文摘录

新增Citation/mountCitations（citation-components.mjs/css），研究列表引用列、Agent备忘与PDF网页预览复用同一原文浮窗。传入明确来源类型、定位与链接；同一时间一条，支持关闭/返回焦点与卸载清理，视口限制避开表格裁切。DataTable增加安全文本槽，引用按记录id绑定。原文有本地原件逐字检查，研究样稿与真实项目契约分别标注；不表示真实检索或附件分析。98项检查通过并完成目标浏览器回放；最新接口、边界、证据和队列见[ES06.5记录](PAGE_PATTERNS.md)。


## 2026-10-10 · v0.17 集中来源面板

mountSourcePanel接入研究列表和Agent产物：引用定位对应摘录，集中来源目录换条目，关闭恢复首次阅读位置和引用焦点。原生侧边dialog、独立滚动、语义主题与显式来源，102项程序检查及两处精确坐标回放通过。接口和边界见[ES07.3记录](PAGE_PATTERNS.md)。已有就地Citation/mountCitations接口保留；没有真实检索或全文加载。


## v0.18 · 完整报告组合

入口[research-report.html](research-report.html)，模块report-reader.mjs/css。mountReportReader(host,{tr,language:'zh'|'en',scrollContainer,state})返回{sourcePanel,getState(),destroy()}。getState为{figureView:'chart'|'data',top,left}，双语重挂传回；主题只改语义变量无需重挂。显式目录/摘要用原生hash历史，手动滚动仅更新目录，不改历史。--report-sticky-top / --report-anchor-offset共同处理报告顶栏定位。

当前是可嵌入的固定原创样稿组合，未提供任意报告内容Schema。REPORT_FIGURE为显式原创数据；validateReportFigure保留finite/null，不补值；resolveReportSection仅接受已知章节，非法hash不替换为来源。来源直接复用AGENT_CITATION_SOURCES与mountSourcePanel。图表/数据固定280px，C缺失、D零分别展示。数据可复用接口和真实检索仍未实施。105项检查与目标阅读链浏览器回放通过。设计规则见[共用原则](EDITORIAL_DESIGN_PRINCIPLES.md)，状态见[当前路线](PAGE_PATTERNS.md)。
