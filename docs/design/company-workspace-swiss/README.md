> **2026-10-06：旧页面已退役。** 本目录不再提供独立页面；旧页面及其专用代码、测试已删除。当前使用 [Swiss C 投研前台](../company-workspace-swiss-c/README.md) 和 [真实数据工作台](../../../apps/review_workbench/README.md)。以下文字保留为历史记录，其中旧启动命令与页面链接不再适用。保留的原始素材、来源记录和冻结版本仅用于追溯。

# Uteki · Swiss study A

这是 2026-10-04 在用户授权下复制的独立瑞士风格试稿。原版 `company-workspace-v2` 没有修改；本稿尚未被采纳为产品设计基线。

- [机构总览](http://127.0.0.1:8769/docs/design/company-workspace-swiss/#/institution/uteki?view=overview)
- [公司概览](http://127.0.0.1:8769/docs/design/company-workspace-swiss/#/company/alphabet?view=overview)
- [Manager 概览](http://127.0.0.1:8769/docs/design/company-workspace-swiss/#/manager/north?view=overview)
- [原版](http://127.0.0.1:8769/docs/design/company-workspace-v2/#/institution/uteki?view=overview)
- [视觉计划与验收边界](VISUAL_PLAN.md)

请使用本地 HTTP 预览，直接打开 file 地址会被 ES Modules 与资源读取限制。页眉中的「Swiss study A / 原版」入口保留当前业务路由，便于在同一家公司、Manager 或报告上比较。

## 改了什么

新样式独立在 `swiss-study.css`：统一字级、纵向基线、间距节奏、数据字形与紧凑导航；机构页曲线和组合使用连续纸面，研究页使用清楚的索引与较宽正文，Manager 页使用对齐的数字、表头与覆盖分栏。品牌图形、公司图标与用户选定的明快图表色系不改动。

组件及交互代码从原版复制。仅 `index.html` 新增试稿样式入口、标题与自身预览路径，`render.mjs` 增加保留路由的原版链接。其余复制的运行与数据文件逐字保持一致。原版业务数据与本地图标注册表仍从同层级共享路径只读取得，不嵌入另一份会漂移的公司目录。

机构 / 公司 / Manager、原生阅读滚动、手动 Agent 切换、互动饼图、事件浮层、持仓历史展开、报告版本与返回均沿用原控制器。本机显示语言、主题和图表色卡偏好与原版共享；它们不是业务数据。全部收益、持仓和研究继续标注为明确的虚构样本。

## 检查

2026-10-04：机构渲染、Manager 渲染与真实控制器模拟 DOM 的 89 项既有检查通过，涵盖 Agent 选择、配置图交互、事件分组与详情、报告身份与返回、各实体隔离、键盘与 hover、主题和语言。`render.mjs` 语法检查通过，7 个 HTML 静态资源及所有本地模块依赖可解析。复制时记录的原版 37 个文件哈希完全一致，证明本轮没有改写原版。

这些检查确认数据与代码行为；不是浏览器布局或用户美感验收。持仓历史的现有日期节点与小趋势图未改成新的大折线图，其细节迭代继续留到后面。未调用模型、接入账户或部署。

## 比较顺序

1. 先看机构总览的标题 / 投资表现 / Portfolio 是否更容易扫读。
2. 点公司或 Manager，比较统一字级与列表密度；再打开一份报告检查阅读感。
3. 页眉打开原版同一页面，决定哪些视觉规则值得保留。认可之前不迁回原版。

## 本轮定点浏览器核对

已打开机构总览，确认资源图像加载；点击 Field 后显示其 5 家公司加 15% 现金，再返回 North。已保存 `preview-institution.jpg`。这仅覆盖本次机构页和该切换，没有声称公司页、Manager 页或其他视口完成视觉验收。
