# 案例阅读组件 v0.6

当前 ES04.7a：将 ES01.3 客户案例研究落实到现有阅读页。入口：[北线研究](workspace.html?view=reading&record=north)。这是实际工作的设计原型页面，数据仍是原有虚构样例，不是生产公司研究或客户证言。

## 来源观察

- [Figma 客户案例](https://claude.com/customers/figma)：本轮浏览器实见与DOM核查。分类标签、衬线导语、公司元信息、结果摘要、导读前视频、分章节正文、署名引用。提炼StoryLead、FactRail与PullQuote；没观看完整客户视频，不声称复刻镜头和时序。
- [Notion 客户案例](https://claude.com/customers/notion)：官方页面结构核查，视频在成果章节。说明媒体应该跟随叙事用途，不能固定在每页首屏。
- [Epilepsy Foundation访谈](https://claude.com/customers/epilepsy-foundation-qa)：官方页面结构核查，问题组织章节。访谈组件未在本轮实现。
- [Tracing thoughts](https://www.anthropic.com/research/tracing-thoughts-language-model)：本轮DOM核查，分章节问题、带解释图注的机制图、介绍视频。核查到的机制图是PNG，不能称它们是动态素材。
- [Global workspace](https://www.anthropic.com/research/global-workspace)：本轮DOM核查到的局部图同样为PNG。复用多阶段机制图的解释组织，不将图解称作模型内部真实执行。
- [Interactive tools](https://claude.com/resources/articles/interactive-tools-in-claude)：本轮DOM核查，多个工具段落分别嵌视频，末尾静态图。未实际观看视频完整内容。
- [Inline visuals](https://claude.com/blog/claude-builds-visuals)：上一轮实见的YouTube/GIF/PNG组合，为本轮原创图解的正文嵌入方式提供依据。

## 实现与定制

`story-components.mjs`导出：

- `StoryLead({eyebrow,title,summary,facts})`：案例导语与事实栏，字段由调用方提供，0、负值、null分别呈现；所有文案转义。
- `PullQuote({text,attribution})`：正文引用与出处/署名；当前页面明确原创编辑札记，非客户证言。
- `mountExplainer(host,{title,caption,steps,duration,labels})`：2–6个步骤、唯一ID、有限正时长，标题/内容由调用方提供。统一进度驱动SVG节点、流动线、说明与进度条；默认静态，Play/Pause/Replay、步骤选择、原生键盘进度控制、播放结束停止。
- 返回`pause()`、`getState()`、`destroy()`。页面重渲染先销毁旧实例，移除全局监听并取消动画帧。切记录、语言或主题后回到静态首步，避免旧记录仍在播放。

尺寸、字体、面板颜色使用现有语义tokens与独立作用域CSS，支持Paper/Mineral/Plum。无第三方库和远程素材；不会下载或复制客户肖像、视频和专有字体。

页面把同一记录的身份、数值、变化和来源边界作为4步。原始数据不变；动画不补充基期或业务结论。URL仅接受已知record与reading视图，非法参数保留正常概览。

## 验证与边界

31项组件/状态契约测试通过，新增测试验证时间轴终点、重复身份、异常时长、转义与0/负值/缺失。浏览器实际核查：步骤选择→对应文案；播放→进度变化→自动停止；End键到末步；图谱工作室缺失、共同地带负值、长线观察零值；英文与Mineral切换；播放中离开阅读页→旧图解移除→返回为静态。

已实现后台暂停与减少动态偏好监听，但本轮未切换系统偏好或专项核查后台行为。未覆盖触屏、屏幕阅读器矩阵或长视频控件；不是已完成所有媒体能力。英文操作检查通过，不将其称为全部双语视觉验收。

## 队列

| ID | 行动 | 依赖 | 状态 |
|---|---|---|---|
| ES01.2 | 多场景来源图谱 | ES01 | 已交付 |
| ES01.3 | 客户案例与文章媒体研究 | ES01.2 | 本轮6来源核查，持续探索 |
| ES04.1–02 | 基础组件与中英PDF | ES02 | 已交付；PDF认可 |
| ES04.3 | 长文PDF | ES04.2 | 暂缓 |
| ES04.4–05 | 工作台与表单反馈 | ES03 | 已交付 |
| ES04.7a | 案例组件与分步动态图解入页 | ES01.3、ES04.4 | 本轮完成，当前位置 |
| ES04.7b | 可展开媒体与视频/静态替代 | ES04.7a、明确媒体输入 | 下一具体项，未开始 |
| ES04.6 | 日期、多选、全局检索 | ES04.5 | 保留队列，未开始 |
| ES04.7其余 | 文件树、复杂表格与画布 | 相关前项 | 未开始 |
| ES05 | 生产迁移 | ES04、明确页面范围 | 未开始 |

用户最新要求优先把来源设计落实到页面，因此ES04.7a/b先于ES04.6；保留原队列且不宣称全部ES04.7完成。


## 2026-10-10 · ES04.7b 正文媒体交付

正文内视频/曲线/轨道均可展开，关闭暂停且回到正文。新增createArticleVideo/createKineticFigure/mountMediaWindow；原生视频与原创7秒素材已实际播放。ES04.7b完成，下一ES04.7c，ES04.6保留队列；详见[复用接口与检查](READING_MEDIA.md)。旧图解拖动先读值再暂停，避免重绘覆盖输入。
