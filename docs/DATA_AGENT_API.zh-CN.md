# Data Agent 接口契约

日期：2026-10-14 · 版本：v0.3 · 状态：设计稿，待 review，尚未实现或联调。

本文件定义 Data 能力的全部对外与内部接口：请求上下文、6 个数据工具、模型可见输出、交付包、内部组件接口及 MCP 映射。职责与流程见[核心设计](DATA_AGENT_FRAMEWORK_DESIGN.zh-CN.md)第 7 节，技术方案见第 14 节；本文件只维护接口细节。

**相对 v0.2 的变化：**按已确认的 A5（单进程库，不建 HTTP 服务），删除 HTTP 路由与状态码映射，改为 Python 进程内调用与 MCP 两种传输；`find_assets` 保留 v0.2 的字段与边界规则，增加证券代码解析与版本呈现规则；补齐其余 5 个工具、`create_context` 与交付包。

所有示例中的公司、期间、ID、URL 与数值均为虚构，不是公司事实或实跑结果。

## 0 通用约定

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

除 `create_context` 与 `run_query` 外，每个工具的响应都使用：

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

- 游标是不透明字符串，绑定：上下文、工具名、全部请求参数（游标本身除外）、目录或 build 版本、`limit`。翻页时只替换 `cursor`，其余参数必须原样不变，否则报 `CURSOR_MISMATCH`。
- 目录或版本已无法重现旧视图时报 `CURSOR_EXPIRED`，不改用最新内容。
- 同分结果按完整引用固定排序，保证翻页不重不漏。

### 0.9 错误码

| code | 含义 |
|---|---|
| `INVALID_REQUEST` | 参数缺失、类型错误、取值越界、未知字段、时间格式错误 |
| `CONTEXT_NOT_FOUND` | `context_ref` 不存在或调用方无权使用 |
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

上下文一经建立不可修改；需要改变范围时新建上下文，并用 `revises_context_ref` 关联。

### Request

| 字段 | 类型 | 必填 | 规则 |
|---|---|---|---|
| `question` | string | 是 | 原始问题，原样保存 |
| `caller` | object | 是 | `{kind: user / analysis_agent, prior_delivery_refs: []}`；补数时引用原交付包 |
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
| `clock` | 建立上下文的时刻（带时区），相对时间以此为准 |
| `resolved_entities` | 每项含输入值、`company_id`、规范名称及匹配的证券（`security_id`、ticker、MIC、share_class、有效期） |
| `unresolved` | 未能解析的输入及原因；存在歧义时直接报 `ENTITY_AMBIGUOUS`，不建立上下文 |
| `effective_policy` | 实际生效的来源、扩展和运行策略 |

证券代码按 `clock` 或 `as_of` 时点解析；一个公司有多个证券时全部列出，并保留用户原始输入的证券，供后续股价、每股指标类问题使用。

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
  "state": {"...": "第 8.1 节公共参数"}
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

返回选中资产指定版本的说明，对应核心设计第 7.2.2 节的九类信息；正文由后续工具读取。说明来自该 build 发布时生成的 `asset-schema.json`，查询时不重新生成。

### Request

| 字段 | 类型 | 必填 | 规则 |
|---|---|---|---|
| `asset_ref` | AssetRef | 是 | 完整引用 |
| `facets` | string[] | 否 | `overview / outline / fields / concepts / coverage / readiness / capabilities`；省略时返回 `overview`、`readiness`、`capabilities` 与一级 `outline` 或 `fields` 摘要 |
| `outline` | object | 否 | `{parent_section_id: null 或 ID, depth: 1–3}`，用于展开目录 |
| `field_group` | string | 否 | dataset 的字段组展开 |
| `limit`、`cursor` | | 否 | 目录节点或字段的分页 |

### Response item

| 字段组 | 内容 |
|---|---|
| `overview` | 标题、语言、`asset_ref`、来源（发布方、平台、原始链接）、类型（资产类别 / 材料类型 / 表现形式）、关联公司及角色、时间（报告期间、内容期间、发布、获取、可得及依据）、派生内容概述（标注生成方式与版本） |
| `readiness` | 0.7 中各能力的状态，及未完成位置 |
| `capabilities` | 可用的工具与模式，如 `search_asset.outline`、`search_asset.text`、`search_asset.concept`、`read_evidence`、`query_records` |
| `outline`（document） | 节点 `{section_id, title_raw, canonical_section, mapping_status: explicit / inferred / unmatched, origin: source / inferred, child_count, block_count, page_range}`；含显式的“未归属块”节点 |
| `fields`（dataset） | `{name, type, concept_id, unit, period_semantics: instant / duration, nullable_meaning, dimensions}`、允许的过滤与计算、分片与版本一致性状态 |
| `concepts` | 已标注概念、角色、目标数；附概念标注的覆盖范围 |
| `coverage` | 已处理与未处理范围：未读图片、失败表格、OCR 未处理页、未分类块等 |

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

`concepts` 只统计已建立的标注；未命中不表示材料未披露。没有 `query_records` 能力意味着表格未经结构化，不能当作标准化指标表查询。

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

`coverage`：`{status, blocks_searched, not_searched: [{reason, count, section_ids}]}`；concept 模式另含 `{annotated_blocks, unannotated_blocks}`。命中只是候选，不是答案；附带内容按 `attached` 的角色标出，不伪装成直接命中。片段与附带内容足以判断时，Data Agent 可以不再调用 `read_evidence`（核心设计 7.2.3）。

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
| `evidence_id` | 本次运行内唯一（如 `e-0007`，不同于元数据依据的 `ev_` ID）；交付时只能引用这里返回过的 ID |
| `role` | `target` 或 `context`；context 附 `context_of`（对应目标）与 `context_kind` |
| `kind` | `text / table / image / record` |
| `content` | text：`{text}`；table：`{cell_fields, rows, spans, header_rows}`；image：`{media_type, width, height, image}`（MCP 中以图像内容块传递）；record：见第 6 节 |
| `locator` | 0.6 的 Locator |
| `quality` | `{extraction: text_layer / ocr / html / xbrl, issues: []}`；OCR 或派生描述须标明 |
| `truncated` | 该项是否被分段；分段时以 `next_cursor` 继续 |

`coverage`：`{status, requested_targets, returned_targets, unread: [{target, reason}]}`。未返回的脚注、跨页续表或图片不能标为已读；只有模型描述而没有返回图像时，不算读过原图。需要新做 OCR 或视觉处理时，经第 7 节补处理。

## 6 `query_records`：查询结构化记录

只适用于 `readiness.records` 为 `ready` 或 `partial` 的资产，例如带 iXBRL 记录的申报文件或 companyfacts 数据集；其他资产报 `CAPABILITY_UNSUPPORTED`。

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

计算结果单列：`{calc_id, formula, operand_record_ids, value, unit, limitations}`。零基数、单位或口径不一致时不硬算，返回 `limitations` 与 issue。`null` 与 `"0"` 严格区分；同一事实在多份材料重复出现时保留各自记录，不重复累计。查询由类型化请求编译为参数化查询，不接受任意 SQL。

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

Data Agent 每次工具调用都携带 `state`，对应核心设计第 9.2 节的四项任务状态：

```json
{
  "satisfied": [{"need_id": "need-1", "evidence_ids": ["e-0007"]}],
  "gaps": [{"need_id": "need-2", "missing": "管理层对 FY2025 收入变化的解释"}],
  "next_action": "search_asset",
  "reason": "需求 2 尚无证据；同一份 10-K 的 MD&A 章节可能包含相关说明"
}
```

运行框架校验 `need_id` 与 `evidence_id` 都存在，并把 `state` 保存到运行记录；`state` 不进入工具的业务参数。

### 8.2 控制工具

| 工具 | 参数 | 效果 |
|---|---|---|
| `clarify` | `question`、`blocking_need_ids`、`state` | 运行状态变为 `needs_clarification`，问题返回调用方；调用方回答后新建上下文继续 |
| `deliver` | `needs: [{need_id, status, evidence_ids, note}]`、`stop_reason`、`state` | 程序按第 9 节组装交付包；引用了未返回过的证据时拒绝并要求修正 |

需求计划由 Data Agent 在首轮通过 `state` 提出，后续修订需在 `reason` 中说明；删除未满足的需求不能让覆盖变为完整。

### 8.3 输出模板与长度预算

程序保留完整结构化响应；写回对话的是按确定性模板生成的文本，不调用模型。每段输出都以状态行开头、以继续入口结尾。

| 工具 | 默认展示上限 |
|---|---|
| `find_assets` | 10 个候选，每个不超过 400 字符 |
| `get_asset_schema` | 概览加不超过 40 个目录节点或字段 |
| `search_asset` | 8 个命中，每个片段不超过 300 字符 |
| `read_evidence` | 遵循请求的 `max_bytes`，默认 24,000 字节 |
| `query_records` | 50 条记录；计算结果全部展示 |

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

## 9 `run_query` 与交付包

### 9.1 `run_query`

`DataService.run_query(context_ref) -> DeliveryPackage`：在给定上下文中运行 Data Agent，直至交付、需要澄清、取消或达到停止条件。调用方可以中途取消；取消后返回已确认部分与 `stop_reason=cancelled`。

### 9.2 `DeliveryPackage`

| 字段 | 说明 |
|---|---|
| `delivery_id` | `dl_` 标识 |
| `context_ref`、`run_id` | 对应的上下文与运行 |
| `prior_delivery_refs` | 补数时引用的原交付包 |
| `needs_plan` | `{version, needs: [{need_id, description, required}]}`，含修订历史引用 |
| `needs` | `[{need_id, status, evidence_ids, gaps, note}]`；`note` 标为模型说明 |
| `evidence` | 被引用的证据项（第 5 节结构），每项含 `asset_ref` 与 `locator` |
| `records`、`calculations` | 被引用的记录与计算（第 6 节结构） |
| `assets_used` | 实际使用的 `asset_ref` 列表，均已冻结 |
| `conflicts` | `[{need_id, evidence_ids, description}]`；未解决的冲突并列呈现 |
| `gaps` | 未满足的缺口与原因 |
| `search_log_ref` | 本次运行的工具调用记录位置 |
| `usage` | `{model_calls, cost_usd, unknown_cost_reserved_usd, wall_seconds}` |
| `stop_reason` | `delivered / budget_exhausted / max_turns / no_progress / wall_time / cancelled` |
| `created_at` | 系统时间 |

**闭包规则：**`needs` 引用的每个证据、记录和计算都必须在 `evidence`、`records`、`calculations` 中出现，并来自本次运行的工具结果；它们引用的每个 `asset_ref` 都在 `assets_used` 中。交付包写入后不可修改，新的补充生成新的交付包。

## 10 内部组件接口

以下为 Python 接口草案（`typing.Protocol`），供实现与测试对齐；签名中的类型均来自 `contracts/`。

```python
class CatalogRepository(Protocol):
    def resolve_entities(self, names: list[str], securities: list[SecurityQuery], at: datetime) -> EntityResolution: ...
    def search_assets(self, ctx: RequestContext, req: FindAssetsRequest) -> FindAssetsResponse: ...
    def get_build(self, ref: AssetRef) -> BuildRecord: ...
    def begin_build(self, key: BuildKey, job_id: str) -> BuildRecord: ...        # 唯一约束即并发锁
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

class ModelClient(Protocol):
    def complete(self, messages: list[Message], tools: list[ToolSchema], *, require_one_call: bool) -> ModelTurn: ...
    # ModelTurn = 单个工具调用 + 用量；费用先预留后结算
```

- `ContentIndex` 的所有实现（FTS5 基线、PageIndex、OpenAI 文件检索）返回同一种 `SearchPage`，命中必须映射到 build 内的块 ID 与 locator；映射失败的命中进入 issues。
- `SourceConnector.fetch` 对重定向目标与附件逐个重新检查策略；被拒绝时返回 `denied_by_policy`，不抛出静默异常。
- `BuildStage` 不直接写 SQLite；状态变更由管线编排器经 `CatalogRepository` 完成，保证发布协议只有一个入口。

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
