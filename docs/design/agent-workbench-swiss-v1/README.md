> **2026-10-06：旧页面已退役。** 本目录不再提供独立页面；旧页面及其专用代码、测试已删除。当前使用 [Swiss C 投研前台](../company-workspace-swiss-c/README.md) 和 [真实数据工作台](../../../apps/review_workbench/README.md)。以下文字保留为历史记录，其中旧启动命令与页面链接不再适用。保留的原始素材、来源记录和冻结版本仅用于追溯。

# Uteki 后台瑞士排版预览 / Swiss workbench preview

独立视觉探索，使用与 [现版后台](../agent-workbench-v1/README.md) 相同的任务、产物和交互。工程阅读型为本页默认方案；两种风格均待用户评审，尚未成为 Uteki 的通用界面规则。

An independent visual exploration using the current workbench’s tasks, artifacts and interactions. Engineering is this preview’s default; neither variant is an approved product-wide style.

## 打开 / Open

已运行本地服务时：[独立预览](http://127.0.0.1:8769/docs/design/agent-workbench-swiss-v1/) · [现版对照](http://127.0.0.1:8769/docs/design/agent-workbench-v1/)。

If no local server is running, start one from the repository root:

```sh
python3 -m http.server 8769 --bind 127.0.0.1
```

使用 HTTP 地址打开；ES modules 无法可靠地通过 `file://` 使用。页面不连接模型或执行后端；所有任务、产物和评分均为明确标记的虚构演示。

Use the HTTP address rather than `file://`. The page connects to neither a model nor an execution backend. Tasks, artifacts and scores are explicitly labeled fictional samples.

## 对照方案 / Variants

| 方案 / Variant | 重点 / Focus |
| --- | --- |
| 工程阅读型 / Engineering | 紧凑标题、清晰元信息、对齐的正文与证据区域。Compact headings, legible metadata, aligned work and evidence areas. |
| 编辑排版型 / Editorial | 同一结构，较宽松行距与间距、较窄阅读列、砖红强调。The same structure with more reading space, a narrower text measure and red accents. |

顶部切换只改变 `html` 的 `data-preview-style`，不会重建 `#app`、切换任务、发送要求或清空草稿。预览工具条跟随工作区中英切换；用户仍使用原生滚动。窄窗口通过水平滚动保留任务与产物各栏，是待评审的实验方案。

The top switch only changes `html[data-preview-style]`; it does not rebuild `#app`, switch tasks, send instructions or clear drafts. Preview labels follow the workbench language. Native scrolling is preserved; narrow windows retain all panes through horizontal scrolling, pending user review.

## 体验路径 / Review path

1. 打开 GOOGL 现金流任务的评审页，写一条尚未保存的意见。Open Review for the GOOGL cash-flow task and enter an unsaved note.
2. 打开对应产物，再切换两种排版；确认仍为同一任务、运行、意见与产物。Open its artifact and switch typography; check that the task, run, draft and artifact remain selected.
3. 打开 Analysis 的设置齿轮，查看配置后返回；切换中英，比较信息密度。Open the Analysis settings gear and return, then switch languages to compare reading density.

评审、追加要求和草稿沿用现版的当前页面状态，刷新会清空。追加要求只创建待执行演示尝试，不产生新的 Agent 回复或研究结论；两种排版的切换不会刷新页面。现版对照链接另开页面，各页面的临时输入不共享。

Reviews, instructions and drafts remain in the current page and clear on refresh. A follow-up creates a pending demo attempt without generating an agent reply or research result. Typography changes do not refresh the page. The baseline link opens a separate page; temporary input is not shared between pages.

## 实现与检查 / Implementation and checks

- `index.html` 直接加载 `../agent-workbench-v1/app.mjs`；其模型、渲染与演示数据继续使用原文件。The entry loads the existing application and its original model, renderer and fixture.
- `style.css` 导入现版基础 CSS，新增样式限于独立预览。The stylesheet imports the baseline with preview-specific overrides.
- `preview.mjs` 仅处理排版切换和预览工具条双语。The preview module handles typography selection and bilingual preview labels only.
- `preview.test.mjs` 检查工作区状态保持、双语同步、选项范围及本地引用。Tests cover retained state, language synchronization, option scope and local dependencies.

```sh
node --test docs/design/agent-workbench-v1/model.test.mjs docs/design/agent-workbench-v1/view.test.mjs docs/design/agent-workbench-swiss-v1/preview.test.mjs
node --check docs/design/agent-workbench-swiss-v1/preview.mjs
```

2026-10-04：31 项聚焦检查通过；脚本语法通过；新入口、样式、共享模块与 Logo 共 9 个本地 HTTP 请求返回 200。未进行浏览器视觉验收，代码检查不代表阅读体验或跨尺寸布局已获认可。尚未连接真实任务、持久化评审或执行服务。

2026-10-04: 31 focused checks and JavaScript syntax passed. Nine local HTTP checks covering the entry, styles, shared modules and logo returned 200. No browser visual acceptance was performed; these checks do not establish readability or responsive-layout acceptance. Real tasks, persistent review and execution services remain unconnected.

下一步：先对照两种方案评审文字密度与证据阅读，再依据反馈调整；后台真实执行接入独立推进。

Next: compare reading density and evidence inspection in both variants, then refine from feedback. Real execution integration remains separate.
