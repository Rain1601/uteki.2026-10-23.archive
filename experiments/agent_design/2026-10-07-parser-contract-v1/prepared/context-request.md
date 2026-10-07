# 请与 Codex 一起确定财报解析产物，先于问答案例

## 用户业务目标与本次纠正

Uteki 是有证据的公司研究系统。Data Agent 把原材料加工成不同的数据产品，例如结构化事实、精编文档、业务图、索引。每类产品需要结构 schema、业务语义、消费方式和来源说明。之后分析 Agent 根据问题选择工具，读数据和原文片段，形成有依据的结论。引用必须尽可能到具体段落/表格/单元格，不能止于整份年报。新闻、官方博客以后也走可溯源的过程。

用户确认研究 VectifyAI/PageIndex；内核必须仍是 Uteki 自己的 Agent，不用 Codex 手工完成任务再冒充系统执行。拟定 Sonnet 5.5 做执行，Opus 5.5 可做规划/顾问。模型经 AIHubMix 连接。用户刚才说“Sonnet 5.5还是 OpenAI 5.5”，与此前模型选择有语音歧义，本请求沿用已有 Opus/Sonnet，而不另选 OpenAI 模型。

上轮我们建议冻结年报，先跑一个数据问题、一个业务问题。用户现在明确纠正：**解析层必须先定义清楚，10-K 究竟变成哪些对象、字段、数据类型；若是文档，样式如何固定；标准化应当使结果稳定可复现。** 请先回答这件事，不能拿两条问答成功替代基础解析验收。请给出你自己的方案及对 Codex 草案的修正。后续才用明确契约跑真实消费案例。

## 已核实的现有实现，不能当作缺失重建

Python，lxml 原文解析。正式 company_materialization 的 HTML 入口显式用 sec-source-blocks-v0.1.7，build_legal_outline 输出 document-index-v0.1。parse_sec_source 函数历史默认仍 v0.1.1；未知字符串没有强制拒绝。此次新实验出口会明确验证支持版本，不改历史默认或冻结产物。

SourceBlock（既有 dataclass）：block_id, ordinal, type, text, text_hash, source_anchor, dom_path, reported_page, style_signature, table?, image_asset_id?, layout_role?。
type 枚举：heading_candidate / paragraph / list_item / table / image / page_marker / other。
text 是规范化的可见文本，连续 Unicode 空白折叠并 trim；不是原 HTML 字节。字符坐标必须声明针对规范化文本。block_id 由顺序号和文本 hash 生成，不是全局 ID；使用时要带来源与解析/index 身份。

TableStructure：row_count,column_count,cells[]。
TableCell：text,row,column,rowspan,colspan,is_header。row/column 从 0 起；span >=1；is_header 表示源 HTML th，不代表理解会计列。表格包括排版用表格。外层块/表文本可能覆盖内层表的文本；不可将所有块/表加总当内容不重复。

ParsedDocument 还有 anchors（anchor/dom_path/target_block_id）、toc_entries（part|item,number,title,source_anchor,reported_page,ordinal）、assets（asset_id,source_url,source_path,alt,dom_path）、parser_diagnostics。
目前 anchors/toc_entries 在内存里，没有独立完整导出。

DocumentIndex：index_id,schema_version,parser_version,source_snapshot_id,form_type,nodes[],diagnostics[]。
DocumentNode：node_id,parent_id,kind(document|part|item),title,part_number,item_number,start_block_id,end_block_id,source_anchor,reported_page。
IndexDiagnostic：code,severity(info|warning|error),message,node_id。
index_id 包含 raw hash/schema/parser version，但不包含全部业务身份，不可单独当全局产物 ID。当前目录是法定层级，不保证语义小节和主题都识别。

现有输出有两条写法：
- company_materialization 用 asdict，style_signature 为二元数组；输出 index.json, blocks.jsonl, assets.json, manifest.json；图片只是引用。
- index_artifacts 把 style_signature 转 dict，排序序列化，还可核验 JPEG 文件；其 assets.local_path 依赖输出位置，manifest.index_version 取输出文件夹名称。
因此“解析对象相同”不自动等于“跨目录所有文件字节相同”。不能改旧产物来制造一致。

DocumentReader 已有 outline/search/read/context/evidence；search 是单一字面短语，不是任意关键词逻辑；reading_groups 确定性地将列表、邻接表头/单位/脚注与表格一起读，但跨远处脚注仍可能未解析。不存在单独 read_source(cell) 公共操作。

已存在 ResearchRecord、EvidencePackage/SourceLocator/coverage、计算结果 ComputedScalar、model_summary、BusinessMap 契约及候选生成、narrative 契约。研究类型、候选/采用状态不是空白。当前 typed queries 编译参数化 SQL，不允许任意 SQL；不要扩张需求为自主通用 SQL。标准财务 adapter 有明确指标映射，不能以 HTML parser 自动理解任意公司的所有财务数据。

公司、来源版本、表单、报告截止日、available_at 等来自显式冻结材料元数据，不从样本猜默认值。报告截止日不能代替每一行财务事实的实际期间。未知数据/未覆盖不能填 0；一次搜索未命中不等于整份材料没有披露。

## 两个真实冻结来源的审计

- AMD FY2023，10-K，报告截止日 2023-12-30。原件 SHA256 47955f5d3d309e40c53ac7243dc955c8c1b594605fa938db1b5c411aaf2aa808。v0.1.7 解析 1184 块、76 HTML 表、7429 cell、2 图片引用、1950 anchors、27 toc_entries；目录 1 document+4 part+23 item。仍有 1 条 toc anchor conflict error、7 条 warning。
- TSMC FY2023，20-F，报告截止日 2023-12-31。原件 SHA256 8ab4ee8c621d4d7bc804d08bd5cfe494b91dc09a63a4c7decfad4e5f8b9961c1。1929 块、506 HTML 表、67764 cell、5536 anchors、32 toc_entries；目录 1 document+3 part+0 item，有 item_unresolved error。
- 每份来源在同一环境用相同显式参数各内存解析两次，ParsedDocument/index canonical JSON 相同，也与各自冻结 blocks/index 对应。这只验证重复解析稳定，不证明完整/正确、不证明跨目录包相同。
- 本轮准备真实解析包样例及标准阅读 HTML，独立验证跨目录全部内容 hash 和缺口保留。尚未宣称新出口已纳入生产 prepare。

## PageIndex 固定版本源码结论

核对 VectifyAI/PageIndex commit 6d23caf416858f2ca136840305d1f479a86f6ef7，声明 SDK 0.2.10、MIT。
https://github.com/VectifyAI/PageIndex/blob/6d23caf416858f2ca136840305d1f479a86f6ef7/pageindex/flash/api.py

- 开源本地版有索引、retrieve、chat。真实 PDF 可直接 page_index_flash(pdf,summary=False,optimize=False)。这一组合不调用模型，返回标题树和从1起、含首尾的 PDF 物理页范围。
- 公共结果没有完整稳定段落块、table cells、bbox 集；内部 page_texts 返回前被移除。不能当完整 PDF 数据解析器。node_id 是遍历编号，不是跨重建稳定事实身份。
- 本地 submit_document 仍会 summary=True 加文档说明。chat 自带 Agent 循环。索引 LiteLLM helper 有最多10次尝试、drop_params=True；摘要默认并发64，扩展最高32。native Anthropic chat 使用 tool_runner。
- 能经 backend base_url/api_key 接原生 Messages，但 AIHubMix+此 SDK 尚未实测。我们的最小复用无需它接管模型循环。
- HTML 有 DOM anchor，PDF 有物理页与坐标；reported_page 不是物理页。PDF目录到 Uteki 块可以一对多，最终结论必须回到支持它的具体片段。
- 本次未安装或运行 PageIndex。SEC HTML 先借鉴层级导航思路；PDF 案例再验证最小 Flash 组件复用；不因示例 benchmark 就认定质量。

## 模型运行时现状，避免虚构联通

AIHubMix 原生 /v1/messages 的 Sonnet/Opus adaptive/high、stream=false 已在冻结实验脚本实测。它们目前是实验 transport。共享生产 model_factory 对 AIHubMix 仍走 OpenAIChatCompletionsModel；普通 planner 固定 temperature=0；autonomous planner 暂只支持 DeepSeek 的显式 effort。因此不能只换 model ID 就说 Sonnet 已运行完整工具链。真正用 Sonnet 在系统内自主调用原有检索工具，需要先做 provider 适配，仍由 Uteki 持有循环、预算、日志。

本次是顾问评审真实源码与规格，不是模型执行检索案例。你没有外部工具。

## Codex 初案（请批评，不必认同）

1. 先发 SEC HTML 确定性原文包：source.json、blocks.jsonl、index.json、anchors.json、toc.json、assets.json、schemas/、document.html、manifest.json。重复用现有 parser，无 LLM；新出口独立版本。style_signature 明确选正式 materialization 的二元数组表示。路径与运行时间分离在包外记录。
2. schema 负责字段类型，额外校验来源/范围/链接/hash；仍需语义正确、覆盖、冲突评估。
3. 人读 document.html 固定样式：来源身份和诊断→法定目录→原块顺序；每块/单元格固定锚点；HTML表格保留合并格；区分标题候选与确认目录；来源报告页码未知保留空；图片引用状态，不伪造OCR；保留解析可能重叠的说明。
4. 模型业务加工另分：结构化事实、精编文档、业务图、导航摘要；通过原有契约做增量。JSON/SQL/Markdown只是载体；同一事实多种投影不重复算独立证据。
5. 精编标准模板：身份/范围→覆盖目录→固定ID分节（陈述、主文、数表、来源）→缺口与冲突→版本与运行；中文英文共享 statement_id 与根出处；每条语义事实/管理层观点/计算/推断区分。章节覆盖由显式版本模板决定，不硬编码某公司时期。此时还未定完整 schema。
6. 可复现分四层：原件/程序解析内容hash一致；字段/模板渲染稳定；模型重跑事实/证据/覆盖一致性量化；已采用产物冻结版本反复读取一致。fixed effort不承诺逐字输出一致。
7. 先用真实 AMD10K 和 TSMC20F 展示完整解析包并保留目录错误，再做按契约的财务与业务消费案例。不是说20F完整已通过。

## 请返回具体决策

A. 是否同意先定义解析输出？用明确表格给出：产品/最小字段/程序或模型产出/当前vs新增/验收/消费者。区分原文、导航、业务对象。
B. 哪些应本轮必须落地，哪些可后置？有哪些必要却缺的对象或语义？避免为每种格式新增一套业务身份。
C. 两种文档——标准原文阅读版与模型精编——各给一份具体、可检查的模板，字段/章节/出处/缺口怎样固定？给一个小型示意JSON，不要冒充真实财务内容。若认为现有 narrative/evidence 可复用，指出增量而非重建。
D. 对“稳定可复现”定义精确验收，如何区分格式稳定、程序重放、语义稳定、冻结产物重用？如何发现稳定地输出错误内容？
E. PageIndex 最小接入位置/不用SDK或复用组件的取舍；源码核查支持到哪一步，尚需什么真实实验？
F. 给出可执行的3个优先动作，指出 Codex 草案你反对或需修改的2–4点。如果关键事实未知，明确不知道。

不要输出庞大通用平台设计、未验证工具名或不可证明的“完全可复现”。也不要求你写隐藏推理步骤。
