# Anthropic → Editorial 四项对照 · 2026-10-10

当前位置 ES04.1。本轮用户要求下，对 Header、Sidebar、Table、PDF 做浏览器或 PDF 原件实看；原截图、v0.1 历史与 v0.2 保留。颜色不用相同，学习字体角色、间距与层级。下面的数值取本次 1280×720 浏览器与原 PDF，不是官方公开组件规范。

| 项目 | 原设计实测 | v0.1 | v0.2 的选择 |
| --- | --- | --- | --- |
| Header | Project Swap 文章导航：15 / 21px Sans；主栏68px；左右64px | 72px高、36px边距、13px导航；额外技术标签 | 68px高、64px边距、15 / 21px导航，标签移到样册工具栏；品牌/链接/操作均 props |
| Sidebar | Project Swap：172px目录；12 / 14.4px Sans；12px垂直行间距；sticky top92px；正文640px；目录至正文84px | 阅读目录150px、11px；正文18 / 32.4px，宽720px | 阅读目录172px、12 / 14.4px、sticky92px；正文20 / 31px、640px；宽屏列距84px；当前项字重600 |
| Table | Haiku benchmark：Sans14 / 19.6px、th600；价格表：th/td14 / 19.6px，10×12px单元格，完整细网格。价格表容器继承 Serif，实际部分内容为Sans，不能只读table祖先字体 | 13px正文、11px弱表头；名称硬编码交互；18px行内距 | Sans14 / 19.6px、表头600、正文400、14px行距（紧凑10px）；ruled与grid两变体；显式interactive/rowKey/caption；数值右对齐为适配 |
| PDF | Project Swap Letter612×792pt；封面36ptSerif；节标题24ptSans；正文11ptSerif；页脚8ptSans | A4、35pt标题、12pt正文、脚本散落参数 | Letter、36/44封面、24/30标题、11/17.5正文、8/10页脚；共享json控制纸张/边距/角色/表格/页脚；英文嵌入字体 |

Header 基准取文章页。官网首页使用了不同导航字体变体（本轮 DOM 对其链接测得20px Serif），没有把这些互不相同的页面强行归为一个官方值。Sidebar 的应用目录、表格金融对齐及三套主题是适配。

## 原来源

- https://www.anthropic.com/research/project-swap：文章Header与目录。
- https://www.anthropic.com/claude-haiku-5-5：两种表格；定价表区域截图实看。
- https://www-cdn.anthropic.com/3818cf6119b88f9714d995f6549fa8aac0bd5ab5/Project-Swap.pdf：封面及第二页，未核查全部26页。

可查看 `comparison.html`：逐项原件截图与当前截图，PDF两页渲染，附v0.1和可交互v0.2入口。API见 `COMPONENT_API.md`，PDF细节见 `PDF_COMPARISON.md`。原件截图仅作本地设计研究依据，不作为新UI资产。

## 验收与缺口

已核查源码/契约、独立合成行键与数据边界、当前浏览器四项外观、三主题状态不变、两密度、中英切换、英文PDF页内边界与两页渲染。英文网页和PDF使用同一份本地Liberation字体，字形不是原站专有字体。中文网页固定本地 Noto；PDF中文与通用分页未实现；浏览器打印、跨平台渲染与最终用户审美确认仍未完成。
