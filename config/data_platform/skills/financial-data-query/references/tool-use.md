# Data 工具使用要点（对应现有 v1 接口）

工具的实时 JSON Schema 是参数权威。这里解释容易误用的语义，不提供任何真实公司答案。

## 输入与引用

- `find_assets.request.query` 是材料元数据短语检索，不是整题语义问答。可先按公司/期间过滤，再用报告标题关键词；不要把整段问题直接当短语。
- `asset_ref` 的 asset/snapshot/representation/build 四项作为整体复制，用于导航。它不是 `result_ref`，不能改名拼成证据引用。
- `result_ref` 只能复制本次运行已展示的 `evidence`、`record` 或 `calculation` 结果。初次调用尚无结果，所有需求应处于 gaps，不能预先引用即将返回的结果。
- 首次提交 `state.plan_update={base_version:0,needs:[...]}`；一旦接受，普通后续调用不再提交旧版本。失败时依据错误中的 `current_task_state.plan`，不能假定计划已提交。
- 每次 `state.satisfied` 与 `state.gaps` 合起来恰好覆盖全部计划需求；`next_action` 是本次工具名。

## 读取与计算

`read_evidence.table_representation` 当前用 `full`；`compact` 虽出现在通用 schema 中，本版本尚不支持。请求完整必要上下文时注意返回页上限。

`query_records.select.fields` 可省略或为空以保留默认字段。需要投影时从 schema 的实际字段列表选择；原文定位叫 `locator`，期间是 `period` 对象。不要把 `entity_scope` 作为返回字段或用它代替合并口径证据；当前范围过滤优先使用实际返回的显式维度。

以下仅是 `calculations` 中一个计算项的形状示例，尖括号必须替换为本次工具返回值，不能原样提交。其余 request/state 依实时工具 schema 填写。

```json
{
  "calc_id": "requested-growth",
  "op": "growth",
  "operands": [
    {"asset_ref": "<本期完整AssetRef对象>", "record_selector": {"record_id": "<本期已观察记录ID>"}},
    {"asset_ref": "<基期完整AssetRef对象>", "record_selector": {"record_id": "<基期已观察记录ID>"}}
  ],
  "output_unit": "ratio",
  "period_policy": "distinct_nonoverlapping",
  "comparison_basis": "<从本次证据确认的同指标、主体、单位、口径和期间比较依据>"
}
```

`growth` 使用 `(本期-基期)/基期`，返回比例而非百分数。`sum`、`difference`、`ratio` 是其他可用运算；不要为非计算问题强制调用。零基数、不同单位、期间重叠、未解析操作数或歧义选择必须保留计算限制，不能填 0。

## 交付与检查示例

虚构任务：“比较甲公司两年收入，列明单位、期间和口径，计算同比并引用来源”。可拆成数值、计算、上下文三个 need；名称由本次计划决定，没有固定 `n1/n2`。

宿主可提供以下需求检查文件。它只表达任务要求，不含答案、记录 ID 或工具序列；完整覆盖任务计划中的需求。

```json
{
  "needs": [
    {"need_id": "amounts", "required_result_kinds": ["record"]},
    {"need_id": "change", "required_result_kinds": ["calculation"]},
    {"need_id": "basis", "required_result_kinds": ["evidence"]}
  ]
}
```

检查器接受当前 `delivery` 包、`DataService.deliver` 响应或 `run_query` 结果文件。引用计算会带入操作数依赖，检查器沿依赖查找所需结果类别。`supported` 只有文字说明而没有要求的结果类别会拒绝；partial/unresolved 保留缺口，`--require-complete` 则返回非零。`note` 只解释已引用结果，不能代替事实/计算。

正常：事实、计算和上下文均有引用，完整交付。缺口：已确认该材料不提供结构化记录，保留能读取的片段，并说明本范围无法生成所需代码计算；这可形成合法 partial，不能宣称完整。尚未尝试：记录查询能力可用、没有阻塞时，仅搜索后说“缺少计算”应继续查询计算，不据此停止。
