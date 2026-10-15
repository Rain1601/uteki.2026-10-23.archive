# PDF 排版对照 v0.2

当前交付是英文两页独立样本，保留 v0.1 输出与生成脚本。它学习出版物的排版角色，不复制 Anthropic 商标、专有字体或研究内容；颜色由共享主题输入决定。

## 原件核查

本轮读取本机官方 Project Swap PDF，核查封面、第二页正文及对应渲染图。原件为 26 页 Letter（612 × 792 pt）。文字对象显示封面标题使用 AnthropicSerifDisplay-Light 36 pt；第二页节标题为 AnthropicSansDisplay-Semibold 24 pt，正文为 AnthropicSerifText-Regular 11 pt，页脚为 AnthropicSansText-Bold 8 pt。封面有大面积色底、独立元信息和细分隔线；正文保留窄阅读栏与清楚的标题间距。以上为局部来源实见，不代表 26 页的所有图表或表格均已核查。

## v0.1 → v0.2

| 维度 | v0.1 | v0.2 |
| --- | --- | --- |
| 纸张 | A4 | Letter 612 × 792 pt，与本次参考一致 |
| 参数 | 页边距、字级、表格尺寸散落脚本 | `pdf-layout.json` 明确 page / margins / type / spacing / table / footer |
| 封面 | 35 pt 衬线，逐行固定绘制 | 36 / 44 pt 衬线段落，按栏宽换行；元信息随标题高度移动 |
| 正文 | 25 pt 无衬线标题，12 pt 衬线正文 | 24 / 30 pt 无衬线节标题，11 / 17.5 pt 衬线正文；节间层级明确 |
| 阅读栏 | 72 pt 两侧留白 | 左 108 pt、右 86 pt；保留编辑式阅读节奏 |
| 表格 | 固定行高、表头色底 | 最小行高、标签可换行、细线分隔、数值右对齐、取消整块表头色底 |
| 页脚 | 42 pt 基线，页码补零 | 26 pt 基线，8 pt 无衬线，普通页码 |
| 溢出 | 固定坐标可能覆盖页脚 | 段落与表格超过正文下界即报错 |

字体嵌入已有 Liberation Sans / Sans Bold / Serif。字族角色可复用，字形与 Anthropic 原件不同。颜色取 `model + theme` 输入中的语义角色；默认使用已有共享输入，未因参考封面为绿色而固定绿色。

## 产物与复跑

- 排版契约：`pdf-layout.json`
- 新入口：`render_pdf_v02.py`
- 成品：`output/pdf/editorial-specimen-v0.2.pdf`
- 旧成品：`output/pdf/editorial-specimen-v0.1.pdf`，保留；本轮读取的 SHA-256 为 `50363a0db34fa5044347b45a9c5a214d1906ac17076640367cc85f0524596112`。

新入口接受共享 JSON（含 `model` 与 `theme`）、现有 Liberation 字体目录，支持 `--layout` 与 `--output` 参数。不会改动 report model 或网页组件。

## 已执行验收与限制

本轮按 PDF 技能先执行创建 marker，再生成新 PDF；Poppler 渲染两页 PNG，Codex 实际查看封面与正文。当前固定样本未见文字裁切、重叠、破损字形或表格错位。pdfplumber 确认两页 Letter、嵌入字族、标题和表格文本存在、全部文字包围框位于页面内；零值与 Missing 分开。此检查是本次 PDF 样本检查，不是用户审美确认。

未完成范围：中文字体嵌入、任意长度报告自动分页、跨页表格、脚注、目录、复杂图表、PDF 可访问性标签、生产导出接入。当前过长内容显式失败，不自动缩字或截断。英文样本的通过不代表上述能力已完成。

下一步：父任务给出最终共享主题输入后，刷新同一 v0.2 样本并渲染检查；再由用户比较整体字体、间距和层级。

### 父任务最终集成

最终主题输入为 `/tmp/anthropic-style-study/pdf-input-v02.json`，来自当前 reportModel + themes.paper；字体从样册本地 fonts 读取。样册标签已抽入 specimenLabels；元信息字号/分隔线/表格padding也进入显式契约。最终文件重新生成后由父任务渲染查看两页，并用 pdfplumber 核查全部文字在 Letter 页内。独立中文缺字与过长段落输入报错、不生成最终文件。网页预览共用相同JSON与英文内容，未宣称浏览器打印与Python逐像素相同。

v0.1及脚本保留。下一项为 ES04.2 中文两页 PDF 适配；当前英文产物已集成，不再待父任务主题刷新。
