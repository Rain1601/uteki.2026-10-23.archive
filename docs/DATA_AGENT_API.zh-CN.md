# Data Agent 接口契约

日期：2026-10-13 · 版本：v0.2 · 状态：设计稿，尚未实现或联调。

本稿先定义资产搜索 `find_assets` 的方法、request、response 和边界行为。用户提供的 JSON 仅作结构参考；这里采用结果列表、展示摘要和结构化元数据，不引入示例中的业务专属字段。职责与数据关系见[核心设计](DATA_AGENT_FRAMEWORK_DESIGN.zh-CN.md)，接口细节在本文件维护。

**分层说明（2026-10-13）：**[核心设计第 7.2.1 节](DATA_AGENT_FRAMEWORK_DESIGN.zh-CN.md#721-找资产从用户问题到模型可见候选已确认)的找资产流程与职责已确认。本稿现有 JSON 属于 HTTP 与程序侧结构的字段草案，不是原样写入模型上下文的内容；模型接收经过归一化、合并、去重排序、模板格式化及长度控制的工具 `output`。Function 参数、HTTP 补参映射与模型可见文本尚待分别对齐，本稿字段不因流程确认而一并通过 review。

参考流程中的 HTTP 分层不构成雨滴的部署选型；以下 HTTP 映射仍为提案。已确认的后续交接是先取得资产说明与读取入口，正文按需读取；说明的九类信息及其含义见核心设计第 7.2.2 节，该能力的字段名、JSON 结构和详细接口尚未确定。

示例中的主体、期间、ID、URL 与耗时均为虚构。其他工具的详细接口按需补充。

## 1 方法

| 项目 | 约定 |
|---|---|
| 逻辑方法 | `find_assets(request) -> response` |
| HTTP 映射 | `POST /api/data/assets/search`，拟议路由 |
| 内容类型 | request 与 response 均为 JSON；字段统一使用 `snake_case` |
| 职责 | 在本次授权范围内搜索已登记资产，返回候选摘要、匹配情况与固定版本引用 |
| 查询边界 | 不触发外部获取或解析；本地结果适配按程序规则执行，后端检索/排序是否使用模型待核对实现；全文、表格值与完整 schema 由后续读取工具取得 |
| 后续交接 | 选中结果后，将 `asset_ref` 原样交给 `get_asset_schema`，不从标题或 URL 重新猜测资产身份 |

## 2 Request

```json
{
  "context_ref": "req-demo",
  "query": "年度报告",
  "filters": {
    "company_names": ["示例公司"],
    "asset_kinds": ["document"],
    "material_types": ["annual_report"],
    "reporting_periods": ["FY2025"],
    "published_at": {
      "gte": "2026-01-01T00:00:00+08:00",
      "lt": "2026-04-01T00:00:00+08:00"
    }
  },
  "as_of": "2026-04-01T00:00:00+08:00",
  "limit": 10,
  "cursor": null
}
```

| 字段 | 类型 | 必填 | 规则 |
|---|---|---|---|
| `context_ref` | string | 是 | 引用已建立的请求上下文，继承主体、来源、截止日及资源边界；服务端每次校验调用方是否可使用该上下文 |
| `query` | string | 否 | 搜索资产标题、材料类型及已登记的描述/覆盖元数据；不能用自然语言覆盖显式过滤条件 |
| `filters` | object | 否 | 支持下表所列过滤条件；与 `query` 至少提供一项非空条件 |
| `as_of` | datetime | 否 | 本次查询的历史可得截止时间，按 `available_at <= as_of` 判断；省略时继承上下文，两处都未指定则不声明历史截止日查询 |
| `limit` | integer | 否 | 默认 10，允许 1–50；越界报参数错误，不静默截成合法值 |
| `cursor` | string 或 null | 否 | 首次请求省略或为 null；翻页使用上一页返回的原样游标 |

| 过滤字段 | 类型 | 含义 |
|---|---|---|
| `company_names` | string[] | 公司正式名称或已登记别名；在授权实体目录内解析为主体 ID，返回规范名称与 ID |
| `entity_ids` | string[] | 已知主体 ID 时可直接传入；匹配登记的材料或数据主体，不把正文提及当作发行主体 |
| `asset_kinds` | string[] | `document` 或 `dataset`；PDF/HTML/API 是表现形式，不是这里的资产类别 |
| `material_types` | string[] | 已注册材料类型，例如 `annual_report`；未知枚举报错 |
| `reporting_periods` | string[] | 材料的报告期间，例如主体对应的 `FY2025` |
| `content_periods` | string[] | 内容覆盖期间；命中任一所列期间即可成为候选，不要求单份材料覆盖全部期间 |
| `published_at` | object | 发布日期范围，支持 `gte`（含起点）与 `lt`（不含终点）；至少提供一个 datetime，双边同时提供时须 `gte < lt` |

不同过滤字段之间是 AND，同一数组内是 OR。字段省略表示不增加该条件；空数组、未知字段或错误类型报 `INVALID_REQUEST`。财政期间按主体已登记的期间定义解释，不能默认等于自然年。

`company_names` 与 `entity_ids` 是同一主体条件的两种输入方式，可任选其一；两者同时提供时，名称解析后的 ID 集合必须与显式 ID 集合一致，否则报 `ENTITY_MISMATCH`，不擅自选一边。名称找不到报 `ENTITY_NOT_FOUND`；对应多个主体时报 `ENTITY_AMBIGUOUS`，通过 `error.details.candidates` 返回授权范围内的候选名称与 ID，不自动选首项。名称解析仅使用已登记目录，不触发外部搜索。

**datetime 的 JSON 表达（查询边界草案）：**请求中的时间边界拟采用带时区的 datetime，JSON 使用 ISO 8601 字符串表达，schema 对应 `type=string, format=date-time`。接受 `Z` 或明确时区偏移，拒绝无时区时间及仅有日期的字符串。比较时统一为 UTC；不把 `FY2025` 转换成某个默认时间点。

资产元数据中的时间保留来源精度：只有日期时不补造时刻，已知时区信息随时间保留。此原则已在核心设计第 7.2.2 节确认；日期精度、未知时区的编码及与请求时间边界的比较方式仍待细化，不能由以上请求格式反推来源必有精确时刻。

三个时间含义分别保留：`reporting_periods` 是财报期间；`published_at` 是材料发布日期范围；`as_of` 是当时能够取得材料的截止时间。显式 `as_of` 可收紧上下文截止时间，不能晚于上下文允许值；冲突报 `SCOPE_DENIED`，不静默覆盖。发布日期不能单独证明可得时间，`available_at` 未知时不能冒充满足历史截止日。

主体、来源及截止日是硬边界，未经验证满足边界的资产不作为合格候选返回。范围越界的显式请求报错，不静默放宽。报告/内容期间、发布日期等匹配元数据未知时，允许返回 `match.status=unresolved` 的候选，并列出未解决字段；因未知可得时间无法满足截止日的情况则记入搜索级缺口。

## 3 Response

### 成功示例

```json
{
  "operation_id": "op-demo-001",
  "status": "ok",
  "items": [
    {
      "asset_ref": {
        "asset_id": "asset-demo-2025",
        "snapshot_id": "snap-1",
        "representation_id": "pdf-1",
        "build_id": "build-1"
      },
      "asset_kind": "document",
      "title": "示例公司 FY2025 年度报告",
      "url": "https://app.example/assets/asset-demo-2025?snapshot_id=snap-1&representation_id=pdf-1&build_id=build-1",
      "summary": "示例公司｜FY2025 年度报告｜PDF｜内容覆盖 FY2024、FY2025｜语义索引部分完成",
      "metadata": {
        "entity_refs": [{"entity_id": "issuer-demo", "name": "示例公司", "role": "issuer"}],
        "material_type": "annual_report",
        "format": "pdf",
        "reporting_period": "FY2025",
        "content_periods": ["FY2024", "FY2025"],
        "published_at": "2026-03-01T00:00:00Z",
        "available_at": "2026-03-01T00:00:00Z",
        "source_url": "https://issuer.example/reports/fy2025.pdf"
      },
      "readiness": {
        "original": "ready",
        "structure": "ready",
        "semantics": "partial"
      },
      "match": {
        "status": "matched",
        "matched_fields": ["query", "company_names", "asset_kinds", "material_types", "reporting_periods", "published_at", "as_of"],
        "unresolved_fields": []
      },
      "issues": [
        {"code": "SEMANTIC_INDEX_PARTIAL", "message": "部分内容尚未完成语义标注"}
      ]
    }
  ],
  "next_cursor": null,
  "truncated": false,
  "coverage": {
    "status": "complete",
    "catalog_revision": "catalog-demo-1"
  },
  "issues": [],
  "error": null,
  "resource_usage": {"elapsed_ms": 12, "external_calls": 0}
}
```

`summary` 是从已登记元数据格式化得到的可读摘要，`metadata` 是供程序使用的结构化值；不能通过解析摘要获得正式字段。`title` 与 `url` 只保存一份，不嵌套复制另一套搜索结果。

### 顶层字段

| 字段 | 类型 | 规则 |
|---|---|---|
| `operation_id` | string | 本次工具调用标识，关联实际查询条件、目录版本与运行记录 |
| `status` | string | `ok`：本页搜索正常完成；`partial`：有可用结果但存在未解决匹配、搜索缺口或执行截断；`error`：请求未成功执行 |
| `items` | object[] | 本页候选资产；无匹配时为空数组，失败时也为空，须结合 `status` 判断 |
| `next_cursor` | string 或 null | 下一页入口；null 表示没有可提供的下一页，不单独证明所有范围已经查完 |
| `truncated` | boolean | 是否因执行/资源上限提前停止；普通分页不是截断 |
| `coverage` | object | 本次目录搜索的评估范围状态与冻结目录版本；不表示研究问题已获得完整证据 |
| `issues` | object[] | 搜索级缺口，元素包含 `code`、`message` 及必要的范围说明；资产自身问题放在对应 item 中 |
| `error` | object 或 null | 成功/部分成功为 null；失败返回稳定的 `code` 与可读 `message`，必要时用 `details` 说明候选或冲突字段，客户端不解析报错文案做分支 |
| `resource_usage` | object | 实测 `elapsed_ms` 与 `external_calls`；本方法外部调用数必须为 0 |

`coverage.status` 取 `complete / partial / not_started`，分别表示当前目录搜索视图中的条件已评估、尚有无法评估的范围、尚未开始搜索；未开始时 `catalog_revision=null`。仍有下一页可与 `coverage.status=complete` 并存，调用方须读取 `next_cursor`。

### 候选资产字段

| 字段 | 类型 | 规则 |
|---|---|---|
| `asset_ref` | object | 包含 `asset_id / snapshot_id / representation_id / build_id`；固定原件与处理版本，不能隐式转向最新版本 |
| `asset_kind` | string | `document` 或 `dataset`，与核心设计一致 |
| `title` | string | 资产名称 |
| `url` | string 或 null | 面向阅读的资产详情链接，必须定位到返回的版本；尚无浏览入口时为 null |
| `summary` | string | 有界的格式化元信息，未知项明确表示未知，不填补事实 |
| `metadata` | object | 主体 ID/规范名称/角色、材料类型、表现形式、报告期间、已知内容期间、发布时间、可得时间与来源链接 |
| `readiness` | object | 原件、结构、语义等能力各自的处理状态；不能由文件存在推断全部 ready |
| `match` | object | `status=matched/unresolved`，并列出 `matched_fields` 与 `unresolved_fields`；matched 仅表示满足本次资产检索条件 |
| `issues` | object[] | 当前资产的处理缺口或冲突；每项至少包含 `code`、`message` |

只登记了原件、尚无可发布处理结果时，`build_id=null`，对应能力标为 `not_ready`；读取工具须返回未就绪，而不是替调用方启动处理。`readiness` 各能力使用 `ready / partial / not_ready / failed / not_applicable`，与匹配状态、语义验收结论分别记录。

`metadata.format` 为当前表现形式的 `pdf / html / api`。`dataset` 的 `material_type` 取该资源注册的数据类别，`reporting_period` 可为 null；`content_periods` 列实际观察到的期间，未知为 null，不以空数组代替未知。时间使用带时区的 datetime 字符串；未知 `published_at` 或 `available_at` 为 null，禁止以获取时间填充。

`source_url` 是原始来源地址，API 来源仅提供不含凭据的资源入口；它不替代版本引用。完整字段、单位、分页一致性与定位规则由后续 schema 返回。

## 4 空结果 部分结果与错误

| 情况 | 返回约定 |
|---|---|
| 范围内没有匹配资产 | `status=ok`、`items=[]`、`next_cursor=null`、`error=null`；不解释成“公司没有披露” |
| 正常返回一页，仍有更多结果 | `status=ok`、`next_cursor` 非空、`truncated=false` |
| 匹配期间未知，或部分目录范围无法检索 | `status=partial`；保留可用/待核对候选，分别在 `match` 与搜索级 `issues` 中说明 |
| 资产语义索引未完成，但本次标题/身份/报告期间筛选可完整执行 | 本次搜索可为 `status=ok`；资产仍保留语义 `partial` 与自身 issues，不宣称资产已通过语义验收 |
| 公司名称无匹配、多义或与 ID 冲突 | `status=error`，分别返回 `ENTITY_NOT_FOUND / ENTITY_AMBIGUOUS / ENTITY_MISMATCH`；不当作资产零命中或自动改查其他公司 |
| 时间缺少时区、区间倒置，或截止日超出上下文 | 时间格式/区间错误报 `INVALID_REQUEST`；越过上下文截止日报 `SCOPE_DENIED` |
| 参数错误、范围越界、游标失效或目录无法读取 | `status=error`、`items=[]`、非空 `error`；不将失败伪装成无匹配 |

参数错误示例：

```json
{
  "operation_id": "op-demo-002",
  "status": "error",
  "items": [],
  "next_cursor": null,
  "truncated": false,
  "coverage": {"status": "not_started", "catalog_revision": null},
  "issues": [],
  "error": {"code": "INVALID_REQUEST", "message": "limit 必须为 1 到 50 的整数"},
  "resource_usage": {"elapsed_ms": 1, "external_calls": 0}
}
```

HTTP 映射：正常、空结果与部分结果返回 200；`INVALID_REQUEST`、`CURSOR_MISMATCH` 及上述三个 `ENTITY_*` 错误返回 400；调用身份缺失/无效返回 401；`SCOPE_DENIED` 返回 403；`CURSOR_EXPIRED` 返回 410；`CATALOG_UNAVAILABLE` 返回 503；未分类的服务端异常返回 500 和 `INTERNAL_ERROR`。由应用层生成的错误沿用上述信封，网络或网关错误由调用方按传输错误记录。

## 5 分页与版本约束

首次调用冻结可搜索目录视图；后续游标绑定该目录版本、实体目录版本与名称解析结果、请求上下文、query、filters、有效 as_of 与 limit。翻页时保持这些参数不变，只替换 cursor；实体目录变化也不能让同次搜索悄悄换公司。条件改变须开始新的搜索；游标过期或无法重现旧视图时明确报错，不能自动改用当前最新目录。

每项结果对应一个完整 `asset_ref`，同一版本重复命中仅返回一次。不同修订或表现形式可分别成为候选，不因标题相同而合并，也不默认“最新即适用”。同分结果使用固定的完整引用排序，避免翻页重复或遗漏。

资产搜索结束不代表取数任务完成。后续读取沿用选定 `asset_ref`；缺原件或缺处理能力时，由独立补建设入口处理，并继承原请求政策和预算。
