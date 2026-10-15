# Editorial PDF v0.3 · 中英两页契约

当前位置 ES04.2，中文与英文两页样稿已交付。`pdf-bilingual.html` 展示实际 PDF 渲染图；v0.1/v0.2 保留。源自此前 Project Swap 原件观察的字体角色和版面节奏，是项目适配，不是官方字体复刻。

## 复用入口

共用 `render_pdf_v03.py` 与 `pdf-layout-v03.json`。调用方必须提供 JSON：`language` 为 `en` 或 `zh`，`model` 为显式文案及数值行，`theme` 为语义配色。固定标签也是显式样稿配置，不是生产报告默认。

```sh
python3 render_pdf_v03.py pdf-inputs/zh-v03.json fonts --layout pdf-layout-v03.json --output output/pdf/editorial-zh-v0.3.pdf
python3 render_pdf_v03.py pdf-inputs/en-v03.json fonts --layout pdf-layout-v03.json --output output/pdf/editorial-en-v0.3.pdf
python3 check_pdf_v03.py
```

需 ReportLab；验收另需 pdfplumber、pypdf。运行不依赖网络或 fontTools，完整静态字体随样稿保存。替换文案、主题或版面后重新生成 PDF；PNG 对照图必须从新 PDF 重新渲染，不是动态 HTML 打印结果。

## 版面与字体

- Letter 612×792 pt。封面左右 86；正文左108/右86，上60/下64。
- 封面标题36/44，节标题24/30，正文11/17.5，图注8.5/12，页脚8/10 pt。
- 英文 Liberation Sans/Bold/Serif；中文 Noto Sans SC 400/600、Serif SC 400，按角色检查所有文本的字形覆盖。字体嵌入 PDF 子集，许可证与hash保留。
- 原始中文可变字体默认权重100/200，不能代表正文400。`fonts/pdf/manifest.json`记录fontTools4.66.1静态实例、源hash与最终hash；正文400、标题600已显式锁定。网页原可变字体不替换。
- CJK 段落按实际字宽贪心排版，再回退至允许边界；具体行首/行尾禁则字符由中文配置声明。ASCII字母数字词优先整体保留，超长词可按字拆。正文、图注、标题、元信息和表格共用函数。该规则不是完整Unicode排版/专业出版社禁则实现。
- 表格标签和表头可换行，行高随内容增加；最小30pt，四边内距8pt。数值列固定120pt、右对齐，逗号千分位，保留输入数值自然小数表达，不补零、不改变精度。0、null、负数独立呈现，null用语言标签。
- 元信息限两列单行，超出明确失败。页脚左/右54pt，距底基线26pt，预留28pt页码间隔；图注、表格不得侵入正文底部64pt区域。
- 缺字、正文/表格溢出、数字列超宽、页脚碰撞明确失败；不缩字、裁切或替换字体。成功写完临时PDF才替换输出，失败保留已有最终文件。

## 原例与独立验证

四页最终PDF逐页渲染实看：封面字形清晰、标题层级、表格分隔线与页脚完整，无缺字方框或裁切。文字可提取；嵌入各实际字体角色；全部文字在页内，正文与页脚区分开。中文行首/行尾禁则检查通过。

独立长标签含跨期说明、-1284.5、零、null、中英文引号括号混排：标签自然增高、数值右对齐、禁则通过。默认ReportLab CJK曾把右引号置于行首，共用边界回退修复后同输入回归通过。𠮷缺字、超长正文、10^40数值、过长页脚、未知语言均明确拒绝；已有成品hash不变。

边界：仅明确两页结构，任意长度自动分页/跨页表格/复杂脚注公式/移动端/浏览器打印和跨机器字体矩阵未验收。配置可稳定复用不等于通用生产报告引擎。下一项 ES04.3 建议用长文和跨页表格验证分页能力；未开始。
