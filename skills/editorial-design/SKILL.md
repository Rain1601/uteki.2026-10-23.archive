---
name: editorial-design
description: Create or refine editorial-style pages and reusable UI interactions inspired by Anthropic's content hierarchy. Use for reading, research reports, dashboards, lists, Agent tasks and settings when this editorial style is requested or is the established project baseline; supports independent palette and task-layout configuration.
---

# Editorial Design

用字体层级、内容节奏和完整交互建立编辑感。颜色与布局是独立输入，不把米色、衬线标题或等宽卡片网格当作风格本身。这是项目沉淀的方法与源码，不是 Anthropic 官方组件库。

## 先确定当前任务

从用户指令和现有页面确定：读者、主要对象、主要动作、真实内容与状态、已有框架/组件。写一个可判定例子：输入→操作→可见结果→返回。沿用已认可行为与真实数据，少量改动优先复用；不用设计任务替换业务含义。只在缺失信息实质影响结果时问用户。

## 稳定的样式原则

- 主次来自阅读顺序：页首提供方向、范围和主要动作，随后展开正文、比较或操作。卡片表示独立对象，不给每段内容都套卡片。
- display 表达、reading 长文、ui 结构操作、numeric 数字。中文覆盖与英文配对分别考虑；控件不强制衬线。默认间距 4/8/12/16/24/32/48/64/96，密度改变间距而不隐藏依据。
- 正文约 640px 是起点，宽图/表可超出版心；任务与 Dashboard 使用自己的容器。用细线、留白与适度的字号差建立层级，不靠堆阴影。
- 颜色通过语义角色配置。先用命名色卡，也可用完整角色 JSON；同一色卡能用于不同布局，同一布局可换色卡。阅读 [references/palettes.md](references/palettes.md) 获取字段、例子与验证。

## 交互契约

- 动作靠近对象。展开、详情、媒体、图表/数据切换保留上下文；关闭证据面板恢复原阅读坐标与触发焦点。高级设置放在通用设置之后，展开只改变下面的区域。
- 选中对象、筛选、排序、任务阶段、图表模式与阅读状态由调用方持有，换色/换语言不重建业务状态。需要持久化时明确范围，不默认写账号或报告内容。
- 稳定 ID 贯穿列表、表格、图表和引用；0、null、负值与单位分别保留。图表不能通过动画补值，来源组件不能编造原文。
- 空、加载、错误、待确认和完成分别有可读文字。未知进度不造百分比；草稿、有效预览与保存值分开。键盘焦点可见、Escape 有正确回程，减少动态时跳过非必要动画。
- 页面形态与动效按任务选择，不把所有交互画成方块流程图。展开媒体、局部图片检查、共享数据点、细线进度、正文注释可以各有合适的表达。

## 选择实现资源

阅读 [references/composition.md](references/composition.md)，只选当前页面需要的模式。报告内容迁移参考 [references/report-reuse.md](references/report-reuse.md)。需要现成组件时读 [references/components.md](references/components.md) 并检查相应源码。

`assets/editorial/` 是本地 v1 组件快照：Vanilla ES modules + CSS，包含可运行 `starter.html`、命名色卡与 JSON 配置例。无需连接原仓库或付费服务。复制所需模块和其相对依赖，保持目录关系；在现有 React/Vue 项目中按既有架构适配接口，不为套用 skill 改换技术栈。文本渲染器转为框架组件时保留身份、校验与状态职责，不直接塞不可信 HTML。

基础样式有全局 body/control 规则；在已有产品中按宿主范围隔离。便携样例使用系统字体，不声称与原型字形完全一致；用户许可的字体可按角色配置。本仓库原型另有本地字体与两页 PDF，参考路径见组件说明，PDF 不属于便携包的通用导出能力。

## 完成与验证

检查当前实际路径与受影响边界：身份/数值、动作状态、引用出处、语言/主题保留状态、输入失败时旧状态。新增脚本必须真实执行。色卡通过 9 组文字角色检查不等于整页可访问性审计；另看焦点、图表、禁用/状态和实际使用背景。

浏览器检查按用户要求或具体浏览器问题做，不默认生成多视口截图矩阵，不把程序通过写成审美获认可。交付可用页面/组件、采用的色卡与布局、已验证行为和剩余范围。模拟内容与真实执行明确区分。此 skill 不授权付费模型、发布、上传或后端接入。
