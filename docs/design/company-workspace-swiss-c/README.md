# Uteki 前台基线 C · 机构首页

## 2026-10-06 · 收敛为两套实际界面

用户确认保留本前台与真实研究工作台，并删除其他旧页面及不再使用的代码。本前台移除页面蓝图和旧版对照跳转；公司、Manager、报告、证据、组合决策与风险功能保留。Uteki Zero 目录中的报告样本、品牌解析和公司图标仍被本前台引用，继续保留。旧版原型不再提供独立页面；下文旧版对照链接属于历史记录。冻结副本 `docs/design/baselines/`、品牌封版与原始资料保持不变。

前后端保持同一仓库，职责分开；未来通过明确接口接入真实已发布研究产物。本轮只清理页面与导航，没有实现该接口、改变模拟身份或接入账户。检查记录见 [FRONTEND_DESIGN.md](../../FRONTEND_DESIGN.md)。

## 2026-10-06 · 持续风险跟踪

[Field 风险跟踪](http://127.0.0.1:8769/docs/design/company-workspace-swiss-c/?v=20261006-risk1#/manager/field?view=risks&risk=field-delivery-chain&status=all) · [North 待复核](http://127.0.0.1:8769/docs/design/company-workspace-swiss-c/?v=20261006-risk1#/manager/north?view=risks&risk=north-shared-growth&status=needs_review) · [首页风险摘要](http://127.0.0.1:8769/docs/design/company-workspace-swiss-c/?v=20261006-risk1#/institution/uteki?view=overview)

首页当前组合和 Manager 概览提供紧凑风险摘要；Manager 的「风险跟踪」采用状态筛选、左列表与右详情。Field 的同一交付风险连接两次决策，可以查看证据、当时的 Risk 意见、PM 回应、初稿与最终目标及复查条件。回应不等于解决，配置对照也不代表实际成交或单一风险造成了全部调整。

风险 → 决策 → 报告 → 返回保留原路径、筛选、阅读位置及焦点；各 Manager 的选择相互独立。来源固定作者、公司、报告、版本、章节和引用，不可用原文明确显示。四条风险均为具名虚构样本，没有启动真实 Risk Agent、自动止损、交易或账户服务。研究、既有持仓和公司名单保持原样。实现与检查记录见 [FRONTEND_DESIGN.md](../../FRONTEND_DESIGN.md)；本轮没有浏览器视觉验收。


## 2026-10-05 · 组合决策前台

[North 组合决策](http://127.0.0.1:8769/docs/design/company-workspace-swiss-c/?v=20261005-decisions1#/manager/north?view=decisions&decision=north-20260930-allocation&tab=allocation) · [风险与回应](http://127.0.0.1:8769/docs/design/company-workspace-swiss-c/?v=20261005-decisions1#/manager/north?view=decisions&decision=north-20260930-allocation&tab=risk) · [首页入口](http://127.0.0.1:8769/docs/design/company-workspace-swiss-c/?v=20261005-decisions1#/institution/uteki?view=overview)

先体验前台协作产物：左侧选择配置决定，右侧查看「配置变化／研究依据／风险与回应」。North 3 个、Field 2 个具名虚构情景，包含调整配置与维持不变。研究继续使用共享阅读器，链接固定公司、作者、报告及版本；返回保持决定、标签、滚动及焦点。概览、当前组合和操作历史均有入口。

这些决定的调整前、初稿与目标比例是独立设计情景，不是首页持仓的连续账本，不建立与已有交易事件的伪造因果关系。执行状态仅为待模拟执行或无需交易；没有实际成交与新收益。真实 PM / Risk Agent、交易与账户服务均未接入。界面沿用明快配色与主题切换，公司列表、报告正文及既有持仓数据未改。


## 2026-10-05 完整体验审查与报告优化

[当前页面](http://127.0.0.1:8769/docs/design/company-workspace-swiss-c/?v=20261005-ux1#/institution/uteki?view=overview) · [North 研究覆盖](http://127.0.0.1:8769/docs/design/company-workspace-swiss-c/?v=20261005-ux1#/manager/north?view=companies) · [报告阅读样稿](http://127.0.0.1:8769/docs/design/company-workspace-swiss-c/?v=20261005-ux1#/manager/north?view=report&company=alphabet&report=alpha-north-main&version=v2) · [PDF](../../../output/pdf/uteki-research-sample.pdf)

本轮已按用户授权先浏览走查、再修改；以下早期章节保留其当时的检查范围，最新结果以本节及 [完整记录](../../FRONTEND_DESIGN.md) 为准。修改前页面和静态依赖已冻结为 [102文件基线](../baselines/20261005-before-ux-review/README.md)。

- 研究覆盖四标签、等高卡、六项分页；每位 Agent 独立保留状态。
- 两种报告入口共用范围严格的目录，作者/公司、类型、标题联合筛选、八项分页与返回恢复。
- 完整报告以具体版次标题、判断、章节与全局证据编号呈现；原文和数据未改。三个字体模式继续可选。
- 首页侧栏展开不再跨容器断点导致双栏变单栏；事件聚合等推动结束后统一更新，保留详情与键盘焦点。Buy绿、Sell红、Report紫的浅底语义贯穿图表和操作历史。
- `report-directory.mjs` 负责只读筛选，`report-presentation.mjs` 负责网页/PDF共享内容；`report-reading.css` 与 `directory-controls.css` 限定报告样式；没有新框架或后端。

自动检查257项通过，实际完成报告往返、引用/章节、无结果、无报告、侧栏临界宽度、中英文与明暗主题走查。详细步骤、截图和局限见完整记录。减少动效与超出演示数量的分页是程序验证，不冒充系统设置/大量真实数据的视觉验收。PDF5页已逐页渲染复查。

复现PDF需显式传入所有scope和输出路径：

```sh
python scripts/build_research_sample_pdf.py --company alphabet --manager north --report alpha-north-main --version v2 --language zh-CN --output output/pdf/uteki-research-sample.pdf
```

要求本机 ReportLab、Node、指定字体可用；字体缺失明确失败，不自动换研究范围。该脚本是本地静态样稿工具，不是生产导出API。


## 最新迭代：2026-10-05 公司与 Agent 页统一

[公司概览](http://127.0.0.1:8769/docs/design/company-workspace-swiss-c/?v=20261005-entities1#/company/alphabet?view=overview) · [Agent 概览](http://127.0.0.1:8769/docs/design/company-workspace-swiss-c/?v=20261005-entities1#/manager/north?view=overview)

对象身份并入工具栏，固定栏目尾部呈现研究数量和模拟身份；去掉重复工作台标题和单独实体标题带。公司概览直接进入左栏目/右摘要；Manager 报告、覆盖和操作历史使用紧凑计数/筛选行，语义标题保留。主体信息、公司列表、三类关注、报告和表格文字尺度不变，机构主页不改。

94 项既有机构、Manager 与交互检查通过；额外核对 64 个双语实体视图的唯一标题、模拟身份、旧版入口及无重复 ID。机构页双语渲染内容的 SHA256 与本轮开始前一致。现有服务返回 HTTP 200，独立代码复核修正了 Manager 底部 padding 的选择器覆盖。没有浏览器或截图，实际效果由用户评审。

## 2026-10-05 首页精简

[查看精简首页](http://127.0.0.1:8769/docs/design/company-workspace-swiss-c/?v=20261005-compact1#/institution/uteki?view=overview)

机构首页合并工具栏和大标题，呈现一个投资总览标题、模拟身份、日期与币种。旧版对照从设计说明打开，所有显示偏好入口保留。取消非步骤的编号，收紧比较卡及曲线上方留白；收益数字、约 8:4 构图、亮暗主题和丝绸蓝 Logo 不变。公司与 Manager 页头沿用既有结构。窄屏页首允许换行，正文自然滚动。

检查：84 项既有机构渲染及控制器检查通过；双语页首、唯一标题、模拟来源、旧版入口与公司/Manager 边界直接核对通过；25 条入口/变更模块本地引用解析通过，脚本语法通过。现有预览 HTTP 200 且响应与本地入口一致。没有打开浏览器或截图，实际排版效果由用户评审。下一步查看精简首页后，再根据具体阅读问题收紧组合区说明。

## 基线记录

2026-10-04，用户已确认 C 的整体风格与机构首页构图，采用本目录作为后续前台持续迭代入口。v2、A、B 保留为历史对照，不覆盖或删除。

本次采纳明确的是整体视觉方向和机构首页构图，不表示公司、Manager、报告及所有交互细节已经逐项验收。此前工程检查未使用自动浏览器或截图；用户本次的视觉认可单独记录，不改写此前验证范围。收益、持仓与研究内容仍为明确标注的模拟样本；先继续优化前台，能力差距研究后置。

[打开 C 机构首页](http://127.0.0.1:8769/docs/design/company-workspace-swiss-c/?v=20261004-swiss-c1#/institution/uteki?view=overview) · [公司概览](http://127.0.0.1:8769/docs/design/company-workspace-swiss-c/?v=20261004-swiss-c1#/company/alphabet?view=overview) · [Manager 概览](http://127.0.0.1:8769/docs/design/company-workspace-swiss-c/?v=20261004-swiss-c1#/manager/north?view=overview)

## 这次改变什么

机构首页变为三部分：顶部单组 Agent 比较卡、左侧大曲线及事件、右侧当前组合。Agent 收益在比较卡中突出呈现；右侧环图、市值、准确快照日期与公司占比表作为一个完整阅读面，不再把同一收益重复展示。

主区域约 8∶4 分配，曲线与组合同时出现；不到 1000px 的可用宽度时自然上下阅读。机构标题 30px、比较收益 30px、正文 13–14px、元信息 12px。瑞士方向落实在非对称网格、清晰字号对比、准确对齐和结构留白，保持明快的图表色和适量功能圆角。

详细 token、示意线框和投研流程复核见 [VISUAL_PLAN.md](VISUAL_PLAN.md)。

## 保留的业务与交互

- 顶部 Agent 卡、曲线选择、明确前后按钮联动同一组合；双击及「展开持仓」继续查看历史。无自动轮播、滚轮切换或悬停改选择。
- Buy/Sell 在线上、报告在下方；事件浮层保留准确日期、归属和报告版本。图形与标记由同一日期/收益几何定位，CSS 不单独拉伸曲线。
- 饼图、持仓占比及公司报告入口继续联动；报告返回保留原 Agent 和当前选择。
- 公司与 Manager 保留既有三层外框、原公司名单、研究数据与空状态；长报告按 17px / 1.85 阅读。
- 保留明暗主题、中英界面、模拟数据身份、币种和快照日期。雨滴与公司 icon 只读使用原素材；色卡入口以手动展开保留。

## 文件职责

`swiss-study-c.css` 负责 C 的构图、壳层与阅读样式；`index.html` 加载独立样式；`render.mjs` 增加保持当前路由的原版对照入口。机构 DOM、图表几何与控制器的 C 适配由主任务维护。桌面右侧将 Agent 身份、快照日期和市值放在约 136px 环图旁，减少竖向叠放；持仓行约 38px。历史展开后主体改为单列，当前配置在历史后继续阅读。

## 本轮检查与限制

主任务完成 99 项机构、控制器、几何和事件检查，包含 SVG 坐标与实际交易标记对应、双栏实际绘图区宽度聚合。`render.mjs`、`app.mjs`、`institution-view.mjs` 语法通过；86 条本地静态引用可解析；原版、A、B 的 141 个文件哈希未变；现有 8769 服务中的 C 入口返回 HTTP 200。

样式子任务另外核对 7 条 HTML 本地资源引用、CSS 分块括号及 DOM 合同对应。检查没有使用浏览器或截图；CSS 分块核对不等于完整 CSS 解析、真实布局或视觉验收。

本目录现为已采纳的前台基线，未部署、未接入真实账户或启动模型。数据服务能力差距研究后置；持仓历史折线与各页面细节仍可继续优化，不因整体风格获认可而标记完成。

下一步直接在 C 基线上继续前台细化。历史原版入口保留，可返回同一页面作对照。

## 字体对照（2026-10-04）

右上角 Aa 提供「瑞士 / 书刊混排 / 经典宋体」，默认保留已认可的瑞士方案。混排在标题与报告正文中使用 Times New Roman + 宋体，数字与控件保留无衬线；偏好保存在本机。原生字体回退与官方依据见 [TYPOGRAPHY.md](TYPOGRAPHY.md)。本次 73 项控制器检查通过，涵盖切换、持久化、阅读锚点、作用域与存储失败；未进行浏览器字形或换行检验。

## 丝绸蓝雨滴（2026-10-05）

用户先要求优化侧栏玻璃 Logo。当前改用 `assets/uteki-drop-silk.png`，从封版原始 `apps/logo_studio/assets/uteki-silk.jpeg` 仅裁出雨滴并确定性抠底，保留原形态和渐变；旧玻璃 PNG 留作对照。来源参数、哈希及像素核对见 `assets/uteki-drop-silk.source.json`，复现脚本为 `assets/extract-uteki-silk.py`。

已查看透明资源、核对 S 形开口和边缘透明、内部原色一致，以及原图封版哈希；三类工作台双语导航均只引用一张新雨滴，本地资源返回 HTTP 200。未开浏览器或作页面截图验收。布局及字体切换保持；重复标题与留白优化按用户要求后续处理。
