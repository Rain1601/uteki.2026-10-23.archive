# Alphabet FY2025 原文输入包（冻结候选实验输入）

本包供同一原文上的业务与收入提取实验使用。公司、文件、期间与目标年度由本轮调用范围明确指定；不含业务图答案、收入 JSON 候选、预期节点、预期金额或评分。未调用模型。

## 文件与来源

- `source_packet.json`：host 使用的结构化原文包。schema=`source-packet-v1`，78 个原文块，1 张完整表，13 行、12 个逻辑列、82 个物理单元格。
- `source_packet.txt`：相同选段的可读文本及完整单元格列表；不应与 JSON 重复发送。
- 原件：[`source.html.gz`](../../../../data/source_documents/alphabet_2025_10k/source.html.gz)，来自 [SEC 原始 10-K](https://www.sec.gov/Archives/edgar/data/1652044/000165204426000018/goog-20251231.htm)。
- source SHA-256 为解压后原始 HTML 字节：`c2f6301004f35411a20611c14ff01d80a85c0bcbab6053c80d8cc7f6fc747161`。gzip 本身不是该哈希的计算对象。
- 冻结索引：[`v0.5-candidate/blocks.jsonl`](../../../../data/source_documents/alphabet_2025_10k/indexes/v0.5-candidate/blocks.jsonl)，parser=`sec-source-blocks-v0.1.5`，block 文件 SHA-256=`382a4bcbf0f4a1250f23c7253ca9d3a28bab29c6165a26acab8ad2103e7a95f4`。

## 选段范围

1. 封面 fiscal-year 原文块 12；Item 1 标题块 61–62。
2. Item 1 的 Overview 至 Other Bets：原文序号 63–115。保留完整业务正文小节和其中的列表，涵盖 Google Services、Google Cloud、Other Bets；包含原文中的 AI、隐私、研发背景，未根据既有图删成答案清单。
3. 原文块 211：包含 US dollars 的完整汇率风险段落。
4. MD&A 的 Financial Results → Revenues：515–518，含标题、单位说明及原收入表。表保留 2024 和 2025、全部行、空单元格、货币符号、括号和 span；没有人工解析金额或指认目标金额列。
5. Note 1 的 Revenue Recognition：789–813，从收入确认总述到完整 Google Advertising、Google Subscriptions, Platforms, and Devices、Google Cloud 小节。保留 gross/net、按使用量/订阅和收入确认说明。

仅跳过上述范围内已确认的页码/重复页头块：69、70、87、88、104、105、801、802。原文件与原冻结索引未变。Competition 及其后的 Item 1 内容、完整风险章节、收入变动解释、其他财务表/附注不在本包；本包不能用于声称全报告已读或所有业务/收入披露已穷尽。

## host 契约

- 顶层：`company_id`、`document_id`、`period_end`、`source_sha256`、`source_local_path`、`source_url`，另记录 source manifest 和冻结索引指纹。
- 显式范围配置：`requested_period_label='2025'`、`financial_currency='USD'`、`financial_unit='million'`。`scope_evidence_block_ids` 分别指向封面/表期间、US dollars 段落、in millions 说明；这些是有原文依据的调用范围，不是金额答案。
- `blocks[]`：`id` 沿用冻结 block ID；含原始 `ordinal`、`type`、`section_path`、`source_dom_path`、`text`、`text_sha256`、`fragment`、`reported_page`。`section_path` 是人工核对标题后补充的导航标签，非财务事实。块文字与 hash 不重写。
- `tables[]`：`id`、`block_id`、`source_dom_path`、`rows[]`、`cells[]`。行列均 **0 起算**；`column_index` 为 span 展开后的逻辑起列，非第几个 td。`rowspan` / `colspan` 保留原文正整数。每行 `cell_ids` 按原始 DOM 顺序；所有物理单元格只出现一次。
- 单元格 ID 形式 `cell-<block_id>-r002-c009`；每 cell 含原字符串、UTF-8 hash、精确 DOM 路径和原跨度。原 HTML 使用 td 的年份表头，其 `is_header` 为 false；不能据此把年份头忽略。年份归属应根据选择的原文年份 cell 和逻辑列覆盖范围验证，不能采用物理 td 序号。
- 不提供语义金额、预先选中的 row/cell、业务层级、图节点或关系。模型选择 block/cell ID；host 可从此包和原文件重新绑定原文，严格解析金额、核对年度/币种/单位，不能信任模型复写数值。
- `fragment` 沿用旧索引 source_anchor，只表示原件附近的导航落点；精确证据位置是 `source_dom_path`。XML/HTML 命名空间前缀路径来自 lxml 的原 DOM 路径，可用同一解析器建 path→element 映射，不能盲当无命名空间 XPath。

## 实际校验与指纹

已离线核对解压源 hash、冻结 block 文件 hash、全部 78 块的原 DOM 归一化文字与 text hash、全部 fragment 的唯一原始 ID、全部 82 单元格文字/DOM/span 与冻结表一致；独立从原 DOM 展开逻辑网格，确认每行覆盖 12 列且无重叠。未做模型提取、图渲染或全报告语义审阅。

归一化方法：按元素 itertext 原顺序连接，不在标签边界额外插空格；将 Unicode 空白折叠成一个普通空格并去首尾空白。所有 text SHA-256 对该 UTF-8 文字计算。

- `source_packet.json`：102793 字节，SHA-256=`a290de99e8bfd6d48a4663830bca99b43d331cc66055b7c1f7e323b6cd34b0f2`。
- `source_packet.txt`：41020 字节，SHA-256=`693e06604573404e2e5cfa136d597015fe890ef05bb8479d432e3c188e09a4f0`。

下一步：由 host 固定此包指纹后，发送原文和输出契约；将生成候选与独立参考比较。输入选择并非盲测覆盖抽样，不应把单份选段上的结果解释成通用年报自动获取或整报告理解能力。
