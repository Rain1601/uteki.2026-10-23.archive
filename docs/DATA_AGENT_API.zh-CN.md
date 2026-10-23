# Data Agent 接口契约

日期：2026-10-14 · 版本：v0.5 · 状态：用户已确认实施路线，模型 API 统一经 OpenRouter，对比 OpenAI Agents SDK 与 Claude Agent SDK 及配套能力两套实现；共享业务工具契约延续 v0.4。第四批 review 收尾、双 SDK 绑定及 T5/T6 限定离线验收已完成（2026-10-15），真实网关与正式 MCP 尚未联调。当前实现范围见 0.0–0.0.1；剩余业务契约与双实现边界见核心设计 14.16–14.17。

本文件定义 Data 能力的全部对外与内部接口：请求上下文、6 个数据工具、模型可见输出、交付包、内部组件接口及 MCP 映射。职责与流程见[核心设计](DATA_AGENT_FRAMEWORK_DESIGN.zh-CN.md)第 6 节，数据模型见第 4 节，运行时见第 7 节（本文其余处提到的“核心设计 14.x”等旧章节号指[设计历史](DATA_AGENT_DESIGN_HISTORY_2026-10-23.zh-CN.md)）；本文件只维护接口细节。

**相对 v0.2 的变化：**按已确认的 A5（单进程库，不建 HTTP 服务），删除 HTTP 路由与状态码映射，改为 Python 进程内调用与 MCP 两种传输；`find_assets` 保留 v0.2 的字段与边界规则，增加证券代码解析与版本呈现规则；补齐其余 5 个工具、`create_context` 与交付包。

**相对 v0.3 的变化：**补齐需求计划登记、统一结果引用、build 身份与完整输入、发布能力与实时能力、澄清返回与继续上下文五项契约；对应核心设计第 14.15 节的两条文档走查。此次仅修订设计，不表示通过实跑验收。

**相对 v0.4 的变化：**通用执行由各自官方 SDK 承接，删除自定义 ModelClient 草案；Agent/Runner、FunctionTool、Session、RunState 是 OpenAI 侧映射，Claude 侧使用其原生循环、工具与会话。应用保留资产、来源/预算、需求状态、实际展示引用与交付校验；Skills/Memory 使用官方适用机制，不另造 Agent 协议。首期数据来源为官方来源；最新检查失败允许带日期与“未确认最新”标记返回符合硬边界的旧材料，并保留缺口（核心设计第 10 节）。两套实现共享此业务 API，内核选择留在应用装配配置，本次不向公开工具参数注入 SDK 类型或新字段。

所有示例中的公司、期间、ID、URL 与数值均为虚构，不是公司事实或实跑结果。

## 0 通用约定

### 文档后端补充（2026-10-19，目录与完整内容组）

带 `documents` 的上下文在两套 SDK 中使用同一份文档专用参数投影（`agent/document_contracts.py`）；服务内部仍使用下文共享契约。模型可见 schema 不公开 PDF 后端未支持的角色过滤、XBRL 概念、文本 regex/any_terms、图像载荷和更新操作，显式传入这些参数会失败，不静默忽略。旧非文档上下文保持原工具接口。

- `find_assets(filters={securities:[{ticker,exchange_mic}]})` 在资产发现时按已确认登记映射筛选公司，随后目录/正文沿用精确 `asset_ref`，不重复填写 symbol。未知映射返回 NOT_FOUND，映射到多个公司返回 AMBIGUOUS_ENTITY；不会扩大当前公司/材料白名单。不指定截止日时，仅作已登记 symbol 别名定位，不断言当前上市状态；指定截止日则调用原严格证券有效期校验，未知日期明确失败。
- 文档模型工具（不含 deliver/clarify）的 state 为增量：`{reason,add_needs?:[{need_id,description,required}],satisfied?:[…],gaps?:[…]}`。首次必须登记非空 add_needs，以后仅添加新需求；省略需求保留已提交状态，新需求默认为未核验。宿主填 next_action 和计划版本，合成内部完整 TaskState；重复/重写需求、重复/未知状态和非法引用明确拒绝。旧完整状态调用仍严格校验，不静默修正错误版本。deliver 仍须显式判断全部需求，clarify 保持原完整状态接口。
- 文档模型 query_records 默认 max_bytes=200000（原有硬上限），适应不可截断的记录/计算/原文依赖闭包；显式较小预算仍严格执行。超限错误包含实际所需字节和当前预算，超过上限仍失败并要求拆分，其他分页工具的默认预算不变。
- 文档 `ContextRequest.required_securities` 可选地声明调用方明确要求的证券查找条件（非空时须有 documents，禁止重复）。它不同于许可范围 entities；find_assets 的 filters.securities 必须覆盖当前实现要求的同一组条件，否则 SECURITY_FILTER_REQUIRED。后续 asset_ref 必须来自实际匹配 symbol/公司的发现结果，否则 ASSET_DISCOVERY_REQUIRED；澄清不得丢弃或替换既有要求。默认空值不进入旧上下文序列化，不改变旧上下文身份。
- 文档提取记录的 unit 必须有 support.unit 原文明确代码或完整标签支持；不能从 `$` 等含糊符号推断 USD，没有代码时可保留 U.S. dollars 等原名。UNIT_EVIDENCE_REQUIRED 返回模型补读或留 gap；scale 单列。unit_basis=explicit_source_label 仅表示标签的字面来源，不证明该句适用于该数值，不执行无依据的 ISO 归一。
- 单个 `read_evidence(targets=[{section_path,include_descendants:true}])` 现在支持父目录内部按完整原文块分页。后续保持相同目标及 context，仅传 `next_cursor`；可调整 max_bytes，不需拼子路径。每页返回 `coverage.block_start/block_end_exclusive/total_blocks` 和仅依赖当页已返回成员的 `page_evidence`，完整交付需引用全部页。最后一页游标为空不代表该页自身覆盖整章。单块过大时保持游标原位置并返回 ITEM_TOO_LARGE，不跳过正文。多个 target 的旧分页行为保持；旧单章节游标因布局改变明确 CURSOR_EXPIRED，原引用仍可读。

- `get_asset_schema` 不传 `outline` 时，优先在 `items[0].directory.nodes` 返回完整紧凑目录（含父 ID、code_path、深度、子节点数、direct/subtree 内容数和局部边界问题）。目录投影超过 100000 字节时回到有游标的 `facets` 和按父节点展开；必须检查 `directory.complete`。目录完整不代表原件解析质量全部通过。
- `search_asset(mode="outline")` 的 `outline.depth` 控制展开深度，节点按父子相邻的先序排列。`mode="passages"` 使用 `{outline:{section_id},passage_scope:"direct"|"subtree"}`，默认 direct；此模式不接受 depth 展开。子章节组保留各自路径与局部 index，不重新编号为父章节组。
- `read_evidence` 的 `section_path` 默认只读本节点，`include_descendants:true` 才包含子章节。`passage_path` 返回完整成员 `items` 及 `group_evidence`。后者是普通 `kind=evidence` 的 ResultRef，内容种类为 passage，依赖全部成员；完整正文交付引用 `group_evidence.result_ref`，无需重抄全部块引用。依赖必须实际随工具返回并被 SDK 观察，过大响应不会登记隐藏成员或返回半个成功组。
- `query_records` 的模型可见文档参数不包含 XBRL select/filters；空 `select` 可省略，服务使用已有空选择器。仍须先读取明确数值单元格、提供逐字支持及原值，再由代码计算；本次未改数值/业务验收规则。
- 文档工具错误中的 `current_task_state` 补充真实已提交 `state`；仍要求 request/state 分开提交。当前尚未实现状态自动维护或短引用句柄。

当前实现与真实复验范围见核心设计 14.21.2–14.21.3；后文早期接口表的泛化选项不能当作文档 SDK 公开能力。文档后端 `find_assets.query` 当前为标题、公司规范名和材料类型拼接文本上的不区分大小写整句子串匹配，不是分词/语义搜索；`reporting_periods` 只匹配已登记期间，未知会返回 REPORTING_PERIOD_UNKNOWN，不从标题猜年份。本次真实运行暴露了这两项发现阻力，尚未优化。

### 0.0 第四批确定性 Python 实现范围（2026-10-15，限定验收）

以下是第四批当前实现的具体调用形状；后文仍保留完整目标接口，不能将 SDK/MCP、`run_query`、澄清继续或模型输出格式化当成本批已实现。核心契约见 14.7.1，原限定验收及未运行检查见核心设计 14.12.12。**2026-10-15 收尾：R1–R4 已修正并通过限定验收（核心设计 14.12.14），原反例保留于 14.12.13。具备第五批离线适配开工条件，不代表真实 SDK/模型业务验收通过。**

- 装配为 `DataService(catalog, acquisition_adapter=None)`，Catalog 与绝对数据根由宿主显式提供。`create_context(request, request_key=..., recover=False)` 创建不可变上下文；六工具调用为 `service.<tool>(context_ref, request, state=..., request_key=...)`。`deliver(...)` 是控制入口；`inspect_context` 查看接受/完成的操作，`read_delivery` 读回已冻结交付。同步工具不执行模型循环。
- 请求的可执行类型定义在 `contracts/query.py`、`contracts/run.py`。`FiscalPeriod` 沿用存储契约，六个字段均显式提供，未知字段值用 null 并注明 basis；本实现不把财年标签转成自然年。主体、来源与截止日为硬边界，期间匹配未知保留 unresolved；记录查询用精确的 `{start,end}` 或 `{instant}`，时间戳需有时区。
- 完整 AssetRef 四项非空并属于同一已发布版本。未发布版本不可读，旧引用不自动改指向新 build。`ResultRef.item_id` 为宿主生成的 `res_` 标识；业务 `record_id`、`calc_id`、原件 `reader_ref` 保存在结果中，不把业务 ID 当全局唯一结果身份。

| 工具 | 本批实际能力与返回差异 |
|---|---|
| `find_assets` | SQLite 目录硬过滤与 FTS5 文本匹配；当前有效标题用于展示和检索，candidate/conflict 修订不采用。两路 BM25 各自按同分共享的 dense rank 做 RRF 合并（k=60），精确分数内部用分数运算，同分按完整 AssetRef；match.ranking 给出方法和分数字符串。返回 matched/unresolved、未确认最新及实际派生能力。未登记内容期间不补造；无法证明历史可得时间的资产不返回为合格候选。 |
| `get_asset_schema` | `overview`、三层以内目录、记录字段、原件 QName 概念及实时 readiness；默认带一级目录，分页条目位于单个说明的 `facets` 中。 |
| `search_asset` | outline/text/concept；text 支持 phrase/all_terms/any_terms/RE2 regex，返回原文字符命中区间及最长 300 字符片段。词干命中区间来自 FTS 高亮，Unicode casefold 命中映射回原字符。concept 仅指原件 inline QName，角色语义标注、OCR/caption 分类显式拒绝；block/origin scope 仅用于 text。 |
| `read_evidence` | 正文、表格单元格、inline fact 和这些结果的精确 Locator；合并单元格按覆盖的行列选择。仅支持 full 表格表示；compact、图片和跨页 continuation 显式 unsupported。请求的上下文作为 `context_evidence` 返回，目标通过 `dependency_refs` 关联；该组不能被字节预算拆散。无明确表头标记时保留候选上下文和关联未确认 issue。 |
| `query_records` | 返回完整记录及原始 context/unit 出处；本批列均为追溯所需字段，`select.fields` 校验字段可用性，不裁掉口径与出处。精确期间、单位、维度、解析状态过滤；不由维度是否为空推断 consolidated/segment。每个计算操作数必须指定完整 AssetRef、selector；另必填 `period_policy`、`comparison_basis`。 |
| `request_asset_update` | process 显式构建整份 HTML 的派生索引；无 inline facts 时不制造 records/concepts。acquire 只执行宿主配置的 `OfficialAcquisitionAdapter` 精确计划，校验公司、材料、期间、来源、截止日、URL 与扩展策略后复用既有官方获取/发布链。无适配器或未允许网络时不发网络请求；受控传输单列 transport_requests，不冒充真实外部调用。 |

**索引与预算：**派生索引 manifest 为 `uteki-derived-html-v2`，trigram 以 casefold 文本检索并保留原文；旧代不修改，需显式重建后才能使用新代。计算按精度 50、ROUND_HALF_EVEN、除法 18 位小数执行，零基数/歧义/不可比返回 null 和原因。`search_asset/read_evidence/query_records.max_bytes` 为 2,000–200,000，默认 24,000；工具最终信封也受限制，其他工具上限 200,000 字节。计算的原始记录、原文的上下文均计入实际输出；输出不足则保留缺口，未展示结果不登记。

**同步时限与失败：**单次调用从进入 DataService.call 开始计时，扣除该运行已累计时间，覆盖必要预检与执行；未接受计划的超时预检仍计时。获取逐请求 timeout 不超过剩余时间；DuckDB 可中断、SQLite 有进度检查；处理/索引激活/发布移动与提交前检查取消及 deadline。已经开始的不可抢占系统调用可能稍后才返回，返回后不得启动下一业务步骤；失败记录与持久化收尾仍须完成，不以强杀破坏存储。停止后的已提交/不确定结果通过 error.details.effects（致命恢复异常为异常的 details）报告，包含 receipt、generation、snapshot/build 状态及恢复要求；错误不是“没有副作用”的保证。模型强制部分交付仍由后续 runtime 实现。

**上下文创建恢复：**使用原请求和 request_key，显式设置 recover=True；未完成创建返回 RECOVERY_REQUIRED，已完成状态损坏拒绝重置为初始状态。创建意图通过现有 Catalog registrations 和 ContentStore 固定，控制文件再写入；恢复校验原 request/policy/run/context，重确认必要目录同步。此入口只完成上下文创建，不重执行已接受的工具或模型，也不扩展成澄清继续。旧格式上下文与交付可读，无需迁移。

**补数与重放：**获取发布返回现有 build 的 job_；仅重建派生索引及拒绝动作返回 op_，与对应 operation_id 关联，并另列 generation。成功构建索引不代表原始记录全部可解析。acquire 的宿主计划指纹参与幂等键校验；重复原请求读取已保存响应，变更计划不能沿用同一键。接受后中断且无已保存响应时返回 OPERATION_INTERRUPTED，允许检查原件、候选与索引 head，但不自动重复有副作用的动作。交付响应已落盘但目录 run 未收尾时，精确重放补齐目录终态，交付字节不变。

**交付说明：**参数只接受登记引用和标明来源的调用者说明，不接受调用者补填原文或数值。`context_evidence` 与计算操作数递归纳入交付；引用、闭包和格式有效不证明自然语言需求已被充分满足。本批的程序化案例不能当作 Agent 自主选材或业务充分性通过。

### 0.0.1 第五批 SDK 离线绑定（2026-10-15）

**当前验收范围：**核心设计 14.12.16 检查点 16 已按目标附件 Prompt 2 七项要求完成离线收尾，证据见 [checkpoint-16.json](../output/data-agent-runtime-20261015/checkpoint-16.json)。下文按检查点保留协议演进，当时未完成项以该节末尾审计为当前结论。四项历史偶发故障仍未解释；真实网关、实际收费、完整配套与业务效果未验证。当前准入非付费工程与本机合成验收，付费准入未通过；正式 CLI/MCP 信号映射留对应入口批次。

在 0.0 的确定性 API 外增加两侧原生 SDK 装配，入口为 agent.openai_runtime.run_offline 与 agent.claude_runtime.run_offline。六工具及 deliver/clarify 的模型参数是 `{request, state}`；context_ref、请求幂等键与根上下文由宿主绑定，模型不能替换。工具 schema 来自现有 Pydantic 契约。OpenAI strict_json_schema=False 是为保留维度/QName 映射等动态键，应用完整参数校验保持；真实模型是否支持该 schema 仍须对应网关验证。

适配层分别记录 handler 返回、可观察 SDK 消息与最终交付。OpenAI 在 on_llm_start 观察实际输入；Claude 现在从已经转发并取得响应的原生 Messages 请求中提取工具结果；原先 UserMessage 观察仅保留为第一步历史证据。截断或替换后的结果不按原完整返回登记为本适配运行可用引用；这里证明消息包含，不证明模型理解，也不把已测小样扩展为任意压缩/大结果配置已验证。

只有 DataService 接受的 deliver 才能产生成功交付；自由文本、非法引用、工具错误与 SDK 终态成功本身均不够。接受的 clarify 产生 needs_clarification，不代表业务完成。OpenAI 通过原生 tool_use_behavior 终止。第一步验收时 Claude 在 accepted deliver 后还有一次原生终态交互；第二步实施检查点已用原生 PostToolUse 的 continue_=False 修正，同一真实 CLI/合成服务正常案例由 9 次变为 8 次请求（核心设计 14.12.16）。最终控制输出保留在原生事件中，不再宣称进入下一次模型请求。澄清后继、两侧受限非终态继续、终态与持久停止的当前离线验收见检查点 16；不能扩为任意中断或真实网关均可恢复。

当前两侧 `run_offline` 必须显式提供 `limits={native_max_turns,max_model_requests,max_request_bytes,max_response_bytes}`，业务工具轮数/墙钟/无进展/费用仍使用上下文 run_policy。`recover=False` 默认不重开未确认原生执行；显式 `recover=True` 先协调已保存的交付/澄清意图及下述普通工具响应/索引效果。已经结束的交付恢复不新增模型请求；OpenAI 满足下文持久状态和时间核对条件时可继续未结束的原运行，后续新请求仍扣原根额度。原生终态未确认时，业务结果与 native_success=false、native_error、execution_time_uncertain 分别保留；普通工具或模型请求中断仍可返回 RECOVERY_REQUIRED。精确运行绑定与根账本不允许通过重试改变。

Prompt 4 检查点 4 新增内部宿主 `application.gateway_batch.create_gateway_batch`：显式冻结批次 UUID、各独立业务根的 context/profile/limits/transport、总费用与请求上限及执行契约 hash，返回各 scope 的 `gateway_binding={batch_ref,scope_id}`。`RuntimeJournal(..., gateway_binding=...)` 只挂接该批次已有账本；不创建第二份额度，不加载凭据，不构成真实调用授权。批次启用后账本或 ready 标记缺失/损坏明确失败；只有未启用的原初始化意图可显式恢复。业务根、原生 session 和批次预算根分别保留；场景取消仅停止自己的 scope，整批停止和未知费用仍约束全部 scope。当前仅支持独立业务根，尚未绑定网关澄清后继；OpenAI 本机网关接线新增于下述检查点 5，Claude 接线见检查点 6；检查点 7 完成双侧同批十场景的本机合成验收，真实网关仍未验收。

`RunQueryResult.mode` 保留 `offline`，另允许明确标识的 `gateway_synthetic` 与 `remote`。合成本机网关的 `real_model_calls=0`、`gateway_cost_usd=null`；真实模式的请求数仅表示该 scope 已登记派发的物理尝试，不证明上游已执行或收费，未知仍单列。真实费用仅在该 scope 全部请求核费完成后给出，否则为 null。`runtime.root_run_id` 仍是业务根，`runtime.budget.root_run_id` 是批次预算根；另保存 `gateway_binding` 和 `control_scope`。交付 `usage` 的请求/费用/预留是整批累计，另有 `budget_root_run_id`、`control_scope_id`、`scope_model_calls`；墙钟仍属于本业务运行。合成网关交付将合成账单放在 `synthetic_cost_usd`，`cost_usd=null`，不把同账本的合成收费当真实收费。旧结果和交付不回填这些字段。

Prompt 4 检查点 5 新增 `agent.openai_runtime.run_gateway(service, context_ref, profile, *, gateway_binding, endpoint, credential, limits, execution_contract=None, checkpoint=None, recover=False, started=None)`，复用原 Runner/approval/RunState 与六工具/终态控制。profile 的 `mode='gateway'` 校验只确认配置和 SDK 版本，不授予调用权限；网关来源由冻结批次决定，合成来源只能访问明确 loopback，真实来源仍需原 HTTP 准入的精确授权契约。当前草案拒绝真实运行，凭据不从环境自动发现，也不保存到运行绑定。

OpenAI 逻辑请求意图的 hash 与原物理请求键共同进入现有账本。原始 HTTP 响应先保存，随后保存 SDK 实际解析结果；恢复继续官方 RunState，只在重建字节、身份、已存响应与核费状态一致时交给官方客户端重新解析原字节，不发 HTTP。已准备请求沿原键派发，未知请求不重发，缺失/冲突不转换成普通成功或自动重试。锁定 OpenAI 3.13.0 会把自定义 transport 的 CatalogError 包装成 APIConnectionError，适配器通过公开 cause 链保留原错误码，其余 SDK 网络异常保持原类型。调用取消会关闭自己持有的传输并等候该请求收尾，未知响应/费用仍保留；检查点 7 的宿主监督已覆盖下述本机故障边界。OpenAI 限定证据见核心设计 14.12.18 检查点 5，Claude 新接线见下文。

Prompt 4 检查点 6 新增 `agent.claude_runtime.run_gateway`，参数在 OpenAI 网关入口基础上增加显式 `cwd`、`cli_path`。它要求隔离 worker 环境，实际凭据只交给宿主 HTTP 层；CLI 仅持有私有 loopback 桥接 token。复用官方 SDK/CLI、MCP、hooks、session/resume；工具结果在实际转发的原生请求中观察，原始 Messages 响应先保存并核费再转交 CLI，不转换协议或构造模型输出。恢复同时核对原 session 历史、完整 HTTP 响应、原业务/scope/profile 及收费状态；核费成功不能补造缺失的原生消息或工具结果。

`GatewayHTTP.observe_bill(request_key)` 使用同一已准入端点、凭据与字节/时限约束，读取 `/v1/generation?id=<原响应明确取得的 generation_id>`。每次调用最多一个 GET，不重试推理；同一原请求最多两次观察，次数在联网前写入原 RunBudget 的 `billing_observations`，中断也占用次数。响应原字节先落盘，再校验身份与 `total_cost` 并结算原预留；已落盘有效账单可直接核对，不再 GET。缺失 generation ID、缺账单、冲突或超限继续保留未知。停止后可在显式剩余查询时限内核费，不解禁模型/业务派发；只读查询不占模型请求数，也不新增费用权威。新账本包含此表，旧账本没有此表时不自动重建或宣称支持该新查询。当前只验证本机合成 generation 响应；真实 OpenRouter 是否返回可用身份、实际路由及收费仍未验证。

Prompt 4 检查点 7 新增 `application.gateway_supervisor.GatewaySupervisor(catalog, context_ref, binding, profile, limits, *, batch_deadline)`。调用方在持有 Catalog 时完成同批次/scope 绑定校验，释放后启动既有 `ObservedWorker`，再调用 `wait(worker, cancelled=...)`。监督者复用唯一 RunBudget，按当前业务剩余时间、显式批次截止及已派发模型/核费请求的时限观察；取消或超时先停止该 scope，再终止并回收所属进程组。账本读取锁等待有限，停止持久化失败仍清理进程并保留原错误，不伪造成功或改写其他 scope。退出后重新打开 Catalog，以 `record(catalog)` 只登记实际 owner 的退出观察，再按现有恢复协议生成结果。此入口不是新的 Agent 循环、账本或通用调度器；当前验证范围为本机 POSIX，短轮询与 OS 调度不提供实时系统保证。

`GatewayHTTP.validate_request` 对真实 OpenRouter 的 Messages 请求要求显式 `thinking={"type":"disabled"}`；省略时返回 `gateway_reasoning_disable_not_transmitted`，发生在预留及连接前。本机诊断捕获仍允许观察锁定 Claude CLI 省略该字段、携带 `output_config.effort=high` 的实际行为，不修改原始字节，也不据此准入真实运行。显式 enabled/adaptive/非法值继续拒绝。SDK 配置 disabled 不等于请求已传达 disabled；该兼容缺口、官方依据和重放证据见核心设计 14.12.18 检查点 7。

当前新增同步 `clarify(context_ref, {question,blocking_need_ids}, state=..., request_key=..., recover=False)`，返回 `{kind:needs_clarification, clarification, clarification_object}`。它保存完整原问题与不可变澄清；同键显式恢复保留同一 ID/字节。回答通过 `create_context` 的 revises_context_ref/clarification_response 提交完整字段，相同完整回答及策略复用唯一后继，改变回答报 CLARIFICATION_MISMATCH；创建中断用 recover=True 补齐。后继 continuation 额外保存 root_context_ref；原 clock、计划/历史、业务计数/时间及根账本继承，旧引用须重新读取。业务 Session 为 needs_clarification，该次 Catalog 执行为 completed；正常后继开启新原生 session。根物理请求累计不清零，根请求/响应字节限制不扩大，业务范围和策略只可收紧。未确认执行时间仍阻止后继创建；受观察的原运行可以按下文核对后继续。非澄清修订和 analysis_agent 的 prior_delivery_refs 继续明确拒绝，不据此提前声明补数衔接已实现。

检查点 14 固定离线异步入口的取消语义：取消任一正在等待同一 `run_offline` 执行的调用者，表示请求取消该共享运行。宿主先停止原根账本，再向 SDK 发送一次取消；重复取消等待同一收尾，两位调用者取得同一持久结果。适配器吞掉取消异常也不能继续新请求或业务工具，已完成/结果未知的响应仍按原账本保存。当前不建 HTTP 服务；后续传输入口按下述检查点 15 规则将运行调用者断连映射为取消，不把观察连接或普通读取等同于运行调用者。合作退出失败仍需所属 worker 的监督与实际退出核对，不声称能够抢占任意同步代码。Claude 自动压缩请求已纳入当前 Messages 边界；当前 OpenAI 装配未启用 Session 压缩器/Sandbox/Memory，新配套不能凭本批结果直接放行。

检查点 15 增加统一 Python 入口 `DataService(catalog, acquisition_adapter=None, query_runtime=None)` 与 `await service.run_query(context_ref, recover=False)`。query_runtime 是显式绑定的异步调用对象，接收 service、context_ref、recover 和由 DataService 捕获的单调起点 started；两侧直接绑定既有 SDK run_offline，仍只有一个 native 执行登记与根账本。未配置 runtime 返回 CAPABILITY_UNSUPPORTED；非法 recover 或已关闭 Catalog 在调用 runtime 前拒绝。入口不发现凭据、不选择默认模型、不隐式启动真实请求，当前只验收离线绑定。有效调用从 DataService 入口计时，恢复/重放沿原绑定规则；只读取结果继续使用 read_run_result。

调用者显式取消，或宿主因运行调用者断连而取消 run_query 的等待任务，都请求停止同一共享运行并等待收尾；不自动创建脱离调用者的后台任务。其他只读观察者断开不改变运行。正式 MCP/CLI 尚未接入，本步只证明进程内 asyncio 取消与受观察进程退出后的业务结果。进程被监督终止后须记录所属进程的实际退出，再显式 recover=True；未知请求继续保留，不以进程退出证明未收费。

装配示意（变量均由调用方显式提供，scripted_model 仅为合成测试模型）：

```python
from functools import partial
from uteki.data_platform.agent.openai_runtime import run_offline
from uteki.data_platform.service import DataService

service = DataService(catalog, query_runtime=partial(
    run_offline, profile=loaded_profile, model=scripted_model, limits=limits,
))
result = await service.run_query(context_ref, recover=False)
```

Claude 使用其独立 run_offline 绑定 profile、limits、隔离 cwd 和安装的 cli_path，不传 OpenAI Model 对象；本机离线环境限制保持。配置文件载入发生在调用方，started 是宿主内部计时参数，不作为模型工具参数或用户可扩大额度的入口。

检查点 4 增加 `service.call(..., recover=True)`（六工具便捷方法同样支持）：必须匹配已接受操作的原请求/state/request_key；已保存完整 response_intent 时确认同一响应、引用和用量，不重新读取或执行工具。仅派生索引副作用已提交时，可核对冻结 generation/manifest、来源、文件 hash 和当前 head，再确认原索引；不会激活尚未发布的 generation 或覆盖不同 head。此分支响应包含 recovery、elapsed_lower_bound_ms，elapsed_ms=null、execution_time_uncertain=true，inspect_context 同时展示未确认时间，后续动作暂不能继续。目录同步结果不确定时抛 RECOVERY_REQUIRED 并保留 accepted 操作，不再作为普通工具 error 返回。两侧 run_offline(recover=True) 可协调这些原响应并保存到原生工具调用记录；没有终态时仍返回 recovery_required，不调用模型、不宣称原生会话已经恢复。官方 acquire 的同一原请求现可核对持久计划、receipt、输入清单及 snapshot/representation/recipe/run：仅确认已经移入最终目录的同一发布，不重新获取或解析，不执行全目录恢复；保留原 job/AssetRef、附件缺口与实际记录的传输用量。仅取得原件或尚无最终发布仍抛 RECOVERY_REQUIRED，并保留原操作，不假装成功。receipt 保存失败、发布待确认或目录同步不确定均不能作为普通可重试工具错误；取消时若发布已确定则仍返回取消及实际副作用，若发布待确认则先要求恢复核对。恢复后的 elapsed_ms 仍为 null，execution_time_uncertain=true；确认资产发布不代表原生会话或业务任务已经完成。检查点 5 的两侧 SDK 恢复未增加模型请求或下载；受观察运行的时间核对见下文；一般非终态续跑尚未完成。

内部宿主可用 `application.execution_clock.ObservedWorker` 持有实际子进程，`wait(timeout=...)` 确认所属进程组退出后，在重新取得 Catalog 所有权时 `record(catalog, context_ref)` 保存不可变观察；该能力不向业务工具/MCP 暴露，也不接收模型提供的 elapsed 数值。后续 `run_offline(recover=True)` 核对原 PID、单调时钟域、起点、native session 和上下文，在原副作用协调后按耗时上界扣减累计 wall_seconds；`runtime.time_reconciliation` / `inspect_context.time_reconciliations` 明确 `supervised_upper_bound`、已知下界和观察引用，不能把它当精确耗时。观察结束后的等待不计入，重复核对不重复扣减；历史未知记录和旧交付保持。澄清后继继承累计预算及时间依据，并重新读取证据。没有有效观察、跨时钟域或旧格式缺少 clock 时仍保留未核对；普通执行不因无权读取系统启动元数据而失败。已核对时间不代表未知模型响应/费用已解决，也不代表一般原生会话已经续跑。

新写入的 execution_clock 使用 `domain_version=2`，macOS 启动标识不包含时区格式化文本；原生执行和恢复宿主均按保存的版本核对。缺少版本字段视为旧 v1，仍使用原字节算法，不改写旧记录。宿主可绑定同域旧 worker；旧记录因时区不同而无法验证、未知版本或真正跨启动周期时仍返回 RECOVERY_REQUIRED，不能改用新 hash 或清零耗时。

根账本持久停止对恢复和正在执行的两套 SDK 同样生效：动作/请求准入核对根停止，后来的超时或额度信号不能替换首次停止原因。允许保存迟到响应及确认已发生效果，不再执行保存响应里的新工具动作或重新进入原生会话。此前执行时间未核验时仍返回 recovery_required，持久取消不能代替退出观察；已接受交付或澄清及其原结果保持，不因更晚的根停止被撤销。

检查点 7 增加 OpenAI 非终态继续：原生工具 approval interruption 保存官方 RunState，宿主依据既有工具授权自动批准；业务权限检查仍在共享工具内执行，不新增用户确认。恢复校验 context/native session/profile/SDK 版本及请求前缀，通过官方 `RunState.from_json` 继续原 Runner 状态；账本已保存的完整响应只在重建请求完全相同时读回，prepared 请求沿原键发出，未知响应不重发。状态缺失、损坏、版本或请求不符明确 recovery_required；旧运行不补造 SDK 状态。原执行必须有可核对退出观察；新执行段保留旧段、累计时间和根预算，不能沿用旧段观察。checkpoint 中已观察引用恢复同一原生运行的可见前缀，其后工具结果仍需进入 SDK 模型输入；澄清新上下文依旧重读。此检查点不覆盖 Claude 续跑；其后新增范围见下段。未发布获取和全部辅助请求仍未完成，一次索引中断的时间核对失败尚未解释，最新正例通过不等于所有中断均可恢复，见核心设计 14.12.16。

检查点 8 增加 Claude 已保存完整工具结果后的继续：`run_offline(..., recover=True)` 先协调原副作用、预算与退出时间，再核对隔离目录、SDK/CLI 绑定、原始输入、SDK 实际输出的 assistant 消息及原工具 ID/参数/结果，通过公共 `get_session_messages` 和 `resume=<原 session ID>` 继续，不 fork 或改写 transcript。实际转发的首个恢复请求还须携带相同工具历史，之后才登记可见证据。锁定 CLI 插入的精确 `No response requested.` 分隔文字单独记为原生控制标记，不作为模型事实；任意追加 assistant 内容不能因此放行。历史丢失/改动、待执行工具、原生取消替代结果、未观察到的模型响应及未知费用仍返回 recovery_required，不创建新会话掩盖缺口。已通过四个工具后退出位置的续跑与根请求上限验证；尚未证明任意中断均可继续。

检查点 9 增加宿主同步入口 `resolve_update(context_ref, request_key=原工具请求键, action="continue_local"|"close")`，不向模型或外部 MCP 开放。`call(..., recover=True)` 的确认既有结果语义保持。继续只使用原完整输入、收据、计划及已冻结 recipe，核对原 adapter 绑定、归属、根账本和实际退出观察；沿同一 snapshot/build/job 在本地完成，不发获取或模型请求。原运行及本地处理的每次中断分别核对时间，不能复用上一段退出观察。未封存产物按原输入/recipe 重做时已有字节必须相同；封存文件缺失或损坏不重建，保持明确错误。原已提交响应原样读回。

`close` 返回 `status=error / error.code=ACQUISITION_CLOSED`，`error.details.retained_ref` 指向保留记录，`transport_outcome_unknown` 区分在途或旧记录缺证据的传输。它核对已登记原件并只关闭原操作所属的未发布候选，保留原文件/收据和已冻结快照；最终 build 已存在时必须先确认，不能用关闭撤销发布。继续失败后可显式转为关闭并保留原处理历史；关闭后不能再用同键重开。缺少本机原生退出观察时不转移执行权；旧纯同步获取可关闭，但未知执行时间仍保留。关闭不清除根停止、未知费用或费用预留。宿主完成业务操作不补造 SDK 原生 transcript，也不自动启用原生续跑。

时间观察核对失败保留具体原因；`runtime.time_reconciliation_failures` 返回不可变诊断对象引用，宿主可通过内容存储核对原观察、时钟域、已知耗时与上界。这是执行诊断，不是业务证据，也不解除时间/费用未知限制。新增诊断没有解释早期未重现的时钟失败，不能记作该问题已修复。

同步 `deliver(..., recover=True)` 按原请求及 request_key 恢复持久 terminal_intent 中的同一包；缺少原意图的旧中断不重新生成。新增内部宿主收尾 `force_delivery` 不向模型或外部 MCP 开放，使用最近接受的 state 和原生可见引用，不增加业务工具轮数。交付新增 business_status（completed/partial/cancelled），停止原因及根账本 usage；对 SDK 离线运行明确 real_model_calls=0、synthetic_cost_usd=0、cost_usd=null，未知请求数量仍保留，不能将无真实账单写成已核验收费 0。旧交付不回填这些新字段。

当前 profile 与入口限定离线；OpenRouter 配置描述保留精确协议、模型、上游与禁止 fallback 的边界，不表示真实网关已接通。Claude 明确使用 default 权限模式、业务工具白名单及 PreToolUse 检查；空 setting_sources/skills/plugins 不被表述为原生内置 Skills 已全部禁用，后续原生配套单独核验。证据和停止/继续准入见核心设计 14.12.15。

初始化中断的离线恢复沿用 `recover=True`。新格式 native `phase=initializing` 保存原身份和根策略；原宿主已被实际观察退出后，可以确认原初始账本发布并以同一 native ID 首次进入 SDK，原执行与恢复耗时继续累计。根账本描述确认 ready 后，缺失、损坏或不一致不会从初始字节对象重建；初始对象只是未启用阶段的发布输入，不是第二份费用权威。缺少退出观察、已有该上下文的模型/原生工作或旧格式缺少创建意图时不按“尚未开始”重开。恢复原生执行仍走既有 SDK checkpoint/session 协议，不能用初始化路径绕过请求未知、旧会话或根停止状态。限定证据及未覆盖的启动/收尾边界见核心设计 14.12.16。

### 0.1 调用方与传输

| 调用方 | 传输 | 说明 |
|---|---|---|
| Data Agent 模型 | 原生工具调用，由运行框架执行 | 模型只提供工具参数；`context_ref` 由框架补入，模型不能更换 |
| 分析 Agent、用户页面 | Python 进程内调用 `DataService` | 通常调用 `create_context` + `run_query`；也可直接调用读取工具 |
| 外部 MCP 宿主 | MCP v2（stdio） | 见第 11 节；直接调用读取工具的结果不是 Data Agent 交付 |

三种调用使用同一组 pydantic 契约；工具 JSON Schema 与 MCP schema 由契约导出。模型看到的文本输出（第 8 节）与程序侧结构化响应分属两层。

### 0.2 字段与取值规则

- 字段名使用 `snake_case`；未知字段、类型错误、空字符串和首尾带空白的标识一律报 `INVALID_REQUEST`，不静默修正。
- `null` 表示未知；空数组表示“确定没有”，二者不互换。请求中允许省略的字段，省略即不增加该条件。
- 数值一律以十进制字符串传递（如 `"1234.50"`），避免浮点误差；单位与 scale 单列。
- 数组过滤中，同一数组内为 OR，不同字段之间为 AND。

### 0.3 共同响应信封

六个数据工具的响应使用下列信封；`create_context` 使用第 1 节响应，`run_query` 及其 clarify / deliver 控制分支使用第 9 节返回类型：

| 字段 | 类型 | 规则 |
|---|---|---|
| `operation_id` | string | 本次工具调用标识，关联实际参数、使用的版本与运行记录 |
| `status` | string | `ok`：正常完成；`partial`：有可用结果，但存在缺口、未解决匹配或执行截断；`error`：未成功执行 |
| `items` | array | 本页结果；失败时为空数组，须结合 `status` 判断 |
| `next_cursor` | string 或 null | 下一页入口；null 不单独证明范围已查完 |
| `truncated` | boolean | 是否因资源或长度上限提前停止；普通分页不算截断 |
| `coverage` | object | 本次操作实际评估的范围，结构随工具而定；不表示研究问题已获得完整证据 |
| `issues` | Issue[] | 操作级缺口；条目自身问题放在对应 item 中 |
| `error` | Error 或 null | 失败时返回稳定 `code`、可读 `message` 与可选 `details`；调用方不解析报错文案 |
| `resource_usage` | object | `elapsed_ms`、`external_calls`、`model_calls`、`cost_usd`（无费用为 `"0"`） |

**Issue：**`{code, message, target_ref?, details?}`。**Error：**`{code, message, details?}`，`code` 取自 0.9。

### 0.4 资产引用 `AssetRef`

```json
{"asset_id": "as_01J9DEMO", "snapshot_id": "sn_01J9DEMO", "representation_id": "rp_01J9DEMO", "build_id": "bd_01J9DEMO"}
```

- 四个字段共同固定“哪份材料、哪次原件、哪种表现形式、哪个处理版本”。读取工具只接受完整引用，不隐式跳到最新版本。
- 只有原件、尚无 published build 时 `build_id=null`；此时读取正文的工具返回 `BUILD_NOT_READY`，不代为启动处理。
- 块、章节、表格、图片、记录的 ID 只在所属 build 内唯一，必须与 `AssetRef` 一起使用。

**可交付引用 `ResultRef`：**`{run_id, operation_id, kind: evidence / record / calculation / metadata, item_id}`。它定位一次工具调用实际交给模型的结果，不代替 `AssetRef` 或原文地址。`item_id` 为宿主登记结果时分配的标识；业务 evidence_id / record_id / calc_id 另行保留，资产引用仍保存在被引用条目中。metadata 是登记或解析元数据，不是原文业务事实。

- `search_asset` 返回的原文、`read_evidence` 证据、`query_records` 记录与计算共用该引用。仅有命中位置、目录摘要、模型生成摘要时，不登记为原文证据。
- 宿主在格式化后登记实际展示的内容与范围，保存 `result_ref`、完整 `asset_ref`、locator、截断状态及依赖引用。保存在程序侧但未展示的内容不可用于交付；模板再次缩短片段时，登记的证据也必须缩短到实际展示范围。
- 模型使用 `result_refs` 引用登记结果；宿主校验运行归属、类型、条目存在及范围。Data Agent 交付只接受当前运行登记的引用。外部直接读取使用宿主分配的读取运行 ID，不能将这些引用直接带入另一次 `run_query` 交付。
- 计算引用所需的原始记录、证据所需的上下文均作为依赖登记，交付时递归纳入。引用存在只证明读过该范围，不证明足以支持需求。

### 0.5 时间与期间

- **`TemporalValue`：**`{value, precision}`，`precision` 为 `datetime / date / month`。`datetime` 用 ISO 8601 并带时区偏移（`Z` 或 `±hh:mm`）。未知为 null，并在所属对象的 `unknown_reasons` 中说明：`not_disclosed_by_source / not_processed / not_applicable / conflict`。
- **请求中的时间边界**（`as_of`、范围的 `gte` / `lt`）必须是带时区的 datetime；拒绝无时区时间和纯日期。
- **比较规则：**date 与 month 精度的值视为区间，按“最早时区起点到最晚时区终点”的保守边界与请求比较；完全满足为 matched，跨越边界为 unresolved（核心设计 14.2）。
- **`FiscalPeriod`：**`{label, fiscal_year, fiscal_quarter, start, end, basis}`，`basis` 为 `source / derived_from_fiscal_year_end / unknown`。请求中可只给 `label`（如 `FY2025`），按主体已登记的财年解释；主体没有财年依据时，期间匹配为 unresolved，不默认等于自然年。

### 0.6 证据地址 `Locator`

`Locator` 是带 `type` 字段的联合类型：

| `type` | 字段 |
|---|---|
| `pdf_region` | `block_id`、`page_index`（物理页，1 起）、`page_label`（印刷页码，可空）、`bbox: [x0, y0, x1, y1]`、`coord_system: "pdf_pt_top_left"`、`char_range`（可空） |
| `html_node` | `block_id`、`dom_path`（针对冻结快照）、`char_range`（可空） |
| `table_cell` | `table_id`、`row`、`col`（0 起）、`row_span`、`col_span`、`anchor`（底层 `pdf_region` 或 `html_node`） |
| `image_region` | `image_id`、`bbox`、`coord_system: "image_px_top_left"` |
| `record_field` | `record_id`、`field`、`shard_id`（可空）、`json_pointer`（可空）、`source_node`（iXBRL 记录对应的 `html_node`，可空） |

`char_range` 为 `[start, end)`，基于该块规范化文本的 Unicode 码点偏移。每个返回的 locator 都可以原样交给 `read_evidence` 读回。

### 0.7 状态枚举

| 枚举 | 取值 | 用于 |
|---|---|---|
| readiness | `ready / partial / not_ready / failed / not_applicable` | 资产各能力：`original`、`structure`、`tables`、`images`、`ocr`、`concepts`、`text_search`、`records` |
| match.status | `matched / unresolved` | `find_assets` 候选 |
| coverage.status | `complete / partial / not_started` | 操作级评估范围 |
| need.status | `supported / partial / unresolved` | 交付包中的需求 |
| run.status | `running / completed / partial / failed / cancelled / needs_clarification` | `run_query` |
| update.status | `completed / partial / denied / failed` | `request_asset_update` |

### 0.8 分页与游标

- 游标是不透明字符串，绑定：上下文、工具名、全部业务请求参数（游标本身除外）、目录或 build 版本、`limit`。翻页时只替换 `cursor`，其余业务参数必须原样不变，否则报 `CURSOR_MISMATCH`；运行时公共参数 `state` 不参与绑定，可以随轮次更新。
- 目录或版本已无法重现旧视图时报 `CURSOR_EXPIRED`，不改用最新内容。
- 同分结果按完整引用固定排序，保证翻页不重不漏。
- find_assets 冻结候选身份、匹配和排序的目录视图；readiness 为每次读取时的实时能力，不参与本实现的过滤/排序，也不是冻结值。派生索引故障可使后页 readiness 变化而目录游标继续有效；若未来按 readiness 过滤/排序，必须将该状态纳入视图。本次排序协议版本参与目录游标，升级前旧排序游标明确 CURSOR_EXPIRED，不能带原 offset 混用新排序。query_records/search_asset 的派生内容查询仍绑定其 index generation。

### 0.9 错误码

| code | 含义 |
|---|---|
| `INVALID_REQUEST` | 参数缺失、类型错误、取值越界、未知字段、时间格式错误 |
| `PLAN_VERSION_MISMATCH` | `plan_update.base_version` 不等于当前已登记计划版本 |
| `RESULT_REF_INVALID` | 引用未登记、类型不符、属于其他运行或未实际展示 |
| `CLARIFICATION_MISMATCH` | 澄清 ID 与前序上下文不对应，或同一澄清已有不同的后继上下文 |
| `CONTEXT_NOT_FOUND` | `context_ref` 不存在或其状态无法读回 |
| `CONTEXT_INVALID` | 创建/恢复数据损坏或不一致，拒绝重置已完成状态 |
| `RECOVERY_REQUIRED` | 持久化结果未确认，需按对应显式恢复协议处理，不盲重执行 |
| `CANCELLED` | 同步执行已观察到取消；结合 effects 判断已经发生的动作 |
| `SCOPE_DENIED` | 请求超出上下文的主体、来源、截止日或权限边界 |
| `ENTITY_NOT_FOUND` | 名称或代码在已登记目录中找不到 |
| `ENTITY_AMBIGUOUS` | 名称或代码对应多个主体或证券；`details.candidates` 列出候选 |
| `ENTITY_MISMATCH` | 同一请求中的名称、代码与 ID 解析结果不一致 |
| `ASSET_NOT_FOUND` | 引用的资产、快照、表现形式或 build 不存在 |
| `VERSION_MISMATCH` | 引用的四个字段不属于同一条版本链 |
| `BUILD_NOT_READY` | build 为空或所需能力不是 `ready / partial` |
| `CAPABILITY_UNSUPPORTED` | 资产没有该能力，如对无记录的文档调用 `query_records` |
| `TARGET_NOT_FOUND` | 块、表格、图片、记录或章节 ID 在该 build 中不存在 |
| `CURSOR_MISMATCH` / `CURSOR_EXPIRED` | 见 0.8 |
| `POLICY_DENIED` | 补数动作被来源策略或扩展策略拒绝 |
| `BUDGET_EXCEEDED` | 剩余预算不足以执行本次动作 |
| `CATALOG_UNAVAILABLE` | 元数据目录无法读取 |
| `INTERNAL_ERROR` | 未分类的内部错误；保留复现信息 |

## 1 `create_context`：建立请求上下文

上下文一经建立不可修改；需要澄清或改变范围时新建上下文，并用 `revises_context_ref` 关联。原始问题与回答分别保存，不能用回答覆盖原问题。

### Request

| 字段 | 类型 | 必填 | 规则 |
|---|---|---|---|
| `question` | string | 是 | 原始问题，原样保存 |
| `caller` | object | 是 | `{kind: user / analysis_agent, prior_delivery_refs: []}`；补数时引用原交付包 |
| `revises_context_ref` | string | 否 | 被补充或修订的上下文；继续同一任务时必填，宿主据此继承根运行与账本 |
| `clarification_response` | object | 否 | `{clarification_id, answer}`；回答第 9.1 节澄清时必填，且必须同时给出匹配的 `revises_context_ref` |
| `entities` | object | 否 | `company_ids`、`company_names`、`securities: [{ticker, exchange_mic?}]` 任选；全部在已登记目录中解析 |
| `periods` | FiscalPeriod[] 或日期区间 | 否 | 显式期间；相对时间（如“去年”）不在此解析，由 Data Agent 结合 `clock` 澄清后填写 |
| `as_of` | datetime | 否 | 历史可得截止时间；省略表示不做历史截止日限制 |
| `source_policy_ref` | string | 是 | 来源策略版本，决定允许读取与获取的来源 |
| `expansion` | object | 是 | `{mode: disabled / controlled, allow: [], deny: []}`；controlled 时 allow 不能为空，deny 优先 |
| `run_policy` | object | 是 | `{max_usd, max_turns, max_wall_seconds, max_no_progress_turns}`，全部显式给出 |

### Response

| 字段 | 说明 |
|---|---|
| `context_ref` | `req_` 标识 |
| `clock` | 原任务建立上下文的时刻（带时区），相对时间以此为准；继续时继承 |
| `created_at` | 本上下文实际登记时刻（带时区） |
| `resolved_entities` | 每项含输入值、`company_id`、规范名称及匹配的证券（`security_id`、ticker、MIC、share_class、有效期） |
| `unresolved` | 未能解析的输入及原因；存在歧义时直接报 `ENTITY_AMBIGUOUS`，不建立上下文 |
| `effective_policy` | 实际生效的来源、扩展和运行策略 |
| `continuation` | 首次为 null；继续时为 `{revises_context_ref, prior_run_id, root_run_id, clarification_id}`；非澄清修订的 `clarification_id` 为 null，归属由宿主解析 |

证券代码按 `clock` 或 `as_of` 时点解析；一个公司有多个证券时全部列出，并保留用户原始输入的证券，供后续股价、每股指标类问题使用。

**澄清后继续：**调用方重传完整上下文字段，`question` 保留原始问题，回答写入 `clarification_response`，已澄清的主体、期间等写入对应字段。宿主校验字段类型、身份/期间依据及原边界；回答原文留存，不声称程序已验证任意自然语言与字段的语义一致性。缺少可验证字段时不猜测填充，后续运行仍可返回澄清或缺口。`clock` 沿用原任务的解释时点，新的登记时间另记 `created_at`，避免跨日回答使“去年”漂移。

- 澄清只补明未决值或收紧范围，不自行扩大主体、来源或截止日边界；扩大范围须有调用方的明确授权，不能仅由模型的澄清请求授权。
- 同一任务的修订/补数继续使用原 `root_run_id`。`run_policy` 各上限只能相同或更紧；已用费用、未知预留、轮数、连续无进展计数与已用执行时间继续累计，等待人工回答的时间不计入执行时间。剩余额度由根账本计算，不把新上下文的上限当作新增额度；未知费用先对账。
- 同一个 `clarification_id` 最多关联一个后继上下文；完全相同的重复提交返回原后继引用，改变答案的重复提交报 `CLARIFICATION_MISMATCH`，避免响应丢失造成重复继续。
- 前序需求计划及历史传入后继运行；旧结果只作追溯入口。新运行使用旧证据前，须按固定资产引用重新读取或查询并通过新上下文范围检查，生成本运行的 `ResultRef`，不复制旧的“已满足”状态。

## 2 `find_assets`：找资产

### 2.1 Function 参数（模型可见）

```json
{
  "query": "annual report",
  "filters": {
    "company_ids": ["co_01J9DEMO"],
    "asset_kinds": ["document"],
    "material_types": ["sec_10k"],
    "reporting_periods": ["FY2025"],
    "published_at": {"gte": "2026-01-01T00:00:00Z", "lt": "2026-04-01T00:00:00Z"}
  },
  "as_of": null,
  "limit": 10,
  "cursor": null,
  "state": {
    "plan_update": {"base_version": 0, "needs": [{"need_id": "need-1", "description": "取得 FY2025 收入及原文依据", "required": true}]},
    "satisfied": [],
    "gaps": [{"need_id": "need-1", "missing": "尚未查找资产", "result_refs": []}],
    "next_action": "find_assets",
    "reason": "先定位所需年报"
  }
}
```

| 字段 | 类型 | 必填 | 规则 |
|---|---|---|---|
| `query` | string | 否 | 匹配标题、公司名、别名、证券代码及派生摘要；不能覆盖过滤条件 |
| `filters` | object | 否 | 下表；与 `query` 至少一项非空 |
| `as_of` | datetime 或 null | 否 | 省略继承 context.request.as_of；其为 null 时无历史截止限制。不要把解释时钟 clock/created_at 自动填入。显式值只能收紧上下文；晚于上下文报 SCOPE_DENIED，时效缺证明仍留缺口 |
| `limit` | integer | 否 | 1–50，默认 10；越界报错，不截成合法值 |
| `cursor` | string 或 null | 否 | 见 0.8 |

| 过滤字段 | 类型 | 含义 |
|---|---|---|
| `company_ids` | string[] | 公司 ID；必须在上下文主体范围内 |
| `company_names` | string[] | 正式名称或别名，在已登记目录中解析为 ID |
| `securities` | object[] | `{ticker, exchange_mic?}`，经证券映射解析到公司；结果保留输入证券 |
| `roles` | string[] | 公司与资产的关联角色 `issuer / subject / mentioned`；省略时为 `issuer` 与 `subject` |
| `asset_kinds` | string[] | `document / dataset` |
| `material_types` | string[] | 目录中已注册的精确分类名，不猜测为表单标题。未知值报 INVALID_REQUEST，指出字段/值及最多 25 个注册名；不确定时可省略可选筛选，通过 query 发现后读取 metadata.material_type |
| `formats` | string[] | `pdf / html / xbrl_instance / api_json` |
| `reporting_periods` | string[] | 报告期间标签 |
| `content_periods` | string[] | 内容覆盖期间；命中任一即为候选 |
| `published_at` | object | `{gte?, lt?}`，至少一项，双边时须 `gte < lt` |

名称、证券与 ID 同时提供时，解析结果必须一致，否则报 `ENTITY_MISMATCH`；找不到或多义分别报 `ENTITY_NOT_FOUND`、`ENTITY_AMBIGUOUS`，不自动选首项。解析只查已登记目录，不触发外部搜索。

**硬边界与未知值：**主体、来源与 `as_of` 是硬边界，未经验证满足边界的资产不作为合格候选。期间、发布时间等匹配元数据未知时，资产以 `match.status=unresolved` 返回并列出未解决字段；可得时间未知导致无法判断截止日的，记入操作级 issues。

### 2.2 Response items

```json
{
  "asset_ref": {"asset_id": "as_01J9DEMO", "snapshot_id": "sn_01J9DEMO", "representation_id": "rp_01J9DEMO", "build_id": "bd_01J9DEMO"},
  "asset_kind": "document",
  "title": "Example Corp Annual Report on Form 10-K for fiscal year 2025",
  "summary": "Example Corp｜10-K｜FY2025｜HTML｜内容期间 FY2023–FY2025｜概念标注部分完成",
  "metadata": {
    "entity_refs": [{"company_id": "co_01J9DEMO", "name": "Example Corp", "role": "issuer"}],
    "matched_securities": [{"security_id": "sec_01J9DEMO", "ticker": "EXM", "exchange_mic": "XNAS"}],
    "material_type": "sec_10k",
    "format": "html",
    "reporting_period": {"label": "FY2025", "fiscal_year": 2025, "fiscal_quarter": null, "start": "2025-01-01", "end": "2025-12-31", "basis": "source"},
    "content_periods": ["FY2023", "FY2024", "FY2025"],
    "published_at": {"value": "2026-02-04T16:05:12-05:00", "precision": "datetime"},
    "available_at": {"value": "2026-02-04T16:05:12-05:00", "precision": "datetime"},
    "publisher": {"name": "Example Corp", "company_id": "co_01J9DEMO"},
    "platform": "SEC EDGAR",
    "source_urls": ["https://www.sec.gov/Archives/edgar/data/0000000000/000000000026000001/exm-20251231.htm"]
  },
  "versions": {"other_builds": 1, "revision_relations": [{"kind": "amended_by", "asset_id": "as_01J9DEMP"}]},
  "readiness": {"original": "ready", "structure": "ready", "tables": "ready", "concepts": "partial", "text_search": "ready", "records": "ready"},
  "match": {"status": "matched", "matched_fields": ["query", "company_ids", "material_types", "reporting_periods", "published_at"], "unresolved_fields": []},
  "issues": [{"code": "CONCEPT_INDEX_PARTIAL", "message": "部分章节尚未完成概念标注"}]
}
```

- `summary` 由已登记元数据按模板生成，未知项写“未知”；程序不得从 `summary` 反解析字段。
- 每个（资产、快照、表现形式）返回一项，`build_id` 为其最新 published build；`versions.other_builds` 给出其余 build 数量，修订关系单列（核心设计 14.5）。不同快照、表现形式或修订资产分别成为候选，不按标题合并。
- `coverage`：`{status, catalog_revision}`；`catalog_revision` 固定本次搜索的目录视图。

### 2.3 空结果、部分结果与错误

| 情况 | 返回 |
|---|---|
| 范围内无匹配 | `status=ok`、`items=[]`；不解释为未披露 |
| 有下一页 | `status=ok`、`next_cursor` 非空、`truncated=false` |
| 期间等元数据未知，或部分范围无法评估 | `status=partial`，在 `match` 与 issues 中说明 |
| 名称、代码无法解析或冲突 | `status=error`，`ENTITY_*` |
| 截止日越界 | `status=error`，`SCOPE_DENIED` |

`find_assets` 的 `resource_usage.external_calls` 必须为 0：它只查已登记目录，不触发获取或处理。

## 3 `get_asset_schema`：获取资产说明与读取入口

返回选中资产指定版本的说明，对应核心设计第 7.2.2 节的九类信息；正文由后续工具读取。内容说明来自该 build 发布时生成的 `asset-schema.json`，查询时不重新生成。宿主另查询派生索引的当前状态，合成实时 `readiness` 与 `capabilities`；不改写冻结文件。

### Request

| 字段 | 类型 | 必填 | 规则 |
|---|---|---|---|
| `asset_ref` | AssetRef | 是 | 完整引用 |
| `facets` | string[] | 否 | `overview / outline / fields / concepts / coverage / readiness / capabilities`；readiness 同时返回内容/发布/当前状态及 availability。省略时返回 overview、readiness、capabilities 与一级 outline 或 fields 摘要 |
| `outline` | object | 否 | `{parent_section_id: null 或 ID, depth: 1–3}`，用于展开目录 |
| `field_group` | string | 否 | dataset 的字段组展开 |
| `limit`、`cursor` | | 否 | 目录节点或字段的分页 |

### Response item

| 字段组 | 内容 |
|---|---|
| `overview` | 标题、语言、`asset_ref`、来源（发布方、平台、原始链接）、类型（资产类别 / 材料类型 / 表现形式）、关联公司及角色、时间（报告期间、内容期间、发布、获取、可得及依据）、派生内容概述（标注生成方式与版本） |
| `content_readiness`、`published_readiness` | 冻结内容的能力上限、发布时内容与派生层合成的状态；均取自冻结说明 |
| `readiness` | 当前有效状态及未完成位置；内容可用且所需派生层可用时才可宣告 ready，规则见核心设计 14.5 |
| `availability` | `{observed_at, derived_indexes: [{kind, backend_version, status, file_sha256}]}`；记录此次状态依据，缺失或校验失败附 issue |
| `capabilities` | 可用的工具与模式，如 `search_asset.outline`、`search_asset.text`、`search_asset.concept`、`read_evidence`、`query_records` |
| `outline`（document） | 节点 `{section_id, title_raw, canonical_section, mapping_status: explicit / inferred / unmatched, origin: source / inferred, child_count, block_count, page_range}`；含显式的“未归属块”节点 |
| `fields`（dataset） | `{name, type, concept_id, unit, period_semantics: instant / duration, nullable_meaning, dimensions}`、允许的过滤与计算、分片与版本一致性状态 |
| `concepts` | 已标注概念、角色、目标数；附概念标注的覆盖范围 |
| `coverage` | 已处理与未处理范围：未读图片、失败表格、OCR 未处理页、未分类块等 |

以下为内容字段节选，完整响应还含上述发布状态与实时状态依据：

```json
{
  "asset_ref": {"asset_id": "as_01J9DEMO", "snapshot_id": "sn_01J9DEMO", "representation_id": "rp_01J9DEMO", "build_id": "bd_01J9DEMO"},
  "overview": {"title": "Example Corp Annual Report on Form 10-K for fiscal year 2025", "material_type": "sec_10k", "format": "html", "language": "en"},
  "readiness": {"structure": "ready", "tables": "ready", "images": "partial", "concepts": "partial", "text_search": "ready", "records": "ready"},
  "capabilities": ["search_asset.outline", "search_asset.text", "search_asset.concept", "read_evidence", "query_records"],
  "outline": {"nodes": [
    {"section_id": "sec-0003", "title_raw": "Item 1. Business", "canonical_section": "business", "mapping_status": "explicit", "origin": "source", "child_count": 6, "block_count": 84, "page_range": null},
    {"section_id": "sec-unassigned", "title_raw": null, "canonical_section": null, "mapping_status": "unmatched", "origin": "inferred", "child_count": 0, "block_count": 3, "page_range": null}
  ], "has_more": true},
  "coverage": {"images_unread": 4, "tables_failed": 0, "blocks_unclassified": 112}
}
```

`concepts` 只统计已建立的标注；未命中不表示材料未披露。是否有结构化记录由 content_readiness 判定，当前没有 `query_records` 入口也可能只是派生视图失效，须结合缺口原因判断。

`find_assets` 与读取工具使用同一有效能力规则。索引在两次调用间失效时，读取工具重新检查并报 `BUILD_NOT_READY` 及具体 issue；不得沿用旧说明宣告可用，也不静默切换到新 build。`content_readiness.records=not_applicable` 表示没有记录能力，报 `CAPABILITY_UNSUPPORTED`；已有记录但派生视图不可用属于暂不可读，两者区分。

## 4 `search_asset`：在资产内定位

### Request

| 字段 | 类型 | 必填 | 规则 |
|---|---|---|---|
| `asset_ref` | AssetRef | 是 | |
| `mode` | string | 是 | `outline / text / concept` |
| `outline` | object | mode=outline 时 | `{section_id: null 或 ID, depth: 1–3}` |
| `text` | object | mode=text 时 | `{match: phrase / all_terms / any_terms / regex, value, case_sensitive: false}`；regex 长度 ≤ 200，使用线性时间引擎 |
| `concept` | object | mode=concept 时 | `{concept_id, roles: [], dimensions: {}, periods: []}`，取值须来自资产说明 |
| `scope` | object | 否 | `{section_ids: [], block_kinds: [], text_origins: [text_layer / ocr / table / caption]}` |
| `include` | string[] | 否 | 随命中附带的内容：`snippet`、`section_title`、`table_header`、`units` |
| `limit` | integer | 否 | 1–20，默认 8 |
| `max_bytes` | integer | 否 | 完整 UTF-8 响应预算，2,000–200,000，默认 24,000；包含出处和上下文依赖 |
| `cursor` | string | 否 | |

模式与参数不匹配（如 mode=text 却提供 `concept`）报 `INVALID_REQUEST`。

新搜索按条数和字节同时分页；有未返回内容时为 partial/truncated 并返回 next_cursor。命中和所请求的依赖不可拆开；单条放不下时返回 ITEM_TOO_LARGE、target、保守 required_bytes 和停在原位置的 cursor，未返回证据不登记。可在同一 cursor 调整 max_bytes；改变查询/范围/include/limit 仍不匹配，索引或版本改变仍过期。建议先以默认 snippet 定位，再用 read_evidence 按表格行列/目标读取所需上下文，不能把摘要当完整口径证据。整段历史模型请求仍有独立上限，工具单页预算不保证整个会话可发送。

未显式传入 max_bytes 的旧搜索请求保持原序列化身份，旧游标仍可继续；已保存响应和引用按原样重放，不事后裁剪。只有新执行的搜索默认采用 24,000 字节。

### Response item（命中）

| 字段 | 说明 |
|---|---|
| `hit_id` | 本次操作内的命中标识 |
| `block` | `{block_id, kind: paragraph / list_item / table / image / heading}` |
| `section_path` | 从根到所属章节的 `[{section_id, title_raw}]` |
| `locator` | 0.6 的 Locator |
| `match` | `{kind: outline / text / concept, spans: [[start, end]], annotation_id?, annotation_role?}` |
| `snippet` | `{text, truncated}`；只在请求时返回 |
| `attached` | 请求的附带内容 `[{role: section_title / table_header / units, block_id, text}]` |
| `text_origin` | `text_layer / ocr / table / caption` |
| `evidence` | 实际返回原文时为第 5 节证据项数组（含 `result_ref`）；仅位置提示时为空。片段与附带上下文各自保留精确 locator、角色和截断状态 |

`coverage`：`{status, blocks_searched, not_searched: [{reason, count, section_ids}]}`；concept 模式另含 `{annotated_blocks, unannotated_blocks}`。命中只是候选，不是答案；附带内容按 `attached` 的角色标出，不伪装成直接命中。片段与附带内容足以判断时，Data Agent 可以不再调用 `read_evidence`（核心设计 7.2.3）。

`hit_id` 只作导航；可交付的是 `evidence[].result_ref`。截断片段只证明实际展示的范围，省略号不映射为原文；多个不连续片段分别登记。必要上下文作为独立证据项返回并写入目标证据的 `dependency_refs`，不把附带内容算成直接命中。

## 5 `read_evidence`：读取原文与上下文

### Request

| 字段 | 类型 | 必填 | 规则 |
|---|---|---|---|
| `asset_ref` | AssetRef | 是 | |
| `targets` | object[] | 是 | 1–16 项，每项为一种：`{block_id, char_range?}`、`{table_id, rows?, cols?}`、`{image_id, region?}`、`{record_id}`、`{locator}` |
| `context` | string[] | 否 | `section_title / table_headers / units / footnotes / neighbors / continuation` |
| `neighbors` | object | 否 | `{before: 0–5, after: 0–5}`，`context` 含 `neighbors` 时使用 |
| `table_representation` | string | 否 | `compact`（按列字段的单元格元组，无损）或 `full` |
| `include_image` | boolean | 否 | 为 true 时返回真实图像或区域，供视觉读取 |
| `max_bytes` | integer | 否 | 2,000–200,000，默认 24,000 |
| `cursor` | string | 否 | 超限分段时继续 |

### Response item（证据项）

| 字段 | 说明 |
|---|---|
| `evidence_id` | 本次运行内唯一（如 `e-0007`，不同于元数据依据的 `ev_` ID）；`search_asset` 与 `read_evidence` 共用宿主登记机制 |
| `result_ref` | 第 0.4 节的 `ResultRef`，kind=evidence；由宿主分配，不由模型填写内容 |
| `asset_ref` | 证据所属的完整资产版本引用 |
| `dependency_refs` | 此证据所需上下文的证据引用；无依赖时为空，引用闭包不得有环 |
| `role` | `target` 或 `context`；context 附 `context_of`（对应目标）与 `context_kind` |
| `kind` | `text / table / image / record` |
| `content` | text：`{text}`；table：`{cell_fields, rows, spans, header_rows}`；image：`{media_type, width, height, image}`（MCP 中以图像内容块传递）；record：见第 6 节 |
| `locator` | 0.6 的 Locator |
| `quality` | `{extraction: text_layer / ocr / html / xbrl, issues: []}`；OCR 或派生描述须标明 |
| `truncated` | 该项是否被分段；分段时以 `next_cursor` 继续 |

`coverage`：`{status, requested_targets, returned_targets, unread: [{target, reason}]}`。未返回的脚注、跨页续表或图片不能标为已读；只有模型描述而没有返回图像时，不算读过原图。需要新做 OCR 或视觉处理时，经第 7 节补处理。

## 6 `query_records`：查询结构化记录

只适用于有效 `readiness.records` 为 `ready` 或 `partial` 的资产，例如带 iXBRL 记录的申报文件或 companyfacts 数据集。原本无记录能力时报 `CAPABILITY_UNSUPPORTED`；有内容但派生视图暂不可用时报 `BUILD_NOT_READY`。

### Request

| 字段 | 类型 | 必填 | 规则 |
|---|---|---|---|
| `asset_ref` | AssetRef | 是 | |
| `select` | object | 是 | `{concepts: [concept_id], fields: []}`，取值来自资产说明的 `fields` 或 `concepts` |
| `filters` | object | 否 | `{periods: [FiscalPeriod 或 {start, end} 或 {instant}], entity_scope: consolidated / segment, dimensions: {}, units: []}` |
| `calculations` | object[] | 否 | `{calc_id, op: difference / ratio / growth / sum, operands: [{record_selector}], output_unit}`，最多 8 项 |
| `order_by` | object | 否 | `{field, direction}` |
| `limit`、`cursor` | | 否 | limit 1–200，默认 50 |

### Response item（记录）

每条记录还必须带 `asset_ref` 与 kind=record 的 `result_ref`；以下为业务字段节选：

```json
{
  "record_id": "rec-000412",
  "concept_id": "us-gaap:Revenues",
  "value": "12000000000",
  "unit": "USD",
  "decimals": -6,
  "period": {"start": "2025-01-01", "end": "2025-12-31", "instant": null},
  "entity_scope": "consolidated",
  "dimensions": {},
  "source": {"accession_number": "0000000000-26-000001", "form": "10-K", "filed": {"value": "2026-02-04", "precision": "date"}},
  "locator": {"type": "record_field", "record_id": "rec-000412", "field": "value", "shard_id": null, "json_pointer": null,
              "source_node": {"type": "html_node", "block_id": "blk-000887", "dom_path": "/html/body/div[412]/table/tr[5]/td[3]", "char_range": null}},
  "issues": []
}
```

响应在共同信封之外增加 `calculations` 和 `supporting_records` 数组。计算结果为 `{calc_id, result_ref, formula, operand_refs, value, unit, limitations}`，其中 kind=calculation，`operand_refs` 是本次操作中实际返回的记录引用；不使用跨 build 含义不明的裸记录 ID。

计算所需的记录即使不在当前结果页，也必须在 `supporting_records` 中带完整记录、资产引用与 locator 返回并展示。`items` 与 `supporting_records` 合计仍受请求 `limit` 与展示预算限制；依赖超限时不返回该计算，给出 `partial` 与 `CALC_DEPENDENCIES_TOO_LARGE` issue，提示缩小计算范围。不能返回数值却隐藏其依赖。零基数、单位或口径不一致时不硬算，返回 `value=null`、`limitations` 与 issue，该结果不能支持“已取得有效计算值”的声明。

`null` 与 `"0"` 严格区分；同一事实在多份材料重复出现时保留各自记录，不重复累计。查询由类型化请求编译为参数化查询，不接受任意 SQL。`deliver` 可直接引用记录和计算的 `result_ref`，无需再调 `read_evidence` 换取另一种 ID。

## 7 `request_asset_update`：补获取或补处理

Data Agent 内部的补数入口（核心设计第 8.2 节），把请求交给资产建设管线；首期同步执行，受上下文剩余预算与墙钟时间限制，超时返回 `partial` 与缺口。

### Request

| 字段 | 类型 | 必填 | 规则 |
|---|---|---|---|
| `need_id` | string | 是 | 对应需求计划中的需求 |
| `action` | string | 是 | `acquire`（获取新原件）或 `process`（对已有原件补处理） |
| `acquire` | object | action=acquire 时 | `{company_id, material_types: [], periods: [], source_hints: [{connector, url?}]}`；只能在上下文主体与扩展策略内 |
| `process` | object | action=process 时 | `{asset_ref, capabilities: [ocr / vision / tables / concepts], targets: []}` |
| `reason` | string | 是 | 针对哪个缺口、为何需要 |

`expansion.mode=disabled` 时，`acquire` 直接返回 `denied`，不发起任何外部请求。

### Response

响应使用共同信封，`items` 只有一项，字段如下。

| 字段 | 说明 |
|---|---|
| `update_id` | 对应建设任务 `job_` 与运行记录 |
| `status` | `completed / partial / denied / failed` |
| `policy_decision` | `{allowed, matched_rules, denied_reason}`；逐个 URL 的策略判断记入运行记录 |
| `new_asset_refs` | 新发布的资产或 build 引用；Data Agent 需重新读取说明后再使用 |
| `gaps` | 未解决的缺口及原因（来源不可达、被策略拒绝、预算不足、处理失败） |
| `resource_usage` | 实际下载数、字节数、外部调用、模型调用与费用 |

下载成功不等于补数完成：新资产经过校验并发布、且 Data Agent 读取后确认适用，才算满足对应需求。

## 8 模型可见的工具与输出

### 8.1 公共参数 `state`

Data Agent 的业务服务接口携带 `state`，包含核心设计第 9.2 节的四项任务状态，以及可选的需求计划更新 `plan_update`。**文档模式的模型端 `deliver` 例外：模型只提交 `request.needs`，SDK 绑定层按其显式判断派生 state，不重复要求模型填写两遍；其他工具仍提交 `{request,state}`。** OpenAI 侧用官方 FunctionTool 接入 Runner，Claude 侧用 SDK 原生进程内 MCP 包装相同业务函数；state 是雨滴业务状态，不替代 SDK 会话。Skills/Memory 的辅助工具沿各自官方协议，不强行塞入本业务 schema，也不能绕过业务工具发布资产或交付证据。新任务的计划版本为 0、无需求；第一次业务调用必须提交非空计划，可以和第一次 `find_assets` 或 `clarify` 在同一次调用中完成：

```json
{
  "plan_update": {
    "base_version": 0,
    "needs": [
      {"need_id": "need-1", "description": "FY2024 与 FY2025 同口径收入及增长率", "required": true},
      {"need_id": "need-2", "description": "管理层对 FY2025 收入变化的解释", "required": true}
    ]
  },
  "satisfied": [],
  "gaps": [
    {"need_id": "need-1", "missing": "尚未取得两年收入及计算", "result_refs": []},
    {"need_id": "need-2", "missing": "尚未取得管理层解释", "result_refs": []}
  ],
  "next_action": "find_assets",
  "reason": "先查找相关期间的年报"
}
```

后续 `satisfied` 的条目为 `{need_id, result_refs}`，引用至少一项已登记结果；`gaps` 的条目为 `{need_id, missing, result_refs}`，可附已取得的部分结果。当前计划的每项需求恰好出现在二者之一；部分满足仍放在 gaps 中。`next_action` 必须等于本次调用工具名。

**文档模式的单字段引用（2026-10-20 更新）：**证据、记录、计算及文档元数据返回完整 `result_ref` 和展示字段 `result_handle`。模型端 schema 的 ResultRef 位置统一为 `{"handle":"rr_…"}`，包括状态、交付及计算操作数；复制已观察条目的 result_handle，不拼 run_id / operation_id / item_id。句柄由完整引用的规范字节确定生成，仅在本 SDK 运行已观察的引用集合内解析；未知、跨会话、未展示及碰撞明确拒绝，不按相似 ID 猜测。服务、持久化与导出继续使用完整 ResultRef，旧完整引用仍严格校验。文档 find_assets 候选、get_asset_schema 实际返回页、search_asset outline 节点提供 kind=metadata 引用，保留 asset_ref、source_object/source_url、locator.projection 和登记/解析限定。元数据引用只支持相应登记、目录或状态声明，不证明原文业务事实；未知期间、主体限定和目录分页边界保持。数值/口径提取仍要求 evidence。句柄不参与进展指纹，导航仍按既有元数据去重。

上述语义已写入两套 SDK 共用的字段 schema/工具说明，不要求模型靠错误逐条猜测。SDK 工具错误附 error.current_task_state：plan 为真实已提交计划，operation_accepted 标明该次操作是否已经受理。预检错误不会提交计划；执行后错误可能已提交，以反馈的版本为准。系统不自动改写模型参数、补需求或注入答案；各模型独立 system prompt 仍分别维护。

**接收顺序：**先校验请求形状与计划 `base_version` → 以候选计划校验所有需求引用与当前运行的结果引用 → 校验本工具参数、范围与预算 → 将计划更新和 state 一起接受并写入记录 → 执行工具。校验失败时不接受任何计划或 state 变化、不执行工具；工具执行失败仍保留已接受计划和错误。状态引用的是本次调用之前已返回的结果，不能预先引用尚未产生的结果。

- `plan_update` 提交完整需求清单；接受后版本加 1，保存旧版与 `reason`。同一上下文内已有 need_id 的 description 与 required 固定，不能删除；程序按字段相等校验，避免依赖对“是否缩小原需求”的语义猜测。可添加细化需求并保留原需求；确需更改问题范围，经第 1 节上下文修订并保留历史。
- 澄清后从前序已登记版本继续，更新时 `base_version` 不是 0；期间等澄清绑定保存在新上下文，需求 ID 不因继续而重置。旧结果未在新运行读取前，相关需求进入 gaps。
- 不更新计划时省略 `plan_update`。`state` 由运行框架消费，不进入工具业务参数或分页游标。未知 need_id 报 `INVALID_REQUEST`，无效结果引用报 `RESULT_REF_INVALID`；不能从一句 `reason` 隐式新建需求。

### 8.2 控制工具

| 工具 | 参数 | 效果 |
|---|---|---|
| `clarify` | `question`、`blocking_need_ids`、`state` | 运行状态变为 `needs_clarification`，返回第 9.1 节的澄清分支；调用方按第 1 节新建继续上下文 |
| `deliver` | `needs: [{need_id, status, result_refs, gaps, limitations, source_claims}]`、`conflicts: [{need_id, result_refs, description}]`、`stop_reason`、`state` | 文档模式不接受自由 `note`，模型不重复传 state；原非文档服务保留 note。程序按第 9 节组装交付包；引用未登记结果时拒绝，预算尚允许时可修正 |

`deliver.needs` 必须逐项覆盖已登记计划，且与 state 一致；supported 必须有结果引用且无该项缺口，partial / unresolved 必须说明缺口。冲突涉及的结果也必须已登记；未解决且影响需求的冲突不能同时声明该需求 supported。结构检查不代替模型的业务充分性判断。模型主动交付时 `stop_reason=delivered`；其余停止原因由宿主设置，模型不能冒填。

文档模式传 `{"request":{"needs":[{"need_id":"…","status":"supported","result_refs":[{"handle":"rr_…"}],"gaps":[]}],"conflicts":[]}}`，不传第二份 state。绑定层只机械复制 needs 的状态和引用：supported 进入 satisfied，partial/unresolved 进入 gaps，并保留交付中的完整缺口列表；不能遗漏计划需求、自动认定满足或修补非法引用。完整分页章节仍须引用每一页的 page_evidence 句柄，由既有依赖闭包组装全部原文与出处。非文档模式、直接业务服务调用的原 `{request,state}` 契约保持。

### 8.3 输出模板与长度预算

2026-10-20 起 `DeliveryNeed.limitations` 默认空列表，承载已披露的来源/结果限定；`gaps` 承载未完成的请求。读全已存正文并披露解析限制，可以完成此种读取/披露任务；若请求证明原解析无遗漏或事实正确，未核验仍是 gap。宿主保持原 supported/partial 校验，不将 gaps 自动移走，不按 limitations 推断业务充分性。旧交付原对象不变。

同日的说明层修复：文档模式 SDK schema 移除 `note`，服务也拒绝新提交的非空 note（`DELIVERY_NOTE_UNSUPPORTED`），不会静默删除。分页范围由宿主生成 `read_coverage`，调用方不填写。必要原文声明放入 `source_claims:[{statement,support:[{result_ref,quote}]}]`，默认空数组；每项至少一条逐字摘录，支持引用须属于该 need 已引用的 evidence 或成员依赖。metadata/record/calculation 冒用报 `SOURCE_CLAIM_INVALID`，摘录不存在报 `QUOTE_NOT_FOUND`；原 SDK 可见性检查继续适用。代码只确认摘录与出处，statement 的语义解释不标为独立核验通过。gaps/limitations 不能用来绕过引用要求写正向事实断言。旧交付文件仍原样可读。

程序保留完整结构化响应；写回对话的是按确定性模板生成的文本，不调用模型。每段输出都以状态行开头、以继续入口结尾。

| 工具 | 默认展示上限 |
|---|---|
| `find_assets` | 10 个候选，每个不超过 400 字符 |
| `get_asset_schema` | 概览加不超过 40 个目录节点或字段 |
| `search_asset` | 最多 8 个命中，每个片段不超过 300 字符；完整响应默认 24,000 字节，含所请求的依赖 |
| `read_evidence` | 遵循请求的 `max_bytes`，默认 24,000 字节 |
| `query_records` | 共 50 条记录（含计算依赖）；只展示依赖已完整展示的计算 |

`find_assets` 输出示例：

```text
[find_assets] status=ok · 本页 2 项 · 还有更多（cursor=c1）· 目录版本 cat-0042
1. Example Corp 10-K FY2025 · HTML · ref=as_01J9DEMO/sn_01J9DEMO/rp_01J9DEMO/bd_01J9DEMO
   发布 2026-02-04T16:05:12-05:00 · 内容期间 FY2023–FY2025 · 匹配：全部条件
   可用：目录 ✓ 全文 ✓ 记录 ✓ 概念 部分 · 另有 1 个处理版本 · 被 as_01J9DEMP 修订
2. Example Corp 业绩材料 FY2025Q4 · PDF · ref=…
   发布 未知 · 期间匹配 未解决（reporting_period 未知）
issues: 无
下一步：get_asset_schema(asset_ref) 查看目录与读取方式；或带 cursor 翻页
```

截断、分页和执行不完整分别写明；未展示的候选不能当作已读，首屏不能冒充全部结果。

凡可用于交付的展示条目都附 `result_ref`，上下文与计算依赖一并展示并登记；保存在完整响应但未展示的条目不能引用。更大的显式请求在展示预算不足时必须返回可继续读取的范围/游标，不能用下一页游标跳过本页被隐藏的条目。

## 9 `run_query` 与交付包

### 9.1 `run_query`

**检查点 11 的时间核对补充：**恢复宿主与被恢复的原生进程分别保存时钟。`inspect_context.recovery_attempts` 展示当前执行段的恢复尝试、owner、已计耗时以及 completed/reconciled/active 状态；active 仅表示尚无持久完成确认，不证明进程存活。恢复尝试再次中断时，宿主 `ObservedWorker.record` 绑定该尝试自己的退出观察，原进程观察不可替代。已确认恢复耗时加到累计 `wall_seconds`，原进程上界只与属于原进程的部分比较；人工等待不加入。原生续跑将这些记录归档到原段，并把累计时间带入新段。恢复宿主的监督超时停止同一根账本，不能因恢复而得到新预算。新结果快照的 `runtime.wall_seconds` 是准备结果时的累计执行时间，`host_recovery_seconds` 是当前执行段内已计的恢复时间；冻结结果不随后续核对改写。已有终态或提交意图仍可通过显式恢复核对后来取得的原进程退出观察，仅更新当前审计状态。没有可验证观察或旧格式缺少记录时不补造耗时依据。

**检查点 13 的入口与结果提交计时：**有效离线 SDK 调用从公开入口捕获起点，预检与装配耗时计入本次执行；配置文件装载发生在调用方，非法配置仍在启动 SDK 前拒绝。SDK 装配失败也保存明确运行结果。新结果的 `runtime.timing_scope="through_result_preparation"` 表示准备该不可变结果时的历史用量快照，不包含此后提交与核对的全部耗时；当前累计时间从 `inspect_context.wall_seconds` 查看。

`inspect_context.completion_clock` 与业务结果的提交状态分开：`pending` 表示结果收尾计时尚未确认，`recorded` 表示已在业务结果提交后采样并保存，`observed` 表示中断后由所属原宿主的真实退出观察核对。收据自身写入后的尾部不由一次采样证明，实际退出观察可补充核对。计时确认中断时，`read_run_result` 仍能读回已提交的原结果；运行入口须显式恢复，澄清后继不能跳过未确认时间。没有原退出观察的恢复保留不确定性，不重开 SDK、不改写旧结果；在结果意图保存前退出也不能恢复出从未持久化的原错误。旧格式不补造新字段或计时证据。当前 Python 宿主准入、取消及已装配辅助请求的离线证据见核心设计 14.12.16 检查点 16；新增配套和真实网关须重新核对对应调用入口。

`await DataService.run_query(context_ref, recover=False) -> RunQueryResult`：在给定上下文中运行已显式配置的 Data Agent，直至交付、需要澄清、取消或达到停止条件。当前 Python 离线绑定见 0.0.1；MCP 尚未接入，其目标响应仍与 Python 使用相同的带 `kind` 联合返回类型：

内部由所选 SDK 执行完整循环。两套离线运行已使用各自原生停止机制，错误工具结果不能触发成功交付；SDK 的自由文本不能直接变为 DeliveryPackage。保存内核/版本/原生 session 与业务 run/root/context ID 的显式映射，恢复不绕过范围、引用与账本检查；跨内核不承诺无损恢复。`contracts/run.py` 的 `RunQueryResult` 已用于当前 Python `DataService.run_query` 离线接入，七项收尾审计见核心设计 14.12.16。正式 MCP、真实网关及业务效果尚未验收，不据该类型或离线通过宣称整条真实运行路径完成。

| kind | 字段 | 含义 |
|---|---|---|
| `delivery` | `delivery: DeliveryPackage` | 正常交付或宿主因停止条件强制组装的部分交付 |
| `needs_clarification` | `clarification: ClarificationRequest` | 返回问题并结束当前执行，不伪装成完成交付 |
| `failed` | `error`、`runtime` | 本上下文明确失败并结束；未知费用/响应仍须核对，不因此变成零 |
| `recovery_required` | `error`、`runtime` | 本上下文尚未确认终态；只能按原意图恢复或显式关闭 |

当前离线信封保留 `delivery`/`clarification` 的已提交工具响应及不可变对象引用，内部业务包仍按下文约定。新结果带 `schema_version=uteki-run-query-result-v1`、`terminal` 和 `reconciliation_required`；兼容已有 `status`：delivery 为 completed/partial/cancelled，澄清为 needs_clarification，失败及恢复要求为 failed，调用者须以 kind/terminal 判断是否结束。`native_success` 单独报告 SDK 是否正常结束：SDK 正常结束却未交付仍是业务失败；已接受业务包而 SDK 收尾失败，业务包保留且 `native_error` 说明原生失败。结果中的耗时与账本是冻结时快照，后续费用核对不能改写原结果。

终态先保存不可变结果和 `outcome_intent`，再确认 Session、Catalog 和结果头；显式恢复确认同一对象，不重跑模型。`read_run_result(context_ref)` 只读已有结果并校验终态一致性；未完成提交返回 RECOVERY_REQUIRED。`inspect_context.lifecycle` 同时给出 Catalog 状态、原生阶段及待提交/关闭标记；Catalog running 是业务未终结，不是进程存活证据。旧格式结果原样读回，不补造新字段。

宿主 `close_run(context_ref, request_key=..., reason=...)` 用于原生历史不完整或未知响应的显式放弃。要求实际观察原进程组退出、无待确认交付/澄清，副作用及已有响应意图先经原恢复入口确认/关闭。无响应意图的只读 accepted 操作可标记 closed 并保留原记录，不生成假的成功/错误工具响应。关闭停止原根账本，仅释放尚未 dispatch 的 prepared 请求，保留 dispatched/outcome_unknown 的预留；返回 kind=failed、error=RUN_CLOSED。关闭键/原因固定，关闭中断沿原意图继续；普通 SDK recover 不能取消关闭，也不能创建第二个运行掩盖它。该宿主操作不是新增模型工具或对外 MCP 能力。

`ClarificationRequest` 包含 `{clarification_id, context_ref, run_id, root_run_id, question, blocking_need_ids, needs_plan, state, usage, remaining_budget, created_at}`。`clarification_id` 使用 `cl_` 系统 ID；usage 为根任务累计用量，remaining_budget 为扣除已结算、预留及未知费用后的余额。宿主冻结该记录；调用方得到问题后，按第 1 节提交回答和原上下文引用，再调用 `run_query(new_context_ref)`。不另增模型工具或自动后台等待。

`context_ref` 与查询运行一一对应：重复调用正在执行的上下文时，同步等待同一执行并返回同一结果；已结束的返回已保存的 `RunQueryResult`，不重复发起模型调用。澄清后通过新上下文创建新的运行。

取消、预算、轮数或时间耗尽时返回 kind=delivery，停止原因由宿主填写。强制交付不额外调用模型：复制最近一次已校验状态及引用；尚未经过下一轮判断的新工具结果不自动算作 supported，未确认部分列为缺口。若首轮计划尚未登记，宿主只以原始问题创建一项 unresolved 需求，标明“停止前尚未完成需求拆解”，不生成事实或满足声明。

### 9.2 `DeliveryPackage`

| 字段 | 说明 |
|---|---|
| `delivery_id` | `dl_` 标识 |
| `context_ref`、`run_id`、`root_run_id` | 对应的上下文、本次运行与累计预算所属根运行 |
| `prior_delivery_refs` | 补数时引用的原交付包 |
| `needs_plan` | `{version, needs: [{need_id, description, required}]}`，含修订历史引用 |
| `needs` | `[{need_id, status, result_refs, gaps, limitations, source_claims, note}]`；新文档交付 note 为 null，旧/非文档 note 继续可读。source_claims 含逐字摘录、精确出处、quote_presence_checked 与 semantic_verification=not_performed；解释与 limitations 不冒充独立业务核验 |
| `evidence` | 被引用的证据项（第 5 节结构），每项含 `asset_ref` 与 `locator` |
| `metadata` | 被引用的实际登记/解析快照，与正文分开；旧交付无此字段时按空列表展示 |
| `records`、`calculations` | 被引用的记录与计算（第 6 节结构） |
| `assets_used` | 实际使用的 `asset_ref` 列表，均已冻结 |
| `conflicts` | `[{need_id, result_refs, description}]`；未解决的冲突并列呈现 |
| `gaps` | 未满足的缺口与原因 |
| `limitations` | 已披露的来源/结果限定，保留 need_id 和模型说明来源；不自动改变任务状态 |
| `completion_basis` | requested_work_not_source_quality_certification：完成请求工作不等于原件或解析质量认证 |
| `read_coverage` | 从交付中 section_page 生成；按材料/解析/父路径/include_descendants 分组，含零起始半开 ranges、pages、missing_ranges、去重 delivered_blocks、total_blocks 和 stored_section_complete。重复读取不增加块数；不一致报 COVERAGE_INCONSISTENT。原 PDF 的 source_completeness 仍 not_verified |
| `search_log_ref` | 本次运行的工具调用记录位置 |
| `usage` | `{model_calls, cost_usd, unknown_cost_reserved_usd, wall_seconds}`；均为根任务累计值，单次明细见运行记录；wall_seconds 为执行时间，不含等待澄清回答 |
| `stop_reason` | `delivered / budget_exhausted / max_turns / no_progress / wall_time / cancelled` |
| `created_at` | 系统时间 |

**闭包规则：**以 `needs` 与 `conflicts` 的 `result_refs` 为起点，递归纳入证据的 `dependency_refs` 与计算的 `operand_refs`；每个条目按 kind 放入 `evidence`、`records`、`calculations` 或 `metadata`，保留原 `result_ref`。所有引用必须来自本运行实际展示的工具结果，不得悬空、循环或引用旧运行；每个原始证据/记录/元数据的 `asset_ref` 都须出现在 `assets_used`。原文、数值、公式、元数据快照和依赖由程序从登记结果复制，模型不提交替代值。交付包写入后不可修改，新的补充生成新的交付包。

**文件导出：**同一交付对象生成 `delivery.json` 与 `delivery.md`；存在 records 时生成 `records.csv`，存在 calculations 时另生成 `calculations.csv`。计算 CSV 保留精确结果、公式、单位、操作数/结果引用、比较依据、期间策略和限定；缺失结果保持空值并保留原因。`manifest.json` 记录文件 hash 并作为导出完成标志。导出不调用模型，不覆盖已有目录，也不改写旧文件。

## 10 内部组件接口

以下为 Python 接口草案（`typing.Protocol`），供实现与测试对齐；签名中的类型均来自 `contracts/`。

```python
class CatalogRepository(Protocol):
    def resolve_entities(self, names: list[str], securities: list[SecurityQuery], at: datetime) -> EntityResolution: ...
    def search_assets(self, ctx: RequestContext, req: FindAssetsRequest) -> FindAssetsResponse: ...
    def get_build(self, ref: AssetRef) -> BuildRecord: ...
    def begin_build(self, spec: BuildSpec, job_id: str, retry_of_build_id: str | None = None) -> BuildRecord: ...
    # BuildSpec 含资产/快照/表现形式、完整输入清单 hash 与处理配方；仓储计算 build_key，按有效行部分唯一约束复用或登记
    def publish_build(self, build_id: str, manifest_sha256: str, readiness: Readiness) -> None: ...  # 单事务
    def fail_build(self, build_id: str, failure_code: str) -> None: ...
    def freeze_snapshot(self, snapshot_id: str, manifest_sha256: str) -> None: ...
    def record_revision(self, revision: MetadataRevision, evidence: list[MetadataEvidence]) -> str: ...

class ContentStore(Protocol):
    def put_object(self, data: bytes) -> ObjectRef: ...                 # 写一次，按 sha256 去重
    def open_staging(self, job_id: str) -> StagingArea: ...
    def promote(self, staging: StagingArea, ref: AssetRef) -> Manifest: ...  # 校验后整体移动
    def read_artifact(self, ref: AssetRef, artifact: str) -> bytes: ...

class SourceConnector(Protocol):
    name: str
    def discover(self, target: DiscoveryTarget, policy: SourcePolicy) -> list[SourceCandidate]: ...
    def fetch(self, candidate: SourceCandidate, policy: SourcePolicy, budget: Budget) -> FetchResult: ...  # 每个 URL 先过策略

class BuildStage(Protocol):
    name: str
    version: str
    def run(self, inputs: StageInputs, ctx: BuildContext) -> StageResult: ...

class ContentIndex(Protocol):
    backend: str
    version: str
    def build(self, ref: AssetRef, blocks: Iterable[Block], annotations: Iterable[Annotation]) -> DerivedIndexRecord: ...
    def outline(self, ref: AssetRef, req: OutlineQuery) -> SearchPage: ...
    def text(self, ref: AssetRef, req: TextQuery) -> SearchPage: ...
    def concept(self, ref: AssetRef, req: ConceptQuery) -> SearchPage: ...   # 不支持时抛 CapabilityUnsupported

```

**Agent 集成边界：**不再定义独立 ModelClient、工具分发或会话协议。OpenAI 使用官方 Agent/Runner、FunctionTool、Session 等扩展点；Claude 使用其原生运行时、MCP 工具、会话及 hooks。共享 Catalog/Content/Build/Index 和业务 schema 不依赖 SDK 类型；网关统一并不要求内部事件与会话协议相同。费用保存 SDK 原始统计，并以可核对的 OpenRouter 记录对账及根任务累计，未知费用保留；既有 MeteredModel 不代表覆盖 Claude 内部调用或流式。网关路由、原生配套与验证条件见核心设计 14.17。

- `ContentIndex` 的所有实现（FTS5 基线、PageIndex、OpenAI 文件检索）返回同一种 `SearchPage`，命中必须映射到 build 内的块 ID 与 locator；映射失败的命中进入 issues。
- `SourceConnector.fetch` 对重定向目标与附件逐个重新检查策略；被拒绝时返回 `denied_by_policy`，不抛出静默异常。
- `BuildStage` 不直接写 SQLite；状态变更由管线编排器经 `CatalogRepository` 完成，保证发布协议只有一个入口。
- `begin_build` 必须校验版本归属、完整输入清单与 build_key；不同快照即使主对象字节相同也分别登记。已有 staging 返回同一任务，published 返回同一 build，failed 仅在显式重试授权内新建并保留旧记录；具体约束见核心设计 14.4。
- `publish_build` 在最终说明/manifest 复验后调用，readiness 必须等于冻结说明的 published_readiness。查询端将 content_readiness 与派生层当前状态合成有效能力，不回写冻结文件；见核心设计 14.5。

## 11 MCP v2 映射

| MCP 工具 | 对应接口 | 只读 | 说明 |
|---|---|---|---|
| `create_context` | 第 1 节 | 否（只写上下文记录） | 外部宿主建立上下文后才能调用其他工具 |
| `find_assets` | 第 2 节 | 是 | |
| `get_asset_schema` | 第 3 节 | 是 | |
| `search_asset` | 第 4 节 | 是 | |
| `read_evidence` | 第 5 节 | 是 | 图像以 MCP 图像内容块返回 |
| `query_records` | 第 6 节 | 是 | |
| `run_query` | 第 9 节 | 否 | 由 Data Agent 完成查询并交付；产生模型费用，受上下文预算约束 |

- 业务结果放在 MCP `structuredContent`，同时附第 8 节模板文本。
- `request_asset_update` 首期不对外部宿主开放；外部宿主需要补数时使用 `run_query`，由 Data Agent 在策略内处理。
- MCP v1（`discover_data / get_data_schema / query_facts / read_source`）冻结，不并行扩展；迁移完成后另定下线时间。外部宿主直接调用读取工具得到的结果，不是 Data Agent 交付。
