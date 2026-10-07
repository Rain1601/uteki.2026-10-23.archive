# 可选补充文件 v1

用于保存人工小样，并通过现有业务/收入验收页的 `--enrichment` 参数展示。它不修改 BusinessMap 域契约、模型主请求或 Workflow。此版本的执行来源限定为人工网页核对；模型自动发现的产物尚未接入。

| 字段 | 含义与检查 |
|---|---|
| `schema_version` | `official-product-enrichment-v1` |
| `binding` | `company_id`、`document_id`、`period_end` 和 `business_map_sha256`，与调用方指定的原图逐项相同 |
| `provenance` | 本版为 `method: codex_manual_web_review`、`model_api_calls: 0`；不冒称 Agent 运行或 Claude 审阅 |
| `entities[].business_id` | 原图中存在的明确节点 ID，同一补充文件不得重复 |
| `official_links[]` | 每个入口保存 `id`、`url`、`final_url`、`title`、`role`、`publisher`、`official_status`、`availability`、`checked_at`、`published_at` 和 `verification` |
| `role` | `product`、`documentation` 或 `release_notes` |
| `official_status` / `availability` | `verified` / `unverified` 与 `readable` / `unavailable` 分开；仅 `verified` + `readable` 可作官网入口及观察来源 |
| `checked_at` / `published_at` | 核对时刻用带时区 ISO 时间；网页发布时间未知写 `null`，不使用核对时刻代替 |
| `verification` | `publisher_basis`、`product_match`、`source_url`、`locator`、`exact_quote`、`quote_sha256`。短原文使用实际观察的文字；hash 对象是原文字符串的 UTF-8 字节，不是整页 |
| `to_watch[]` | `id`、`question`、`why`、`source_ids`、`observable_signal`、`status: suggested`；来源 ID 必须属于此节点的已核对可读入口 |
| `gaps[]` | 非空文字列表，说明无入口、归属未定或粒度不足等问题；没有发现不等于不存在 |

URL 为不含凭据的 HTTPS 地址；页面文本按文本转义，不执行其中代码。每个节点内链接 ID 和观察 ID 唯一。绑定不匹配时拒绝展示，不挪用另一家公司、报告或版本的数据。

本版 `official_links` 保存有实际读取依据的记录。首次无法打开、未观察到最终地址或正文的候选，只在 `gaps` 中保存候选 URL、检查时间及具体失败原因，不填假摘录或猜测最终地址。若已有真实读取记录、此次发现不可访问，可以保留原核验记录并标 `unavailable`，但不得将旧摘录标成本次读取，页面只将它呈现为缺口。

`verified` 是保存的审阅结论。当前渲染器只验证记录结构、hash 和引用，不联网，也不自动识别官方身份。正式自动发现需要另行验证来源资格和受约束抓取边界，不能把通过此格式校验当作完成。

真实小样：[NVIDIA AI Enterprise 补充记录](../../../experiments/agent_design/2026-10-07-official-product-links-v1/nvidia-ai-enterprise.json)。这里只补充一个产品的两个官方入口和两条建议，不代表 NVIDIA 全产品覆盖。它绑定选定 FY2025 图，网页内容属于独立核对时刻。

展示适配：[build_view.py](../../../experiments/agent_design/2026-10-07-agent-business-revenue-v1/build_view.py)。启用时显式传入补充文件；省略时保留原行为。保留原执行和冻结产物，只更新派生验收展示。
