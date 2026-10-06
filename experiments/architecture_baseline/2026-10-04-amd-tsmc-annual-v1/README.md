# AMD / TSMC 真实年报提取

用户确认范围：FY2023 起、截至 2026-10-04 的官方年报，保留报告内比较列；先年度，后季度。DeepSeek 执行，Codex 独立核验。历史结果保留，不自动采纳为正式事实。

## 2026-10-05：主 Data Agent 自主选批与调用

本次正式入口是 `agent query`，输入 [main-agent-inputs-v2](main-agent-inputs-v2/request.json)。复用前轮真实模型选出的 75 个原文块和来源期间目录，登记年度财务任务；问题要求寻找包含现金、债务和股本的资产负债表，没有指定批次编号、期望金额或独立答案。主 Agent 从原文摘录目录自行选择第 2 批，调用登记方法 `annual-financial-v2`，默认方法实际加载提取 Skill 和 Prompt v2。

实际链路：字段错误被拒绝 → 加载 query Skill → 再次字段错误被拒绝 → 建立有效提取计划 → 调用 `financial_extract` → 接收候选及缺口 → 结束。完整顺序见 [query/result.json](amd-fy2023-main-agent-v2/query/result.json) 与逐步 Trace。本轮 6 次 `deepseek-v4-pro/high` 规划请求、1 次 `deepseek-flash/low` 提取请求，共用原账本；已存价表估计费用合计 **$0.17045820**，不是实际账单。返回 `candidate_ready` 只表示一次候选生成任务完成。

| 检查层 | 本轮结果 | 限制 |
|---|---|---|
| 原始候选 | 10 条：9 条数值受原文支持，1 条横线正确保持未知 | 仅覆盖该表选定核心指标的两个时点；不代表整表完整 |
| 规范化 DB | 3 条：两期现金及现金等价物、一期期末流通股数；均与原文一致 | 其余 7 条保留在草稿和诊断中，没有被静默丢弃 |
| 程序诊断 | 12 项，涉及 7 条草稿和 2 条关系 | 指标标签匹配、数值边界与未知值分别记录，不等于 12 条错误数字 |
| 独立内容审核 | 全部 10 条草稿、3 条 DB 行、2 条关系和 10 条模型 gaps 已对照 | 对报告原文口径的支持不等于批准通用指标映射；候选未采纳 |
| 主调用能力 | 主模型选批、默认方法选择、Skill/Prompt 加载、候选回执与固定共享账本通过 | 全文选材仍沿用前轮输入，跨运行续接、全年报编排与自动内容修订未完成 |

关键发现：股本 `17` 和流通股数 `1,612` 都出现在正确引用中，但解析正文把邻接单元格拼成 `1,61217`，数值边界检查因而拒绝。结构化单元格仍保留独立值，后续需使用单元格及期间定位修复，不能放松成任意子串命中。债务净额/current/noncurrent 和股本金额的完整源标签未匹配现有目录；不能仅删除限定词或增加 AMD 数值特判来提高入库数量。FY2022 当前债务的横线在原 HTML 有 fixed-zero 属性，但该属性未交付给模型，故本轮保留未知是正确行为。

审核产物：[独立原文审核](review-amd-fy2023-main-agent-v2-source-review.json)、[核心对照](review-amd-fy2023-main-agent-v2-core.json)、[合并逐条审核](review-amd-fy2023-main-agent-v2-combined.json)、[运行与数据库核验](amd-fy2023-main-agent-v2-host-verification.json)。核对了 140 个冻结文件、实际 Skill/最终 System Prompt、规范化重放、DB payload 和原始基线不变。

追溯检查另发现历史实现归档的同名文件冲突：domain 与 infrastructure 的 `direct_extraction.py` 被保存到同一个路径，导致结果声明的一个 hash 与实际副本不一致。manifest 对实际副本有效，但历史实现快照不完整。代码已改为完整包路径、同一份 bytes 写入及计算 hash，并通过 78 项定向离线检查；历史运行保持原样，此修复尚无新的真实模型运行证明。

首个启动目录 [amd-fy2023-main-agent-v1](amd-fy2023-main-agent-v1/result.json) 保留配置拒绝：规划器 `max_tokens=16384` 超过其适配器上限，未发送模型请求；v2 只将规划器改为 8192，提取器仍为 16384，未更换模型或研究范围。

[查看本轮真实财务矩阵](http://127.0.0.1:8765/evaluation?dataset=amd-annual-v2&tab=records&source=source-291485b98a75d8cfabe47571&run=amd-fy2023-main-agent-v2)；[查看提取子运行的实际输入与 Skill/Prompt](http://127.0.0.1:8765/extractions?run=amd-fy2023-main-agent-v2)。页面展示的是提取子运行，完整主 Agent 步骤以本节 Trace 为准。首要后续为表格数值定位与受控指标映射，再处理现金流批次及 TSMC；财报精编仍未生成。

两页 HTTP/内容核对通过。第一次检查中的 `Source-faithful` 大小写和内部文件名不对应页面实际文本，按冻结 Prompt/Skill 与显示标题修正检查后通过，HTML hash 相同；原回执保留为 [v1](ui-main-agent-v2-http-receipt.json) 与 [v2](ui-main-agent-v2-http-receipt-v2.json)。未做浏览器视觉验收，查看页面不触发模型。

## 当前输入

官方获取和文档解析已单独验收：[完整下载链路](../2026-10-04-prepare-chain-v1/README.md)。新数据包为 `official-filing-preparations/amd-v2/dataset` 与 `tsmc-v2/dataset`。`source-selection-v2.json` 绑定六份年度主报告及数据集 hash；AMD 修订版保留为补充来源，不冒充完整主报表。

模型配置：`deepseek-v4-pro/high` 选择证据，`deepseek-flash/low` 提取。沿用 `costs/shared.sqlite`、无金额/总请求上限；每次实际请求及失败留档，无隐藏网络重试。提取 system prompt：[annual-financial-extraction-v1.txt](../../../skills/data-agent/extract/references/annual-financial-extraction-v1.txt)。

## 已运行结果

| 版本 | 输入与实际结果 | 状态 |
|---|---|---|
| `amd-fy2023-attempt-01` | 原试跑，Planner 输出上限 7,000 全被 reasoning 使用，未输出有效计划 | 未进入 Extractor |
| `amd-fy2023-v2-attempt-01` | 自动下载的新原件；从原件生成绑定 CIK/来源/hash 的日期；Planner 上限 16,384。实际 1 次请求，完整返回，选择的 8 个 block ID 均省略 hash 后缀，不在目录中 | 宿主拒绝，0 条提取记录，无人工补 ID |
| `amd-fy2023-v3-attempt-01` | 实际 2 次 DeepSeek 请求：36 个短引用均严格解析，交付 75 个原文块；模型返回 35 条草稿 | 0 条规范化、97 项未解决诊断；不等于 97 个错误事实 |
| `amd-fy2023-v3-protocol-revision-01` | 复用已选块与目录，仅更新通用输出约定和程序反馈；实际 1 次 Flash 请求 | 输出达到 16,384 上限，JSON 截断，整次提取失败；不修补或采用不完整输出 |
| `amd-fy2023-v3-batch-00-canary-01` | 同一来源选材按表切为 11 批；仅第 0 批，5 块。实际 1 次 Flash 请求，16 条草稿/9 条规范化记录 | 9 条核心数值/期间与独立对照匹配；10 批及 24 个未分配正文块仍待处理，核心包不完整 |
| `amd-fy2023-formal-batch-00-v1` | 经正式 `agent extract-batch`，任务 profile 默认选择方法并实际加载 Skill/Prompt；同源第 0 批。实际 1 次 Flash 请求，9 条草稿/9 条规范化记录/0 条程序未解决项 | 9 条与独立核心对照匹配；限定为三个指标各三个期间，全文与剩余批次仍未完成 |

v2 原始计划、模型输入/响应/用量及拒绝原因保留在运行目录；[拒绝记录](amd-fy2023-v2-attempt-01/experiment-result.json)与 `experiment-manifest.json` 冻结文件 hash。完整 JSON 或模型声称选到财务表格，都不能替代来源 ID 核验。

## 独立核验

[AMD FY2023 独立对照](independent-review-amd-fy2023-v2.json)先于提取结果完成，覆盖三张合并主表中的 37 项事实，记录原文表头、单位、周制期间、block ID、单元格及 raw inline context。它没有进入任何 Planner/Extractor 输入，也不作为规范化代码的预期答案。未覆盖的附注明确列为限制，不能把这份对照称为全报告 Gold。

独立对照的本轮可重复比较：[review_core_canary.py](review_core_canary.py) 仅用于结果评估，不进入模型或规范化链路。[v3 核对结果](review-amd-fy2023-v3-core-01.json) 在 35 条草稿中识别到独立对照的 25 条核心主表项目：24 条金额、原表符号、单位、实际期间及引用位置匹配；1 条横线转零缺少交付给模型的显式证据；其余 10 条不在该核心对照覆盖内。这不等于 24 条已入库或 24 条完整语义验收通过。

`run_extraction_v3.py` 已完成短引用协议：模型输入显式 `R000001` 等编号，宿主按绑定 source/hash/manifest 的完整映射恢复 block ID，拒绝未知、重复、旧式截断 ID 和跨来源映射。5 项定向测试及 AMD 1,184 个引用的离线核验通过，随后上述真实 v3 Planner 也通过；未复用旧无效计划。

用户已认可“两类产物 + 原文检索底座”，详见[产物定义与 Daloopa/FactSet 对照](../../../docs/design/UTEKI_DATA_PRODUCTS_v1.zh-CN.md)。本轮交付先补真实数据的查看与核验，财报精编仍未生成。

## 发现的实现差距

v3 的主要程序诊断是 35 次不支持的会计口径字段写法、26 次数值字面量与引用格式不同、17 次指标映射未解决；存在重叠，不能相加当成错误事实数量。6 次单位不匹配来自未映射债券分项的空 metric ID，非已选核心目录被覆盖。不能把这些错误全部视为模型金融知识错误，也不能为了入库绕过口径和证据检查。

输出长度问题另行处理：75 个块的原文文本合计 17,647 字符，但完整块 JSON 包含重复表格单元格结构，约 24 万字符；修订输入实际超过 10 万 tokens。首批改为 5 块、1,023 原文字符，实际输入 20,363 tokens，输出 7,204 tokens；请求正常结束。这个结果同时改变了提示与范围，不能单独归因于 Prompt 改进。

首批独立审阅见 [逐记录与覆盖结论](review-amd-fy2023-v3-batch-00-combined-01.json)：额外候选有原文支持，但覆盖说明把部分未返回的项目称为“保留”，并漏了额外指标的 12 个比较列数值。9 条 DB 数值正确不代表整表完整；这些问题已写入新应用 Skill 的通用覆盖约束，未把财务答案加入提示。

## 真实查看页与方法接入

[财务事实矩阵](http://127.0.0.1:8765/evaluation?dataset=amd-annual-v2&tab=records&source=source-291485b98a75d8cfabe47571&run=amd-fy2023-v3-batch-00-canary-01)分别展示原始候选与规范化 DB 行，逐条可回到原文；失败版本、关系错误与覆盖缺口可查。[运行页](http://127.0.0.1:8765/extractions?run=amd-fy2023-v3-batch-00-canary-01)显示真实输入、Prompt/schema、结果与核验。财报精编明确为未生成。

`ui-http-verification-v2.json` 的 16 项检查全部通过；测试固定登记文件 hash，包含错误来源/跨公司拒绝、失败版 0 行、TSMC 独立缺口及原文返回链接。v1 记录保留，其旧状态断言未跟随新审阅登记更新；不能把该断言失败当作数据错误。页面视觉体验由用户评审，未声称执行浏览器检查。

应用方法及任务选择接入状态见[执行说明](../../../docs/design/UTEKI_DATA_EXECUTION_v1.zh-CN.md)。本轮先将按表方法从实验入口接入 Uteki，保留全文选材、批次自动续跑和 Review 修订的未接通边界。

正式入口的调用输入保存在 `formal-batch-inputs-v1/`，沿用 v3 模型选材和目录，仅去掉 inline Prompt，并显式声明任务类型。任务 profile、方法选择原因、Skill/Prompt 全文与 hash 保存于 [method-snapshot.json](amd-fy2023-formal-batch-00-v1/method-snapshot.json)，没有将独立答案或财务预期值写入输入。

[正式运行工程核验](amd-fy2023-formal-batch-00-v1-host-verification.json)已核对真实系统指令、文件完整性、规范化回放、9 条 DB payload 和 6 条去重原文证据；[独立核心对照](review-amd-fy2023-formal-batch-00-core-v1.json)9 项均匹配。模型明确把其他报表留为缺口，0 条程序未解决项不等于没有研究缺口。请求使用 `deepseek-flash/low`，输入 17,599、输出 4,985 tokens，20.38 秒，按已存价表估计 $0.0112617，非实际账单；共享账本未重置。本轮 v3 至正式单批共 5 次请求，旧尝试另存。

底层模型客户端复用了现有 `SdkRecordReviewer` 传输类，因此计费回执的 stage 字段仍叫 `record_review`；这次实际执行的是 Extractor，不能把该标签当成另做了一次内容 Review。`system-prompt-effective.json` 的 `prompt_sha256` 指基础 Prompt，追加 schema 后的完整指令由文件 manifest/hash 和实际文本组合核对。

[正式运行独立内容复核](amd-fy2023-formal-batch-00-independent-content-review-v1.json)不读取本轮 held-out 比较结果，另从交付原文检查 9 条候选、7 条 gaps 与关系列表；9 条均在限定范围内 supported，未发现三个请求指标的比较期遗漏。标题引用与未定位附注描述仍作为改进点保留；不将归母与总净利混同。[合并审阅](review-amd-fy2023-formal-batch-00-combined-v1.json)已登记至[最新真实矩阵](http://127.0.0.1:8765/evaluation?dataset=amd-annual-v2&tab=records&source=source-291485b98a75d8cfabe47571&run=amd-fy2023-formal-batch-00-v1)，保留旧运行和候选状态。

正式运行登记后新增两页 HTTP 核对通过：真实财务矩阵显示新 9 条候选与覆盖审阅，运行页显示本次实际 Skill/Prompt。回执为 `ui-formal-run-http-receipt-v1.json`；登记配置 hash 在检查前后相同。此前 16 项路由/范围检查单独保留，本次未重复全套，也未进行浏览器视觉验收。
