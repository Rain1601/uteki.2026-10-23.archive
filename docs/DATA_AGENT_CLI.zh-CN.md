# 公司 Data Agent CLI

## 只获取官方原件（2026-10-04）

新增 `agent acquire --config <公司来源配置> --workspace <原件库>`，直接调用已有获取组件，不调用模型、不要求模型凭据、不启动解析。支持显式 CIK 与 10-K / 20-F 年报区间；真实配置见 `config/company_sources/amd-annual-v1.json` 和 `tsmc-annual-v1.json`。联系身份按 `--sec-user-agent`、环境 `UTEKI_SEC_USER_AGENT`、非空公司配置、私有 `.env` 顺序读取；`--settings-root` 默认为工作目录，可显式指定。逐份状态保存在返回的 `manifest_path`，有缺口退出 2。本机既有 SEC 联系身份已持久保存，后续无需重复输入。

完整范围、恢复规则及真实验收状态见[自动获取说明](design/UTEKI_REPORT_ACQUISITION_v1.zh-CN.md)。旧历史配置没有 `filing_selection` 时现在会明确报错；应另建明确范围的新版本。

四个入口共用 `CompanyDataCoordinator`，执行结果保存在新目录。原件、数据集和旧运行不可覆盖；所有候选事实仍需复核，不会自动采纳。

## 准备和检查

本机的 SEC 联系身份已配置，运行时会自动读取；服务器需提供自己的私有配置。原始配置与有效运行配置分别保存在运行目录；有效配置包含 SEC 联系身份，分享产物前需检查。

已登记的公司可以通过名称或代码选择，资料范围取自显式目录绑定的配置。目前目录为 AMD / 台积电、FY2023 起、截止 2026-10-04。未知名称、缺少目录、身份冲突或配置 hash 变化直接报错，不回退到示例公司。

```bash
PYTHONPATH=src:. .venv/bin/python -m uteki.infrastructure.research_data.query_cli agent prepare \
  --company AMD --company-catalog config/company_sources/annual-pilot-catalog-v1.json \
  --workspace /tmp/uteki-source-store --output /tmp/amd-prepare-001

PYTHONPATH=src:. .venv/bin/python -m uteki.infrastructure.research_data.query_cli agent prepare \
  --company 台积电 --company-catalog config/company_sources/annual-pilot-catalog-v1.json \
  --workspace /tmp/uteki-source-store --output /tmp/tsmc-prepare-001

PYTHONPATH=src:. .venv/bin/python -m uteki.infrastructure.research_data.query_cli agent inspect \
  --run /tmp/amd-prepare-001
```

`acquire / prepare / refresh` 同时保留 `--config` 入口，与 `--company` 互斥。`prepare` 不调用模型：发现并冻结官方原件，生成正文/表格索引、受当前适配器支持的候选事实及 DuckDB。输出的 `stage_coverage` 区分原件、正文、表格结构、候选数值和未进行的财务语义核验。

`prepared_with_gaps` 表示有可查询来源且仍有缺口；既不表示全部资料收齐，也不表示核心财务包完整。0 records 时正文仍可查看；不能因此把财务提取标为完成。`inspect` 校验运行文件与引用数据集的哈希，不判断金融语义。

解析器修复后，可用 `agent prepare --from-run /tmp/amd-prepare-001 --workspace /tmp/uteki-source-store --output /tmp/amd-reprocessed-001` 从核验过的冻结原件重新入库。此路径不发 HTTP 请求。`refresh` 则重新查询官方披露清单；内容和实现均未变时复用已核验数据集，同时保留它原有的解析缺口。输出目录须为新目录。

旧基线的“最新 10-K 及后续申报”需要显式配置 `filing_selection.mode=latest_10k_and_subsequent_filings`，不再是默认行为。指定旧年报时，在**新配置文件**中显式增加下列字段，日期须来自 SEC 发现清单，不能由自然年猜财年：

```json
{"filing_selection":{"mode":"annual_report_period","report_period_end":"2025-06-30"}}
```

该模式只取得对应年报和修订；其他官方材料仍由基线准备管理。未发现该期间则返回缺口，不替换为最新年报。获取产物的 `filing_catalog` 保留已发现年份及未遍历的范围。

## 查询

### 年报按表提取：Uteki 实际加载 Skill

`agent extract-batch` 从明确的任务配置选择默认或允许的方法，校验其 Prompt/Skill 文件版本后执行一个指定批次。此路径使用 Uteki 自己的运行模块，不要求运行中的 Codex 阅读 Skill 或手动生成提取答案。

```bash
PYTHONPATH=src:. .venv/bin/python -m uteki.infrastructure.research_data.query_cli agent extract-batch \
  --dataset /path/to/frozen-dataset \
  --job /path/to/explicit-extraction-job.json \
  --task-profile config/data_tasks/annual-financial-v1.json \
  --method-root /Users/bytedance/Documents/ChatGPT/uteki \
  --batch-index 0 \
  --model-config /path/to/extractor-model-config.json \
  --credentials-root /Users/bytedance/Documents/ChatGPT/uteki \
  --output /path/to/new-batch-run
```

任务 JSON 必须显式声明 `task_type`，与 profile 一致；还需给出公司、来源快照、信息截止、任务、原文块及所需目录。不得再提供竞争的 inline `prompt`。当前 profile 的任务类型为 `annual_financial_extraction`，默认并仅允许 `annual-financial-v2`；这是年报财务提取能力配置，不携带默认公司、年份或金额。

`--method-id` 可以显式选择 profile 允许的方法；未知任务/方法、缺少输入、来源不适用、文件版本不匹配均拒绝，不自动猜另一套方法。未来新增 Skill 先由 Codex 编写和独立评估，再以新配置明确启用。此 CLI 的批次由调用方指定；主 query Planner 自主选批使用下文的登记任务入口。

`method-snapshot.json` 保存方法资产及实际加载内容；最终带输出 schema 的系统指令位于 `extraction-01/system-prompt-effective.json`。`batch-catalog.json`、`coverage.json` 和结果保留已执行、失败、未执行批次及正文缺口。单批结束不能视为整份财报完成，候选也不会自动采纳。

模型配置必须显式提供 `provider`、`model`、共享 `budget_ledger`、`budget_usd`、`max_requests_total`；无金额或次数上限时使用显式 `null`。换 Skill 不隐式换模型或重置账本。输出目录必须新建且位于冻结数据集之外；旧 `agent extract --strategy ...` 仍保留通用直接提取功能，但它不是受此任务 profile 约束的入口。

### 按研究问题查询

查询 JSON 选择一种输入：

- `prepared_run` + 显式 `include_candidates`：复用已核验准备结果，可按题目补取旧年报。
- `company_config` + 显式 `include_candidates`：同一次查询先准备，再查询。
- `dataset` + 完整 `scope`：查询冻结数据集；此模式不提供获取回调。

例如 `request.json`：

```json
{
  "question": "提供 Microsoft FY2025 收入、营业利润率和 Business 业务说明的原文出处。",
  "prepared_run": "/tmp/msft-prepare-001",
  "include_candidates": true,
  "limits": {"max_steps": 24, "observation_bytes": 12000, "max_packet_bytes": 300000}
}
```

```bash
.venv/bin/python -m uteki.infrastructure.research_data.query_cli agent query \
  --request /tmp/request.json --model-config /tmp/model-config.json \
  --workspace /tmp/uteki-source-store --output /tmp/msft-query-001
```

`model-config.json` 必须明确 `provider`、`model`、`budget_ledger`、`budget_usd`、`budget_policy`（`record_only` 或 `enforced`）、`max_requests_total`，可选 `max_tokens`、`request_timeout`、`max_retries`。模型须已登记价格与凭据支持；没有默认模型。`record_only` 中的 `budget_usd` 为预算参考，费用不阻断；累计请求上限仍强制执行。SDK 隐式重试关闭，显式重试/超时逐次计入共享账本。账本必须放在冻结产物之外，重复运行沿用同一账本，不能用新目录重置额度。

用户已授权本任务的 LLM 提取/复核直接执行，调用前告知范围、模型与请求限制，无需逐次等待审核。历史 DeepSeek 46/48 账本不挪用；真实 query benchmark 的配置和累计限制仍单独准备。Python 可注入 planner 做离线验证，强制标为 `scripted_fixture`，不能作为模型验收。

查询输出包含 `query/` 下的请求、计划、逐轮输入/决策/回执、证据 manifest 与完整产物；真实适配器另保存 `model/` 配置、逐请求记录及使用量快照。结果 `evidence_ready` 仅表示宿主引用/声明需求检查满足；`semantic_completeness` 仍为 `not_evaluated`。缺资料保持 `partial`，不会把搜索无匹配解释为未披露。

### 主 Agent 自主选择已登记的财务提取批次

`agent query` 可在 `CompanyQueryInput.financial_tasks` 中登记财务提取任务，并提供 `--extractor-model-config` 和 `--method-root`。宿主先校验已有选材 job、来源和任务方法，冻结允许的 Prompt/Skill；主 Planner 根据表格目录的原文片段选择相关批次，声明 `kind=financial_extract` 需求，再调用正式 `financial_extract` 动作。调用方无需指定 `--batch-index`。

以下为请求结构模板，所有尖括号占位值及日期须替换为所选冻结数据集的实际值，不能直接运行。`job` 是嵌入的完整提取输入对象，沿用已有选材与目录；它不是 job 文件路径，也不得含 inline `prompt`。

```json
{
  "question": "从登记的年度财报范围选择现金流相关表格，生成一个批次的候选财务记录，列出尚未覆盖的部分。",
  "dataset": "/path/to/frozen-dataset",
  "scope": {
    "snapshot_id": "<dataset snapshot_id>",
    "company_ids": ["<company_id>"],
    "source_snapshot_ids": ["<source_snapshot_id>"],
    "source_policy_id": "local-frozen-v1",
    "knowledge_cutoff": "YYYY-MM-DD",
    "include_candidates": true
  },
  "limits": {
    "max_steps": 12,
    "turn_timeout": 300,
    "max_packet_bytes": 300000,
    "observation_bytes": 12000
  },
  "financial_tasks": [{
    "task_id": "annual-financial-task-01",
    "task_profile": "config/data_tasks/annual-financial-v1.json",
    "task_profile_sha256": "<SHA256 of the exact task profile bytes>",
    "max_new_batches": 1,
    "job": {
      "task_type": "annual_financial_extraction",
      "company_id": "<company_id>",
      "source_snapshot_id": "<source_snapshot_id>",
      "dataset_manifest_sha256": "<SHA256 of the exact dataset manifest bytes>",
      "as_of": "YYYY-MM-DD",
      "task": "从显式选定的原文提取财务候选，保留来源、期间、单位及未解决项。",
      "block_ids": ["<selected source block_id>"]
    }
  }]
}
```

正式 job 还应保留该选材任务已有的 `entity_catalog`、`period_catalog`、`record_schema_version` 和显式归一化配置等字段。期间目录须绑定同一公司与来源，实际财年日期来自原材料；不能从题目中的年份补出日历年或用另一家公司的映射填空。示例省略这些目录的内容，并不授权清空或猜测它们。

每项登记必须具备唯一 `task_id`、显式 `job`、相对 `method-root` 的 `task_profile`、对应文件 SHA256 和正整数 `max_new_batches`。job 的公司与来源须在 scope 内，`as_of` 必须等于 scope 截止日，数据集 manifest hash 必须匹配。宿主生成的目录保留 `catalog_id`、各批次的原文片段和允许方法；模型只能提交 `task_id`、`batch_index` 及可选的允许 `method_id`，不能更换文件路径、来源、期间目录或模型设置。

```bash
PYTHONPATH=src:. .venv/bin/python -m uteki.infrastructure.research_data.query_cli agent query \
  --request /path/to/financial-query-request.json \
  --model-config /path/to/planner-model-config.json \
  --extractor-model-config /path/to/extractor-model-config.json \
  --method-root /Users/bytedance/Documents/ChatGPT/uteki \
  --credentials-root /Users/bytedance/Documents/ChatGPT/uteki \
  --workspace /path/to/source-store \
  --output /path/to/new-financial-query-run
```

Planner 与 Extractor 的配置分别选择模型，但必须使用**同一个** `budget_ledger`、`budget_usd`、`budget_policy` 和 `max_requests_total`。任一值冲突会在模型调用前拒绝；更换任务、Skill、输出目录或角色不重置共享累计账本。登记任务时必须同时提供 Extractor 配置及 method-root；没有登记任务时不得携带这些金融执行配置。

当前 DeepSeek 角色配置示例如下，账本路径须替换为当前任务既有账本。`null` 表示显式无金额/累计请求上限；`max_steps` 与 `max_new_batches` 仍分别控制本轮决策数和批次启动数。

Planner 配置：

```json
{
  "provider": "deepseek",
  "model": "deepseek-v4-pro",
  "reasoning_effort": "high",
  "budget_ledger": "/path/to/shared-budget.sqlite",
  "budget_usd": null,
  "budget_policy": "record_only",
  "max_requests_total": null,
  "max_tokens": 8192,
  "request_timeout": 300,
  "max_retries": 0
}
```

Extractor 配置：

```json
{
  "provider": "deepseek",
  "model": "deepseek-flash",
  "reasoning_effort": "low",
  "budget_ledger": "/path/to/shared-budget.sqlite",
  "budget_usd": null,
  "budget_policy": "record_only",
  "max_requests_total": null,
  "max_tokens": 16384,
  "request_timeout": 300,
  "max_retries": 0
}
```

主 Planner 的 `max_tokens` 支持 256–8192，不能沿用 Extractor 的 16384；超范围配置会在请求发送前拒绝。首次较长财表提取可将请求中的 `limits.turn_timeout` 与两个角色的 `request_timeout` 均明确设为 300 秒，避免外层默认 120 秒提前结束提取。当前金融提取固定不做 SDK 自动重试，Extractor 的 `max_retries` 应明确为 `0`；登记网关明确拒绝非零或非整数重试值，避免配置被静默忽略。失败需保留版本并检查原因；本例 `max_new_batches=1` 的额度已消耗时，需要另建明确输入的新运行。

纯财务提取需求得到匹配的成功回执后，结果为 `candidate_ready`：仅表示候选批次已生成。0 条归一化记录仍可能伴随原始草稿与映射缺口，不能据此宣布财务包完整。回执中的 `gaps`、数量和覆盖范围必须一并检查；`semantic_acceptance=not_evaluated`、`adoption=unchanged_candidate` 保持不变。混合查询仍按各需求分别检查；财务生成回执不能代替数值查询结果或主 Agent 的原文阅读记录。

本次运行的登记资料位于 `registered-financial/`，其中保留冻结 job、scope、目录和方法资产；Agent 的逐轮决策与提取位于 `query/turn-*/financial_extract/`，成功回执另存 `financial-receipts/`。`query/result.json` 的 `financial_extractions` 指向候选产物，主运行 `result.dataset` 继续指向查询 baseline，不会悄悄切到新候选 DB。

成功复用只在**同一次运行内**生效：同任务、批次与方法文件版本的重复调用先校验已有产物，再返回原成功回执，不再次调用模型。真正启动一次批次即消耗 `max_new_batches`；模型失败也计入，失败不会进入成功缓存。未知任务/批次、非法方法等启动前拒绝不消耗该批次额度。新运行不会自动加载上一轮成功批次，跨运行恢复尚未实现。

此入口的自主性限于**已登记选材范围内的选批、执行和反馈处理**。登记 job 可以来自此前的模型选材，系统会冻结其输入；当前入口不会自动重做全文选材、补建期间目录或覆盖未选中的原文。未分配正文、未运行表格、漏提与内容复核仍是独立缺口，不能把一个候选批次称作整份年报闭环。

## 更新和产物回读

```bash
.venv/bin/python -m uteki.infrastructure.research_data.query_cli agent refresh \
  --config /tmp/msft-new-cutoff.json --previous /tmp/msft-prepare-001 \
  --workspace /tmp/uteki-source-store --output /tmp/msft-refresh-001

.venv/bin/python -m uteki.infrastructure.research_data.query_cli agent inspect \
  --run /tmp/msft-query-001 --artifact-request /tmp/artifact-read.json
```

`refresh` 保持公司和来源选择策略，允许截止日向前推进；数据和解析实现未变时复用数据集。新解析版本重新物化，不修改原件或旧快照。获取/物化取消时等待正在执行的工作退出，保存取消状态；部分新增资料无法入库时，查询保持原 scope。

`artifact-read.json` 使用 `artifact_id`、可选 JSON `pointer`、`cursor` 和 `limit`。ID 来自查询 `artifact-index.json`；游标绑定原 scope 和 hash，不能拿另一运行的游标续读。

当前完整性边界与真实验证见[技术方案](DATA_AGENT_AUTONOMY_PLAN.zh-CN.md)和[benchmark](DATA_AGENT_BENCHMARK.zh-CN.md)。查询运行尚需 T4 专用导出，才能满足 benchmark 的题目/来源绑定及累计逐请求证据接口。

## 提取后的 LLM 记录复核

`scripts/review_data_records.py` 是独立复核入口，目前尚未自动挂入 `prepare`。输入 JSON 必须显式提供冻结 `dataset` 路径、完整 `ExecutionScope` 和非空、唯一的 `record_ids`；实体及期间由这些记录固定，不能传入额外字段后静默忽略。仅支持一条记录对应一个已定位 inline fact 的输入。

```bash
.venv/bin/python scripts/review_data_records.py prepare \
  --request /path/to/review-request.json --output /path/to/review-inputs-001

.venv/bin/python scripts/review_data_records.py run \
  --inputs /path/to/review-inputs-001 --output /path/to/review-run-001 \
  --provider deepseek --model deepseek-v4-pro \
  --budget-ledger /path/to/review-budget.sqlite \
  --max-requests-total 18 --budget-usd 5 --budget-policy record_only \
  --max-attempts-per-packet 2
```

示例的 18 次是该任务的累计限制，`budget_usd=5` 为费用参考，并非实际账单。SDK 隐式重试关闭，每包最多两次尝试；全部失败、取消与纠正计入同一账本。只有 DeepSeek 路径目前具备该复核器所需的原始响应留档保证。

失败后可从结果中明确选取 `unreviewed_record_ids`，保存为 JSON 数组，通过 `repack --inputs /path/to/old-inputs --record-ids /path/to/ids.json --output /path/to/new-inputs` 生成新版本。它按同一来源去重上下文，每包最多 24 条，保留父输入 manifest 和原片段哈希。新输入 v2 从已验证的数据集读取所选指标定义，与原文证据分开提供。后续 `run` 必须沿用账本；`--max-attempts-per-packet 1` 可关闭纠正重试，`--max-output-tokens` 的允许范围为 256–16384，默认 8192。

每轮保存：原件/数据集引用及哈希、记录和输入包哈希、原 HTML 片段、完整表格单元格与有界上下文、prompt 与模型配置、原始响应、宿主拒绝原因、逐记录意见、逐请求用量及结果 manifest。新输出目录不可已存在；失败版本继续保留。表格压缩只消除重复字段名，保留空单元格、顺序与跨度；原件字节和旧文本指纹不随格式调整改写。

结果的 `reviewed` 只表示所有指定记录都有通过结构、范围和逐字引用校验的 LLM 意见。意见分别为 `supported / contradicted / insufficient_evidence`，仍不等于正确性或完整性验收。所有原事实继续为 candidate，不改值、不自动采纳；全文漏提审计、链接脚注完整解析、自动补读缺失上下文和下游语义状态联动尚未实现。

## 独立语义检查与 system prompt

`scripts/review_data_semantics.py` 对明确选定的记录检查重述/可比性、分摊、可加总性、维度、地理和数值口径。它复用冻结数据、原文和计费模型，另存语义约束，不覆盖原数值复核意见。当前 system prompt 在 `infrastructure/research_data/semantic_review.py` 的 `SEMANTIC_PROMPT` 中；每次运行保存实际文本和哈希，历史版本保持不变。

`--tasks` 是 `SemanticTask` 数组。每项必须显式提供 `task_id`、1–24 个 `record_ids` 和 `axes`，可以提供 `additional_block_ids` 补读同一冻结来源中的跨注释段落，以及待核验的 `assertions`（每条包含 `assertion_id / record_ids / text`）。不同来源须拆成不同任务，字段 `expected` 或评分答案不能作为任务输入。

```bash
.venv/bin/python scripts/review_data_semantics.py prepare \
  --inputs /path/to/frozen-record-review-inputs \
  --tasks /path/to/semantic-tasks.json --output /path/to/semantic-inputs-001

.venv/bin/python scripts/review_data_semantics.py run \
  --inputs /path/to/semantic-inputs-001 --output /path/to/semantic-run-001 \
  --provider deepseek --model deepseek-v4-pro \
  --budget-ledger /path/to/semantic-budget.sqlite \
  --max-requests-total 24 --budget-usd 5 --budget-policy record_only \
  --semantic-audit --max-attempts-per-packet 3 --max-audit-attempts 2
```

每个请求轴必须分别返回 `constraints_found / none_found_in_context / insufficient_evidence`，附约束、精确受影响记录、原文引用及未解决问题。`none_found_in_context` 只描述本次提供的上下文；相关证据不足时不能当作“未披露”。断言逐条返回支持、矛盾或证据不足。宿主验证字段、覆盖、来源和连续引用；真实输入还逐一回绑冻结原件、记录、指标定义、正文块、表格和原始/精简 DOM。语义内容仍需独立判分。

默认每包一次尝试；`--max-attempts-per-packet` 允许 1–3，协议纠正和语义修订共用这个上限。`--semantic-audit` 启用第二个模型复核意见；`--max-audit-attempts` 允许 1–2，专门修复 critic 的格式或引用错误。两个角色及全部重试计入同一账本、同一个累计请求限制。示例 24 次不是额外授权；既有任务不得通过新账本重置额度。费用策略 `record_only` 保留失败及未知费用。

循环为：生成草稿 → 宿主校验 → critic → 带引用的修订要求 → 新草稿 → 再校验。critic 绑定实际意见 hash，问题须指向现有字段和所选记录；`error` 阻止接受，`suggestion` 只留档。无效 critic 只修复自身协议，不能驱动生成器改结论。网络或运行异常停止整个 run 并归档；只有协议错误可在限额内重试。取消、预算耗尽、未完成包均明确记录。

可选 `--input-format review_turns_v1` 将修订请求组织成原始资料（user）、上一版草稿（assistant）、宿主反馈（user）。字段内容不删减、不补答案；未提供草稿时不伪造 assistant 消息。critic 意见保留为待核验意见，协议修复只要求改写同一 assessment 的 critique。默认仍为 `packet_json_v1`；首次请求的原 JSON 保持不变。每次归档原始 packet、实际 Runner 输入和各自 hash，格式写入模型配置；Runner 输入不等于完整 HTTP 报文。

输出 `assessed` 表示所有请求都有协议合格的意见；启用 critic 时还须通过其复核，但 `semantic_acceptance` 仍为 `model_audited_requires_independent_evaluation`。critic 是另一份模型意见，必须独立评分；其约束尚未自动接入公司 prepare、查询结果或采纳流程。

新 prepare 输出 `semantic-review-input-v3`，旧 v1/v2 仍可读取和验证，v3 沿用 `SemanticAssessmentV2` 输出结构。输入提供实际正文块/引用对象的 `context_inventory` 和原 DOM 派生的 `record_anchors`。表格事实锚定完整行；段落事实锚定实际 inline fact 字符范围，并保留完整上下文，避免强制引用无关整段。dimensions/value 每条约束，以及任务含这些轴时的每条 supported 断言，仍须分别覆盖其所关联记录；表头/定义可作为语义限定引用，但不能代替记录的来源定位。

`source_start` 是字符偏移，唯一逐字文本可省略，由宿主确定；重复文本必须指定位置。明确错误的位置不会被静默修正。缺少来源覆盖时，反馈包含原始未验证草稿、精确字段路径、同组全部缺失 anchors，以及其他组的缺项；宿主不自动补引用或改 verdict。未定位的 anchor 明确报告 unavailable，不能要求模型猜测。`context_claims` 须匹配清单；`context_requests` 和未解决问题只是未核实请求，自由理由仍需独审。

每版保存输入、原始/归一化意见、生成和 critic 的实际 prompt/模型配置、逐次反馈、调用及费用、关键实现源码副本和 manifest。历史意见、数据及失败运行保持不变。源码副本用于对照，尚非完整依赖环境归档。实际质量与版本差异见[v3 报告](../experiments/data_agent_query/semantic-review-v3/README.md)。

独立合成 benchmark 的输入与答案分开保存在 `benchmarks/data_agent/semantic_review/v1/`；准备/评分入口见该目录 README。它与三家公司 13 道 query benchmark 是不同测试，不能相互代替。
