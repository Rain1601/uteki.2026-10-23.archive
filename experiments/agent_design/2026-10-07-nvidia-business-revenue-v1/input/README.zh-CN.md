# NVIDIA FY2025 原文输入包

本包用于一次跨公司迁移小试。仅提供原文、定位、表格几何和调用范围；不提供业务图、预期节点、图表分组或评分答案。未调用模型。

NVIDIA 的材料已用于早先人工业务图参考，因此本次不是完全未见的盲留出。Skill 也从 v0.3 改为 v0.4，不应与 Alphabet 的结果组成单一模型变量 A/B。

## 明确范围

| 字段 | 选定值 |
|---|---|
| company_id | `nvidia` |
| document_id | `nvidia-fy2025-annual-report-10k` |
| period_end | `2025-01-26` |
| requested_period_label | `Jan 26, 2025`，沿用原收入表日期表头 |
| 财年名称 | FY2025，不是截至 2025 年 12 月的自然年 |
| 币种 / 单位 | USD / million，原文范围证据保留在包内 |
| Skill | [skill-v0.4.md](skill-v0.4.md)，当前候选规则的原样副本 |

## 原件与派生层

原件是 [NVIDIA 官方 IR 年报 PDF](https://s201.q4cdn.com/141608511/files/doc_financials/2025/annual/NVIDIA-2025-Annual-Report.pdf)，[本地冻结 PDF](../../2026-10-07-business-map-mermaid-v1/nvidia/source.pdf) 含 181 个物理页。PDF SHA-256：`757b344ab62ba282f6e44e0702e8ce5f190d88fb23b5e0a2beaf4cb277a395cc`。旧获取记录说明 SEC HTML 曾返回 403；本次没有重新抓取，也没有把 IR PDF 冒充 SEC 原生 HTML。

[source.html](source.html) 是新建的受限派生阅读层。段落由原 PDF 重新执行 `pdftotext -layout` 获取；两张表由 `pdftotext -bbox-layout` 的原始单词及坐标重建。列边界、跨列表头与选区是本实验审阅过的显式配置，保存在 [prepare_input.py](../prepare_input.py)。这是源文件固定后的几何适配，不是通用 PDF 自动表格解析能力。

源包的 `source_sha256`=`c979ab6ebbfa0a680593429f17fd1d50a753f10d6dc9d2708c53758ba54e2bfd` 指向派生 HTML 字节。`original_source_sha256` 单独指向官方 PDF；两者不能混用。每个段落保留 PDF 物理页、旧文本块位置与 hash；每个表格单元格保留 PDF 页面、矩形和原始 word 坐标。派生阅读页可直接打开原 PDF 对应页。

## 选段

- PDF 93 页：10-K 封面身份与财年。封面没有印刷页码，`reported_page` 保留 null。
- PDF 96–99 页：Item 1 从 Our Company 连续保留到 Automotive 小节结束；仅排除三个独立页码。没有从旧业务图反向挑选节点句子。跨页段落不自动拼接，前后两块都保留。
- PDF 149 页：公司合并范围、财年说明；149–150 页保留完整 Revenue Recognition 至 Contracts with Multiple Performance Obligations 说明，排除重复页头/页码。
- PDF 151 页：完整 Foreign Currency Remeasurement 段落，保留 U.S. dollar / United States dollars 的币种语境。
- PDF 170 页：Note 16 的完整报告分部范围和 All Other 含义说明；本轮不收入随后纵向年度展开的分部损益表，等价的收入维度使用 133 页完整横向表。
- PDF 133 页（印刷 41 页）：完整 Revenue by Reportable Segments 表，含两个日期列、金额变化列、百分比变化列、所有行与货币符号。未收入紧随的营业利润表。
- PDF 172 页（印刷 80 页）：完整 Revenue by End Market 表，含三个日期列、缩进子项、总计及所有货币符号。未收入前面的客户集中度百分比表和后面的长期资产表。

完整风险章节、所有财务报表、地区收入表和其他附注不在本包。`fragment_scope` 明示为选段，不能称全报告解析完成。

## 输入格式和独立校验

[source_packet.json](source_packet.json) 共 **62 个块（60 个原文段落、2 个表格块）、2 张表、100 个派生 HTML 物理单元格**，文件 184,086 字节。PDF 没有原生 HTML 单元格；“物理单元格”指本次派生 DOM，不指原 PDF 的天然表格契约。

模型需要自己选年份、金额单元格、分类和关系。金额保留原字符串；货币符号与金额分列；所有年份与非目标变化列保留。没有在包中提供解析后金额、预先挑出的目标金额列、答案节点、财务分组或勾稽结果。表格原缩进可从每个 label 的 `pdf_words[].bbox` 查看。

已执行：原 PDF hash 校验；重新抽取全文并与冻结 `source.txt` 完全一致；60 个选中段落逐项与旧 PDF 派生文本核对；两张表选区内的 101 个原始 word 各分配一次；宿主 `verify_packet` 核对 source manifest、派生 DOM/hash 和完整表格网格；另实际查看 PDF 133、172 页渲染，核对表头、数据行和金额位置。上述验证是输入忠实性验证，不是模型提取评分。

复核命令（离线、无模型调用）：

```sh
PYTHONPATH=src .venv/bin/python experiments/agent_design/2026-10-07-nvidia-business-revenue-v1/prepare_input.py
```

脚本遇到原件改变或冻结输出字节改变会报错，不静默更新历史输入。[validation.json](validation.json) 保留计数与指纹；[source_manifest.json](source_manifest.json) 保留派生链和脚本 hash。

- source_packet SHA-256：`1a14a18f9deaea0079b1798b564817365c8c9709051456dbd1c230233f600852`。
- Skill v0.4 SHA-256：`743f5f3be32d95eb9dd953e81355546de15f615f4cc4d0981156d42835595000`。
- [独立验收标准](../evaluation/acceptance.zh-CN.md) 位于 evaluation，不进入模型输入。

下一步：由主任务固定模型与费用边界后真实执行；再逐项检查业务身份、直接证据和两类收入口径，最后渲染候选图。
