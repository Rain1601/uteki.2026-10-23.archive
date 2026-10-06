# C 基线的字体对照

2026-10-04。用户认可 C 的其他页面方向，并提出 Times New Roman 与宋体的设想。本轮提供字体组合对照，保留已认可的布局、明快图表色、模拟数据和证据状态。默认继续使用当前瑞士方案，不把字体对照自动记为用户已采纳。

## 官方资料能确认什么

| 字体 | 官方资料支持的特点 | 对 Uteki 的设计判断 |
| --- | --- | --- |
| Helvetica | MoMA 的展览说明强调其清楚、适度比例和中性的现代表达；Monotype 将其描述为低笔画反差、比例均衡的无衬线字体。[MoMA](https://www.moma.org/calendar/exhibitions/38)、[Monotype](https://www.monotype.com/resources/articles/complicated-legacy-helvetica) | 适合当前紧凑导航、数据比较与中性工作台，也是 C 目前使用的方向。 |
| Univers | Adrian Frutiger 设计的字族。Monotype 强调其在字重、字宽变化中保持一致的系统性。[Monotype](https://www.monotype.com/resources/videos/good-type-family)、[Linotype / MyFonts](https://www.myfonts.com/collections/univers-font-linotype) | 可作为理解瑞士字体系的另一个参照，重点是字级系统，而非只指定 Helvetica。本轮不加载 Univers。 |
| Times New Roman | Microsoft 记载它为《泰晤士报》设计，1932 年首次出现，强调可读性与版面效率，也用于书刊、报告及办公文档。[Microsoft](https://learn.microsoft.com/en-us/typography/font-list/times-new-roman) | 有明确的书刊、正式报告气质，可以进入研究标题和正文；密集金融数字继续单独用无衬线。 |
| SimSun（宋体） | Microsoft 将其列为简体中文的 serif / mincho 笔画风格，随相应 Microsoft 产品提供。[Microsoft](https://learn.microsoft.com/en-us/typography/font-list/simsun) | 与 Times New Roman 搭配可以形成中英书刊阅读风格。小字号界面不强制使用细宋体。 |

右列是本轮设计判断，不是厂商对金融界面的实测结论。瑞士风格也不是某一个字体名称：本稿仍依赖既有的非对称网格、信息层级和对齐，字体只调整阅读语气。

## 三个选项

| 界面选项 | 标题与正文 | 导航、操作和数据 | 用途 |
| --- | --- | --- | --- |
| 瑞士 / Swiss | C 现有 Helvetica 系西文和系统中文无衬线，原字级保持 | 同一无衬线体系 | 默认，保持已经认可的效果 |
| 书刊混排 / Editorial mix | 实体标题、报告标题和长文使用 Times + 宋体；研究正文 18px / 1.9 | 导航、按钮、表格、曲线、收益数字、日期保留无衬线 | 推荐先比较，判断书刊阅读能否补充工作台气质 |
| 经典宋体 / Classic serif | 在混排基础上，区块标题、公司显示名称和较大说明文字也使用 Times + 宋体 | 控件、元信息和独立金融数字继续保留无衬线 | 展示用户最初设想的更完整文字风格，避免 11–12px 宋体铺满页面 |

正文中的普通叙述数字随段落字体；结构化金融数值、日期和图表刻度明确采用无衬线及等宽数字特性。是否呈现等宽字形还取决于实际本机字体的支持，不将 CSS 声明当作已测量的字形结果。

## 本机字体与回退

无衬线序列：`Helvetica Neue → Helvetica → Arial → PingFang SC → Microsoft YaHei → sans-serif`。

衬线序列：`Times New Roman → Times → Songti SC → STSong → SimSun → serif`。

浏览器逐个寻找已安装且含有所需字形的字体：西文可能来自 Times，中文来自 Songti SC；不是把一整段固定为同一个字体文件。在这台 Mac 上优先给出 Songti SC 的名字，不强求 Windows 的 SimSun。不同系统最终可能采用不同回退，字宽和换行也可能变化。

主任务已确认本机存在 `/System/Library/Fonts/HelveticaNeue.ttc`、`/System/Library/Fonts/Supplemental/Songti.ttc` 和 `/System/Library/Fonts/Supplemental/Times New Roman.ttf`。这证明字体文件存在，不等于浏览器最终字形选择或显示效果已经检查。

不下载、复制、嵌入或远程加载商业字体，不添加 `@font-face`。保留本机字体的正常回退；没有将 Univers 写入默认字体链或伪称已安装。

## 实施与边界

`typography.css` 应在 C 主样式之后加载。根元素 `data-typography` 接受 `swiss`、`hybrid`、`editorial`；没有属性时与 Swiss 默认相同。`--font-sans`、`--font-serif` 和 `--font-reading` 分别表达控件、书刊与阅读字体。

右上角沿用原生下拉框，`.typography-control` / `#typography-select` 控制样式；主任务负责状态保存、选项和行为检查。字体切换不修改文本语言、报告版本、模拟身份、Agent 选择或数据作用域。

本轮子任务只新增本文件和 `typography.css`，并静态核对字体映射、实际摘要容器、选择器与远程资源声明。报告摘要的直接文本及其后 summary 一并使用书刊正文，摘要标签保留原有 12px 无衬线。主任务已完成 73 项控制器检查，包含字体下拉、持久化及阅读锚点；这不等同浏览器布局检查。

未打开浏览器或截图，未验证最终字形与换行。先由用户切换比较，再决定是否采纳某个字体组合。
