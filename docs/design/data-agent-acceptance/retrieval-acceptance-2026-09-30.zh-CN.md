# 召回验收与资料发现边界

日期：2026-09-30。范围：冻结 Alphabet FY2025 10-K 中的现金流与资本支出问题；另核对公司、期间、材料类型与跨公司查询接口。本文记录代码和真实产物，不是新的功能已经实现的声明。

## 1. 原运行的内容验收

**限定问题的内容与溯源通过 Codex 辅助复核；执行效率存在不足。用户人工签收未记录。**

| 验收点 | 实际证据 | 结论 |
| --- | --- | --- |
| 搜索定位 | Item 7 内搜索 `capital expenditures` 返回 7 处预览 | 定位成功；预览不计正文已读 |
| 完整类别交付 | 第 23 步从 block 614 读 8 块；下一次模型输入中保留了 614 引导句、615 技术设施、616 办公设施全文 | 完整交付两类及子项 |
| 原件一致 | 5 处引文均在所引原文块中；按 DOM path 回读原始 HTML，规范空白后与引文涉及的 4 块相同 | 不仅是 JSON 内部一致 |
| 内容限定 | `primarily`；类别不限定单一年度；2024/2025 数字为 actual；2026 为 forward-looking | 未丢失主要限定语，未推断 AI 回报 |
| 相邻内容 | 617 为在建及尚未投用资产；618 后半为折旧；619 起为租赁 | 对本题主要用途无必需遗漏；资本负担/回报问题须另纳入 |
| 财务表分散证据 | 第 10–12 步分页交付 p52 表格全文；用途来自 p38 | 原问题跨表格/段落证据齐全 |
| 执行效率 | 读取无关税法段；重复读取现金流表；一次 artifact 分页只拿到 block_id | 效率未通过，不能用内容正确掩盖 |

本轮按现有工具重新执行原搜索、原读操作，结果与冻结反馈一致。复现及逐引文结果见 [literal-probe-results-v1.json](../../../experiments/architecture_baseline/2026-09-30-retrieval-acceptance-v1/literal-probe-results-v1.json)。独立历史 Data Reviewer 对 3 条叙述均判 supported；本轮复核不改写其冻结意见。

## 2. 搜索工具面对不同措辞

下表为同一 Item 7 内的真实工具调用，关键词由验收者选择，**不是模型自行规划的表现**。

| 搜索词 | 命中块数 | 解释 |
| --- | ---: | --- |
| capital expenditures | 7 | 原运行关键词 |
| CAPITAL EXPENDITURES | 7 | 忽略大小写 |
| capex | 0 | 不自动扩展缩写 |
| capital spending | 0 | 不自动扩展同义词 |
| 资本支出 | 0 | 不自动翻译 |
| technical infrastructure | 17 | 精确出现的另一种文字 |
| office facilities | 1 | 直接定位第二类用途 |
| property and equipment | 7 | 另一组原文短语 |

0 命中均返回 `no_literal_match`，同时 `not_disclosed=false`。没有把“关键词没找到”写成“公司未披露”。读取单个列表项 615 时，工具按结构规则扩展到 614–616，保持引导句和完整列表。

这个测试证明当前工具是字面搜索，也暴露对模型选词及补读的依赖。它不是统计召回率、语义检索或跨公司能力测试。

## 3. 改写问法的真实模型验收

使用相同公开原文、数据集、公司/来源范围、截止日、模型、共享账本及步骤限制。问题改写为“日常经营带来多少净现金”“购置物业和设备实际付出了多少现金”“这些长期实物资产的投入主要花在哪些类别”，不提供页码、关键词、预期类别或标准答案。仍要求 Worker 核对 PPE 金额，主角色独立核对。

- [明确输入配置](../../../experiments/architecture_baseline/2026-09-30-retrieval-acceptance-v1/paraphrase-config-v1.json)
- [运行入口](../../../experiments/architecture_baseline/2026-09-30-retrieval-acceptance-v1/run_query_review.py)：只执行 Data 与 Data Reviewer；不调用 Analysis，不发布。
- [首次运行](../../../experiments/architecture_baseline/2026-09-30-retrieval-acceptance-v1/paraphrase-01/result.json)：第一步两次传输尝试均为 `APIConnectionError`，没有模型决策；费用未知，保留在原共享账本，不按零费用处理。
- 网络权限放行后的[第二次运行](../../../experiments/architecture_baseline/2026-09-30-retrieval-acceptance-v1/paraphrase-02/data-query/query/result.json)为 `limited / no_progress_limit`：主角色作出 4 次真实模型决策，Worker 未运行，没有开始正文搜索。改写问法端到端验收未通过。

失败定位：第 2 步模型已正确提出 2024、2025 全年指标查询，宿主却拒绝为 `plan period is not explicitly grounded in the question`。独立调用当前 `explicit_periods()` 复现：原问法识别 2024 与 2025；改写问法只识别由 FY2025 映射出的 2025，漏掉“2024 和 2025 两个完整年度”中的 2024。第 3 步又出现 requirement 字段组合错误，第 4 步引用尚未建立的 requirement ID，最终触发无进展终止。

这是**自然语言期间解析及错误恢复缺口**，不是已经证明模型找不到同义词，也不是正文搜索漏掉事实。[期间解析复现](../../../experiments/architecture_baseline/2026-09-30-retrieval-acceptance-v1/period-grounding-replay-v1.json)。不通过给问题补回特定关键词掩盖这个失败；冻结失败输入、响应和费用记录均保留。

最终 [Data Reviewer](../../../experiments/architecture_baseline/2026-09-30-retrieval-acceptance-v1/paraphrase-02/data-review/response.json)判定 `question_coverage=incomplete`，整体 `needs_revision`，理由是未建立计划、无候选事实或需求可审。首次审阅传输超时后，最后一次配置内重试返回；未进入 Analysis。新增实验合计 8 次请求尝试（2 次初始连接失败、4 次主角色、2 次 Reviewer），其中 3 次费用未知；已知估算合计 $0.801735，不是供应商账单。

附带执行缺口：在无候选事实可审时，实验入口仍构造全文审阅请求。应增加明确的前置检查，直接报告缺计划/缺候选，避免把无法完成的审阅交给模型消耗时间和费用。

## 4. 公司和材料越来越多时，现状是什么

必须区分：**schema 是字段与类型说明；catalog 是当前范围中有哪些资料；outline 是某份资料的章节；search 是指定资料中的短语匹配结果。** 当前没有提前生成“每个段落可以回答哪些问题”的问答索引。

| 用户需要 | 当前实现 | 尚缺部分 |
| --- | --- | --- |
| 股票代码找公司 | 准备入口接受 symbol + market，通过 SEC ticker 精确映射 CIK，并核验主体 | 自然语言到受控公司身份的解析 |
| 中文/英文名称、别名 | manifest 保存公司名称、代码、CIK、市场 | 中文名/简称/历史名别名表、歧义处理；不能把模型猜中的代码视作验收 |
| 年份与截止日 | 资料有 period_end、available_at；指标有期间起止；可显式选择年报报告期末 | 财年/自然年/披露年意图解析，跨公司期间对齐 |
| 10-K/10-Q/8-K | 来源保存 form；获取器支持最新年报及随后季报/8-K、修订和附件；也可取指定报告期末的年报 | 任意季度/事件查询协议、8-K 专用语义验收 |
| 按材料类型查正文 | `DocumentRequest` 支持 company_id + form + period_end + phrase；form 目前为 10-K/10-Q/EARNINGS_CALL | 旧接口不接受 8-K；新 search_source 可读已选且有索引的 8-K，但不负责跨库找出它 |
| 行业找公司 | 本 Data Agent 目录无行业筛选 | 有来源、版本、生效时间的行业分类及成员；研究主题组需单独标识 |
| 多公司对比 | ExecutionScope 可表达最多 16 公司、64 来源；每个公司必须有明确来源 | 一次查询仍打开一个 dataset。当前公司准备按公司产出；跨 dataset 路由、分别取证及可比性对齐未接通 |

当前验收库中的公司是 `sec-0001652044 / Alphabet Inc. / GOOGL / NASDAQ`，有 2025-12-31 10-K 和 2025-09-30 10-Q。实际本题 scope 只开放前者；材料存在于库中不等于自动进入问题范围。[实际目录检查](../../../experiments/architecture_baseline/2026-09-30-retrieval-acceptance-v1/discovery-audit-v1.json)

来源的年报期间为 2025-12-31，可得日为 2026-02-05，二者不可合并成一个“年份”。目录条目的 period_end 也不代表正文只含该年数字；本年报含 2024 的比较数。

存储方面，本题 dataset 下保存 `raw/` 原件、`indexes/<source>/index.json` 和 `blocks.jsonl`、候选 records/evidence JSON、`research.duckdb` 查询库、manifest 哈希。原件与快照可追溯；目前并非一个全公司、全材料的统一查询入口。

规模边界：目录有分页，模型可按小页读取，但 `_view` 仍先读取范围内候选行并构建元数据；DocumentReader 加载整份原文块，搜索时按块线性匹配。未做两倍/多倍材料的时延与内存压测，不能给出容量承诺。扩大公司列表不会自动补出跨库检索或行业范围。

## 5. 下一步建议，尚未实施

1. 先补可核验的公司主数据及统一资料目录：别名到公司 ID，财年/披露日/form 到材料 ID；先返回明确覆盖和缺口。
2. 再做显式多公司取证与对比：分别检索，各自保留证据；对齐财年、单位、会计口径后比较，不能先合成一段摘要。
3. 用户后续明确：行业问题暂缓展开；按公司 tag 预留，查询可携带 company_list 或行业列表，标签筛选后解析为明确公司集合。可参考 TradingView 分类，接入尚未实现；不继续要求用户选择行业分类方案。向量检索本身不能替代身份与范围解析。

验收例：名称歧义不猜；不存在的期间明确缺资料；10-K/10-Q/8-K及附件可准确筛选；跨公司不串证据；跨财年比较有明确对齐规则。以上是建议目标，不冒充当前实现。
