# Editorial Design System v1 · 使用说明

这是 Anthropic 启发的本地编辑式设计资产，不是 Anthropic 官方组件包。当前入口是 [系统样册](system.html)，交付范围与证据见 [最终交付记录](DESIGN_SYSTEM_DELIVERY.md)，设计判断见 [共用原则](EDITORIAL_DESIGN_PRINCIPLES.md)。旧阶段文档保留历史，不作为当前能力清单。

## 先运行，再选择需要的组件

已有本地服务可直接打开 `http://127.0.0.1:8879/editorial/system.html`。另一台机器可从仓库根目录启动静态 HTTP 服务，例如：

```sh
python3 -m http.server 8881 --directory docs/design/dashboard-demos
```

然后打开 `http://127.0.0.1:8881/editorial/system.html`。ES modules、JSON 与字体需要 HTTP 服务；不要直接用 `file://` 打开页面。当前不要求构建工具、React 或外部字体 CDN。保持模块、CSS、`fonts/` 和相对链接的目录关系。

系统样册用于查找入口与复用边界；[组件页](index.html)用于操作组件；[工作台](workspace.html)、[报告列表](report-library.html)、[报告阅读](research-report.html)、[设置范例](editorial-settings.html)和[双语 PDF](pdf-bilingual.html)用于查看实际组合。

## 最小 JS / CSS 接入

先加载共享字体、角色与基础样式，再加载所用组件的 CSS。下面是一条完整引用链的示例，文本明确为原创说明：

```html
<link rel="stylesheet" href="./style.css">
<link rel="stylesheet" href="./compound-components.css">
<link rel="stylesheet" href="./citation-components.css">
<link rel="stylesheet" href="./source-panel.css">
<main id="example"></main>
<script type="module" src="./example.mjs"></script>
```

`example.mjs`：

```js
import {DataTable} from './editorial-primitives.mjs';
import {Card} from './compound-components.mjs';
import {Citation} from './citation-components.mjs';
import {mountSourcePanel} from './source-panel.mjs';
import {themeCSS, componentCSS} from './tokens.mjs';

const host = document.querySelector('#example');
document.body.style.cssText = themeCSS('paper') + ';' + componentCSS();
host.innerHTML = Card({
  id:'example-card', title:'阅读说明', description:'先比较数值，再核对原文。'
}) + DataTable({
  rowKey:'id', caption:'原创接口样例，非财务数据', locale:'zh-CN',
  rows:[{id:'zero',name:'零',value:0},
        {id:'gap',name:'缺失',value:null},
        {id:'negative',name:'负值',value:-8}],
  columns:[{key:'name',label:'记录'},
           {key:'value',label:'样稿值',numeric:true}]
}) + Citation({id:'example-note',label:'[1] 核对说明'});

const sourcePanel = mountSourcePanel(host, {
  scrollContainer:document.scrollingElement,
  sources:[{
    id:'example-note', title:'原创说明', kind:'authored-specimen',
    text:'此处是调用方编写的示例说明，不是外部来源原文。',
    caption:'接口示例 · 非研究依据', locator:'代码示例',
    href:'./QUICKSTART.md'
  }],
  labels:{title:'来源',returnToReading:'回到阅读位置',
          search:'查找已有摘录',clearSearch:'清除',
          noResults:'没有匹配摘录',results:'匹配摘录'}
});

// 当前页面或宿主负责调用；卸载前先清理组件。
function disposeExample() {
  sourcePanel.destroy();
  host.replaceChildren();
}
```

无状态渲染函数返回安全 HTML，调用方持有数据和业务状态。`Card` 的 `data-card-action/data-card-id`、`ItemList` 的 `data-item-id`、表格的 `data-sort/data-record` 均是动作入口；调用方绑定事件并按稳定身份更新数据，不按显示行号更新。

有交互的 `mount…` 或 `create…` 接口需按各自返回对象卸载。不要把同一组件重复挂进同一宿主。`mountSourcePanel` 与 `mountTooltips` 返回 `destroy()`；报告与 Agent 挂载器还提供 `getState()`。切语言时先取得状态、销毁旧实例，再以同一内容和状态挂载。主题只改变语义变量时无需重挂。

## 报告模型与阅读状态

`report-reader.mjs` 支持显式报告模型，不再要求固定三章。可以先传入命名样稿，再以 [report-content.mjs](report-content.mjs) 的字段作为最小合同：

```js
import {mountReportReader} from './report-reader.mjs';
import {READING_CONTINUITY_REPORT} from './report-content.mjs';
let language = 'zh';
let reader;
function renderReader() {
  const state = reader?.getState();
  reader?.destroy();
  reader = mountReportReader(document.querySelector('#report-host'), {
    report:READING_CONTINUITY_REPORT,
    language,
    tr:(zh,en) => language === 'zh' ? zh : en,
    scrollContainer:document.scrollingElement,
    state
  });
}
renderReader();
```

加载 `report-reader.css`、`citation-components.css`、`source-panel.css` 和共享 `style.css`。有固定顶栏时设定 `--report-sticky-top` 与 `--report-anchor-offset`，两者应与实际顶栏总高度一致；现有独立报告页使用 140px。

报告模型显式给出 `id/kind/date`、双语 `title/kicker/deck/scope`、`summaries/sections/figures/sources`。章节块支持 paragraph、quote、figure、details、boundary、sources；引用与图表使用精确 ID，不接受任意 HTML。当前合同限定 `authored-specimen`，不是自动研究、富文本编辑器或真实报告后端。未知、空、非法报告明确失败，不能依赖缺省命名样稿补业务内容。

报告状态包含报告身份、章节、偏移、双轴坐标、各图独立模式及折叠状态。把它传回**同一报告**；切另一报告取得另一份状态。示例报告列表和阅读页使用 `sessionStorage` 保存本标签页的筛选、排序和阅读状态，存储不可用时显示提示。其他组件不会自动获得这套持久化。

## 身份、数值与来源

- 记录、章节、图表、动作与来源使用稳定唯一 ID；排序和主题切换不能改身份。
- `null` 表示明确缺失；`0` 是已知零值；负值保持负号和零轴方向。表格数字列显式声明类型与单位，不能把缺失补成零。
- `ChartFrame` 仅接受非负有限值；需要负值或缺失时使用 `SignedBars`、`mountLinkedCharts` 或报告的共享零轴图形，不绕过校验。
- 来源面板显示调用方提供的摘录、caption、locator 和安全链接。搜索只在已有公开字段中筛选；不抓取全文，不验证事实，不生成缺失出处。
- `Citation` 的 ID 必须指向本次挂载的来源。点击引用清除旧面板查询并定位对应摘录；换来源保持首次打开时的阅读返回点。

## 主题与双语

`themeCSS('paper'|'mineral'|'plum')` 输出语义颜色；也支持完整六位十六进制角色对象。自定义主题必须提供全部角色，具体名称以 `themes.paper` 为准。格式校验不等于自定义颜色可读性验收。

`componentCSS({readingWidth:640,rowInset:14})` 只接受已声明的有限正数 token；不要拼任意 CSS 字符串。组件内容参数可以替换，页面布局需按任务选择；阅读页、Dashboard、Agent 和设置页无需相同。

`tr(zh,en)` 与 `language:'zh'|'en'` 是已使用的双语方式。基础无状态组件接收调用方已选语言的 label、caption 等文本；报告模型则要求双语字段。英文使用本地 Liberation Sans／Serif，中文使用本地 Noto Sans SC／Serif SC。字形与许可证随目录保存；字体部署压缩和生产样式隔离不在本地 v1 验收范围内。

## 哪些是组件，哪些是页面模板

| 资产 | 复用边界 |
|---|---|
| Header、Sidebar、DataTable、Card、ItemList、TextField、ActionMenu、Notice 等 | 参数化安全 HTML；业务事件由调用方持有 |
| Tooltip、Accordion、Breadcrumb、Pagination、Loading | 参数化辅助组件；Tooltip 另挂 `mountTooltips`，其他使用原生行为与显式调用动作 |
| 引用、集中来源、图片检查、联动图表、媒体窗口、分栏 | 有生命周期的交互接口；各模块独立输入与 CSS |
| 报告阅读器 | 参数化原创报告合同；两份样稿验证不同章节、图表和阅读状态 |
| Agent、财务、投资、资源、运营看板与复核页 | 可组合的固定演示模板；不等于真实模型执行、检索、上传或生产分析 |
| 设置范例 | 本机偏好草稿与预览；不是账户／外部系统配置 |

`utility-components.mjs/css` 新增 Tooltip、Accordion、Breadcrumb、Pagination 和 Loading。Tooltip 用于短的非关键解释，具有关联描述、焦点／悬停与 Escape；不能将唯一操作说明只藏在提示中。Pagination 由调用方显式提供 page/count/action；空范围为 page=0/count=0。Loading 的 unknown progress 使用 null，不造进度数值。

设置页的 language、palette、density、readingWidth、textSize、motion 立即预览；“保存”才写入本浏览器 `localStorage` 的 `design-settings-v1`，撤销回到保存基线。只影响设置页自身；不会自动改变工作台或报告。跟随系统仅指减少动态偏好，不代表主题自动变成系统深色模式。

## 中英 PDF 的复用范围

[PDF_LAYOUT_RULES.md](PDF_LAYOUT_RULES.md) 是中英两页合同。`render_pdf_v03.py` 使用显式 language/model/theme、`pdf-layout-v03.json` 与嵌入字体；输入参考 `pdf-inputs/zh-v03.json` 和 `pdf-inputs/en-v03.json`。需要 ReportLab；检查脚本另需 pdfplumber、pypdf。

```sh
# 从 editorial 目录运行；使用具备上述依赖的 Python 环境。
python3 render_pdf_v03.py pdf-inputs/zh-v03.json fonts \
  --layout pdf-layout-v03.json --output output/pdf/custom-zh.pdf
```

两页合同覆盖中文换行边界、标签增高、数字列、图注、页脚和缺字／溢出明确失败。替换内容后重新生成并核对输出；现有对照 PNG 不会自动随生成更新。HTML 的旧 `PDFPreview` 仍是英文两页预览，实际双语入口展示生成 PDF 的渲染图。

长文自动分页、跨页表格、复杂脚注／公式、浏览器另存 PDF 和生产报告导出仍是后续范围。两页出版模板可以独立使用，不应被称为通用报告导出引擎。

## 使用后最小核对

用自己的显式内容检查一次：主次是否清楚；零、负与缺失是否保留；引用是否对应提供的原文；关闭后是否回到触发位置；键盘焦点与减少动态是否可用；换主题／语言是否保留身份和状态。现有目标浏览器回放证明记录中的原型路径，不替代新页面自己的验收。

## Codex skill 与扩展色卡 · 2026-10-12

已沉淀 `skills/editorial-design/SKILL.md`；安装到 `~/.codex/skills/editorial-design` 后，可在新对话用 `$editorial-design`。便携资产含组件相对依赖与系统字体 starter，不要求原仓库在线；规则重点是样式/交互，颜色与布局独立配置。

[色卡与布局配置页](palette-lab.html) 提供 paper/mineral/plum/forest/clay/night 六套色卡及完整 JSON 编辑。原有页面三套主题继续兼容；无需扩展每个历史页选择器。`palette-presets.mjs` 用 validatePalette 校验角色与9组文字组合，applyPalette(host,input)逐项写变量，不覆盖宿主原内联尺寸。无效配色草稿不改变最近有效主题。

局部主题中的引用面板传 `portalContainer:host`，或者使用同主题的独立portal根；默认仍是body。主题、字体和scoped CSS需要覆盖该根。DataTable未内置上下箭头选行；Accordion仅文本/链接，高级筛选控件需由宿主框架实现受控展开。React/Vue按已有架构适配，不要求改成Vanilla。

研究任务页默认Paper，可直接打开 `research-desk.html?palette=paper-night` 查看暖灰黑的Paper Night。Header日夜切换保留当前任务和笔记，不重新加载页面；扩展色卡现为七套，原night继续保留。

不同内容复用样例：research-report.html?report=evidence-to-judgment&palette=paper（或 paper-night）。四章两图，复用同一 reader。Skill 的 references/report-reuse.md 给出内容契约与迁移检查；该内容为原创方法建议和合成样稿。
