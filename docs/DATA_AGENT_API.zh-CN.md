# Data Agent 接口契约

日期：2026-10-14 · 版本：v0.5 · 状态：用户已确认实施路线，最新指定模型 API 统一经 OpenRouter，对比 OpenAI Agents SDK 与 Claude Agent SDK 及配套能力两套实现；共享业务工具契约延续 v0.4。剩余缺口见核心设计 14.16，SDK/网关边界与交叉比较见 14.17，第四批 review 收尾项已关闭，SDK/MCP 尚未联调，当前确定性实现范围见 0.0。

本文件定义 Data 能力的全部对外与内部接口：请求上下文、6 个数据工具、模型可见输出、交付包、内部组件接口及 MCP 映射。职责与流程见[核心设计](DATA_AGENT_FRAMEWORK_DESIGN.zh-CN.md)第 7 节，技术方案见第 14 节；本文件只维护接口细节。

**相对 v0.2 的变化：**按已确认的 A5（单进程库，不建 HTTP 服务），删除 HTTP 路由与状态码映射，改为 Python 进程内调用与 MCP 两种传输；`find_assets` 保留 v0.2 的字段与边界规则，增加证券代码解析与版本呈现规则；补齐其余 5 个工具、`create_context` 与交付包。

**相对 v0.3 的变化：**补齐需求计划登记、统一结果引用、build 身份与完整输入、发布能力与实时能力、澄清返回与继续上下文五项契约；对应核心设计第 14.15 节的两条文档走查。此次仅修订设计，不表示通过实跑验收。

**相对 v0.4 的变化：**通用执行由各自官方 SDK 承接，删除自定义 ModelClient 草案；Agent/Runner、FunctionTool、Session、RunState 是 OpenAI 侧映射，Claude 侧使用其原生循环、工具与会话。应用保留资产、来源/预算、需求状态、实际展示引用与交付校验；Skills/Memory 使用官方适用机制，不另造 Agent 协议。首期数据来源为官方来源；最新检查失败允许带日期与“未确认最新”标记返回符合硬边界的旧材料，并保留缺口（核心设计第 10 节）。两套实现共享此业务 API，内核选择留在应用装配配置，本次不向公开工具参数注入 SDK 类型或新字段。

所有示例中的公司、期间、ID、URL 与数值均为虚构，不是公司事实或实跑结果。

## 0 通用约定

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

**索引与预算：**派生索引 manifest 为 `uteki-derived-html-v2`，trigram 以 casefold 文本检索并保留原文；旧代不修改，需显式重建后才能使用新代。计算按精度 50、ROUND_HALF_EVEN、除法 18 位小数执行，零基数/歧义/不可比返回 null 和原因。`read_evidence/query_records.max_bytes` 为 2,000–200,000；工具最终信封也受限制，其他工具上限 200,000 字节。计算的原始记录、原文的上下文均计入实际输出；输出不足则保留缺口，未展示结果不登记。

**同步时限与失败：**单次调用从进入 DataService.call 开始计时，扣除该运行已累计时间，覆盖必要预检与执行；未接受计划的超时预检仍计时。获取逐请求 timeout 不超过剩余时间；DuckDB 可中断、SQLite 有进度检查；处理/索引激活/发布移动与提交前检查取消及 deadline。已经开始的不可抢占系统调用可能稍后才返回，返回后不得启动下一业务步骤；失败记录与持久化收尾仍须完成，不以强杀破坏存储。停止后的已提交/不确定结果通过 error.details.effects（致命恢复异常为异常的 details）报告，包含 receipt、generation、snapshot/build 状态及恢复要求；错误不是“没有副作用”的保证。模型强制部分交付仍由后续 runtime 实现。

**上下文创建恢复：**使用原请求和 request_key，显式设置 recover=True；未完成创建返回 RECOVERY_REQUIRED，已完成状态损坏拒绝重置为初始状态。创建意图通过现有 Catalog registrations 和 ContentStore 固定，控制文件再写入；恢复校验原 request/policy/run/context，重确认必要目录同步。此入口只完成上下文创建，不重执行已接受的工具或模型，也不扩展成澄清继续。旧格式上下文与交付可读，无需迁移。

**补数与重放：**获取发布返回现有 build 的 job_；仅重建派生索引及拒绝动作返回 op_，与对应 operation_id 关联，并另列 generation。成功构建索引不代表原始记录全部可解析。acquire 的宿主计划指纹参与幂等键校验；重复原请求读取已保存响应，变更计划不能沿用同一键。接受后中断且无已保存响应时返回 OPERATION_INTERRUPTED，允许检查原件、候选与索引 head，但不自动重复有副作用的动作。交付响应已落盘但目录 run 未收尾时，精确重放补齐目录终态，交付字节不变。

**交付说明：**参数只接受登记引用和标明来源的调用者说明，不接受调用者补填原文或数值。`context_evidence` 与计算操作数递归纳入交付；引用、闭包和格式有效不证明自然语言需求已被充分满足。本批的程序化案例不能当作 Agent 自主选材或业务充分性通过。

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

**可交付引用 `ResultRef`：**`{run_id, operation_id, kind: evidence / record / calculation, item_id}`。它定位一次工具调用实际交给模型的结果，不代替 `AssetRef` 或原文地址。`item_id` 分别取 `evidence_id`、`record_id`、`calc_id`；操作 ID 消除不同查询中的同名计算歧义，资产引用仍保存在被引用条目中。

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
| `as_of` | datetime 或 null | 否 | 只能收紧上下文的 `as_of`；晚于上下文报 `SCOPE_DENIED` |
| `limit` | integer | 否 | 1–50，默认 10；越界报错，不截成合法值 |
| `cursor` | string 或 null | 否 | 见 0.8 |

| 过滤字段 | 类型 | 含义 |
|---|---|---|
| `company_ids` | string[] | 公司 ID；必须在上下文主体范围内 |
| `company_names` | string[] | 正式名称或别名，在已登记目录中解析为 ID |
| `securities` | object[] | `{ticker, exchange_mic?}`，经证券映射解析到公司；结果保留输入证券 |
| `roles` | string[] | 公司与资产的关联角色 `issuer / subject / mentioned`；省略时为 `issuer` 与 `subject` |
| `asset_kinds` | string[] | `document / dataset` |
| `material_types` | string[] | 已注册材料类型；未知值报错 |
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
| `cursor` | string | 否 | |

模式与参数不匹配（如 mode=text 却提供 `concept`）报 `INVALID_REQUEST`。

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

Data Agent 每次本接口定义的业务工具调用都携带 `state`，包含核心设计第 9.2 节的四项任务状态，以及可选的需求计划更新 `plan_update`。OpenAI 侧用官方 FunctionTool 接入 Runner，Claude 侧用 SDK 原生进程内 MCP 包装相同业务函数；state 是雨滴业务状态，不替代 SDK 会话。Skills/Memory 的辅助工具沿各自官方协议，不强行塞入本业务 schema，也不能绕过业务工具发布资产或交付证据。新任务的计划版本为 0、无需求；第一次业务调用必须提交非空计划，可以和第一次 `find_assets` 或 `clarify` 在同一次调用中完成：

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

**接收顺序：**先校验请求形状与计划 `base_version` → 以候选计划校验所有需求引用与当前运行的结果引用 → 校验本工具参数、范围与预算 → 将计划更新和 state 一起接受并写入记录 → 执行工具。校验失败时不接受任何计划或 state 变化、不执行工具；工具执行失败仍保留已接受计划和错误。状态引用的是本次调用之前已返回的结果，不能预先引用尚未产生的结果。

- `plan_update` 提交完整需求清单；接受后版本加 1，保存旧版与 `reason`。同一上下文内已有 need_id 的 description 与 required 固定，不能删除；程序按字段相等校验，避免依赖对“是否缩小原需求”的语义猜测。可添加细化需求并保留原需求；确需更改问题范围，经第 1 节上下文修订并保留历史。
- 澄清后从前序已登记版本继续，更新时 `base_version` 不是 0；期间等澄清绑定保存在新上下文，需求 ID 不因继续而重置。旧结果未在新运行读取前，相关需求进入 gaps。
- 不更新计划时省略 `plan_update`。`state` 由运行框架消费，不进入工具业务参数或分页游标。未知 need_id 报 `INVALID_REQUEST`，无效结果引用报 `RESULT_REF_INVALID`；不能从一句 `reason` 隐式新建需求。

### 8.2 控制工具

| 工具 | 参数 | 效果 |
|---|---|---|
| `clarify` | `question`、`blocking_need_ids`、`state` | 运行状态变为 `needs_clarification`，返回第 9.1 节的澄清分支；调用方按第 1 节新建继续上下文 |
| `deliver` | `needs: [{need_id, status, result_refs, gaps, note}]`、`conflicts: [{need_id, result_refs, description}]`、`stop_reason`、`state` | 程序按第 9 节组装交付包；引用未登记结果时拒绝，预算尚允许时可修正 |

`deliver.needs` 必须逐项覆盖已登记计划，且与 state 一致；supported 必须有结果引用且无该项缺口，partial / unresolved 必须说明缺口。冲突涉及的结果也必须已登记；未解决且影响需求的冲突不能同时声明该需求 supported。结构检查不代替模型的业务充分性判断。模型主动交付时 `stop_reason=delivered`；其余停止原因由宿主设置，模型不能冒填。

### 8.3 输出模板与长度预算

程序保留完整结构化响应；写回对话的是按确定性模板生成的文本，不调用模型。每段输出都以状态行开头、以继续入口结尾。

| 工具 | 默认展示上限 |
|---|---|
| `find_assets` | 10 个候选，每个不超过 400 字符 |
| `get_asset_schema` | 概览加不超过 40 个目录节点或字段 |
| `search_asset` | 8 个命中，每个片段不超过 300 字符 |
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

`DataService.run_query(context_ref) -> RunQueryResult`：在给定上下文中运行 Data Agent，直至交付、需要澄清、取消或达到停止条件。Python 与 MCP 使用相同的带 `kind` 联合返回类型：

内部由所选 SDK 执行完整循环。OpenAI 侧拟用 `tool_use_behavior` 处理已校验的 deliver/clarify；Claude 侧须验证原生结束事件及结构化结果到同一业务终态的映射，不要求复制该 OpenAI 扩展点。错误工具结果不能触发成功终止；SDK 的自由文本不能直接变为 DeliveryPackage。保存内核/版本/原生 session 与业务 run/root/context ID 的显式映射，恢复不绕过范围、引用与账本检查；跨内核不承诺无损恢复。致命错误分支仍是核心设计 T6 待完成的契约，不能据 SDK 返回对象宣称已经闭合。

| kind | 字段 | 含义 |
|---|---|---|
| `delivery` | `delivery: DeliveryPackage` | 正常交付或宿主因停止条件强制组装的部分交付 |
| `needs_clarification` | `clarification: ClarificationRequest` | 返回问题并结束当前执行，不伪装成完成交付 |

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
| `needs` | `[{need_id, status, result_refs, gaps, note}]`；`note` 标为模型说明；宿主强制停止的说明标为程序生成 |
| `evidence` | 被引用的证据项（第 5 节结构），每项含 `asset_ref` 与 `locator` |
| `records`、`calculations` | 被引用的记录与计算（第 6 节结构） |
| `assets_used` | 实际使用的 `asset_ref` 列表，均已冻结 |
| `conflicts` | `[{need_id, result_refs, description}]`；未解决的冲突并列呈现 |
| `gaps` | 未满足的缺口与原因 |
| `search_log_ref` | 本次运行的工具调用记录位置 |
| `usage` | `{model_calls, cost_usd, unknown_cost_reserved_usd, wall_seconds}`；均为根任务累计值，单次明细见运行记录；wall_seconds 为执行时间，不含等待澄清回答 |
| `stop_reason` | `delivered / budget_exhausted / max_turns / no_progress / wall_time / cancelled` |
| `created_at` | 系统时间 |

**闭包规则：**以 `needs` 与 `conflicts` 的 `result_refs` 为起点，递归纳入证据的 `dependency_refs` 与计算的 `operand_refs`；每个条目按 kind 放入 `evidence`、`records` 或 `calculations`，保留原 `result_ref`。所有引用必须来自本运行实际展示的工具结果，不得悬空、循环或引用旧运行；每个原始证据/记录的 `asset_ref` 都须出现在 `assets_used`。原文、数值、公式和依赖由程序从登记结果复制，模型不提交替代数值。交付包写入后不可修改，新的补充生成新的交付包。

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
