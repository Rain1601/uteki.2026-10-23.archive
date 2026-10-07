# 离线核心回归 / Offline checks

新检出仓库可以验证已提交代码的核心契约。完整历史回归还需要原开发环境的资料库、研究数据和不可变实验记录，两者使用不同入口模式。

**核心回归通过不代表 Alphabet 完整研究报告、资料库或证据质量已经验收。** 核心测试使用内存样例、临时目录、已提交的 v0.1 benchmark 和来源节选；实际研究资料与历史实验的覆盖范围见下文。

## 环境与命令

要求 Python 3.11+、macOS 或 Linux，以及可通过 `node` 运行的 Node.js 20+。现有存储测试使用 POSIX 文件锁和 `multiprocessing` 的 `fork` 模式；本入口没有承诺 Windows 支持。

先在仓库根目录安装锁定的 Python 依赖：

```bash
uv sync --locked --extra analysis
```

安装依赖可能需要联网。完成安装后，检查本身不下载资料、不调用模型、不需要 API 密钥，也不执行依赖同步：

```bash
.venv/bin/python scripts/run_offline_checks.py
```

`analysis` 虽是应用的可选依赖，但本套测试需要它：报告编译、引用校验、假模型修复、调用计费和预算测试会导入 Agents SDK / Pydantic。测试使用 fake runner、fake model 或显式 patch；安装 SDK 不会授权真实模型调用。入口同时设置 `OPENAI_AGENTS_DISABLE_TRACING=1`。缺依赖会产生导入错误并返回非零，不会自动缩小测试范围。

入口始终以脚本所在仓库为工作目录，不要求调用者预设 `PYTHONPATH`。也可以从其他目录用虚拟环境解释器和脚本的绝对路径调用。

```bash
.venv/bin/python scripts/run_offline_checks.py --list
.venv/bin/python scripts/run_offline_checks.py --verbose
```

`--list` 不导入测试或运行检查，显示完整 Python 选择器、所有保留给集成模式的范围和理由，以及 JavaScript 文件。维护清单在 [`scripts/run_offline_checks.py`](../scripts/run_offline_checks.py) 的 `CORE_TESTS`、`LOCAL_DATA_TESTS` 和 `JAVASCRIPT_TESTS`。

Python 与 JavaScript 都必须通过。Python 失败后仍运行独立的 JavaScript 检查，最终显示各自的退出状态；任一失败、导入出错或找不到 Node.js，整个命令均返回非零。输出是原始测试报告，不会把错误转换为成功或因缺数据临时跳过测试。

## 核心范围

除下表注明的混合文件外，入口按完整模块运行；因此这些模块以后增加的方法也会自动执行。

| 范围 | 核心覆盖 |
| --- | --- |
| Evaluator | 契约错误、确定性评测和输出 |
| Business Map | fake model 公共接口、实际输入范围与指纹、章节/全文选择、完整提示结构、失败日志、模型响应与人工状态边界；不评价真实模型质量 |
| M0 来源与待审包 | 新快照完整性、图片覆盖与追踪像素显式排除、不可覆盖发布、旧材料审计、独立迁移重放、伪造审批拒绝 |
| SEC 解析与索引 | 可见正文、目录锚点、法定层级、表格/图片/页码、合并单元格和嵌套内容，以及新版来源完整验证、图片相对路径与不可覆盖发布 |
| 阅读上下文 | 跨页列表边界、避免错误合并、复合正文不作为列表 |
| 研究存储与修订 | candidate/review/adopt 生命周期、原报告不变、来源保留、并发/版本冲突、跨进程采纳锁 |
| 研究上下文 | 发布时间边界、历史白名单、前两年年报基线、缺年显式表示、快照冻结、不同 researcher 隔离 |
| 人工反馈 | 批注偏移/hash 校验、评论版本、撤回、未采纳反馈不进入年度基线 |
| 报告生成契约 | 引用必须实际读取、事实需引用、结构验证、单次修复上限、修复前后输出保留、禁止自动采纳 |
| 数字与成本 | 严格数值解析、引用范围内百分比审核、失败计费记录、并发预算和失败关闭 |
| 展示层契约 | 既有双语/引用显示、内容转义、报告修订展示、注意力模型、主题隔离和旧路由重定向；不是浏览器视觉验收 |
| 离线流程 smoke | 已提交材料子集的可定位性与临时存储中的修订/审核/采纳流程，具体限制以 smoke 输出为准 |
| 工作区诊断 | 缺失/损坏输入明确报告、启动前检查、核心与可选资料区分，以及保持真实名单/数据不变 |
| 私密状态迁移 | 合成归档的内容 hash、`.env*` 排除、600 文件权限、空目录保存与逐级 700 目录恢复、冲突不覆盖、路径/符号链接拒绝、重复目标与文件目录冲突检测；不上传归档 |
| 检查入口 | 失败传播、缺运行时、仓库目录定位与跨目录调用 |
| JavaScript | `revision_demo.test.cjs`、`agent_runs.test.cjs`、`agent_results.test.cjs`；包括不可变修订、显式采纳、旧候选拒绝、时间边界及 Agent 运行/结果页面契约 |

2026-10-08 起，默认核心入口另含 13 个 Agent 与解析测试模块：来源提及覆盖及审计 v1/v2、批量诊断、失败恢复与单轮续跑、引用索引投影、粒度阶段、独立批评、对象补丁、有界网络重试、HTML 10-K 结构覆盖和获取目录覆盖。它们使用合成来源、临时目录和 MockTransport，验证共享账本与未知费用保留、来源绑定、原始产物不变及“候选不等于语义通过”等边界；无需历史运行目录或 API 密钥，不代表真实模型质量已验收。

目前 smoke 默认只校验 `alphabet-definition → e-overview → paragraph 55` 这一条链。已提交节选的第 90 段重算 hash 与记录值不一致，smoke 会报告该范围外问题；`scripts/smoke_research_workflow.py --strict-all` 将返回非零。核心中的对应测试验证“能发现这个问题”，不会把真实节选修成通过，也不表示全集完整性通过。

2026-09-18 新建的 M0 包已从官方完整文件重新导出摘录，并保留旧摘录的空白差异。其真实数据重放与上述旧 smoke 分开：

```bash
.venv/bin/python scripts/prepare_m0_review.py --verify data/evaluation/m0_r2a/2026-09-18-candidate
```

这个命令重新核验包内完整来源、历史输入、全部证据和机械派生产物；不调用模型，不代替语义审核。真实来源、索引和新目录重建的记录见 [R2-A 执行记录](releases/V0_2_R2A_EXECUTION.zh-CN.md)。

以下文件同时包含可移植单元测试和真实资料回归，所以使用明确的类或方法选择器；未选中的方法仍由 `--integration` 执行：

| 混合文件（位于 `tests/unit/`） | 核心包含 | 集成模式另含 |
| --- | --- | --- |
| `test_sec_document_index.py` | `SecDocumentIndexUnitTests` 全类 | `AlphabetDocumentIndexIntegrationTests`，需要冻结源文件及索引 |
| `test_business_map_models.py` | 两项内存契约、已提交 pilot 与 v0.1 benchmark | 未分发的 v0.2/v0.3 candidates |
| `test_reading_annotations.py` | `ReadingAnnotationTests` 全类 | `AnnotationRoutesTests` 及其继承的真实资料路由测试 |
| `test_research_archive_routes.py` | 旧路由重定向 | 真实导入、目录、材料、报告和 API 路由；即使“空上下文”测试也需要 catalog |
| `test_reading_groups.py` | 列表边界、无关正文不合并 | 真实 Alphabet 竞争列表 |
| `test_context_regression.py` | 复合正文不是列表 | 已记录工具调用和多版本源索引 |
| `test_evidence_math.py` | 严格数值单元格解析 | 真实 Alphabet 营收及 Cloud 增长计算 |
| `test_nested_source_blocks.py` | 内存 HTML 表格前后正文保留 | 实际季度文件及索引边界 |
| `test_numeric_review.py` | 引用范围与失败计算 | 历史 annual-narrative 百分比回归 |

## 完整本地回归 / Local integration

准备好原始资料后运行：

```bash
.venv/bin/python scripts/run_offline_checks.py --integration
```

此模式直接执行 `python -m unittest discover -s tests -t .`，随后运行同一组 JavaScript 检查。**它包含核心与历史集成测试，不是网络模型运行入口。** 原测试和断言不变，新检出仓库缺资料时预期返回非零。以下内容尚未由公开仓库完整提供：

| 数据/产物 | 主要受影响的测试模块 |
| --- | --- |
| `data/company_universe/` 中原 50 公司名单 | `test_company_universe`、workbench 与档案路由 |
| `data/document_library/`、`data/reading_library/`、完整 `data/source_documents/` | company data、document library/reader、earnings materials、索引与 reading groups |
| `data/research_data/` 和 v0.2/v0.3 Business Map / Cloud benchmarks | research data、review workbench、cloud spike / LLM / analysis / recovery |
| `experiments/document_reader/` 的清单与调用记录 | analysis comparison、context regression、document reader |
| `experiments/analysis_comparison/` 的冻结年度/季度报告、读取日志和校验信息 | codex hypothesis MVP、annual report view、numeric review |
| `experiments/cloud_analysis/` 等历史运行及审核文件 | cloud analysis、cloud recovery、archive import/routes |

不能通过生成同名占位资料来使这些回归通过；需恢复测试实际引用的版本与来源。完整套件仍保留原测试自身的两个跳过条件：analysis comparison 缺 SDK、numeric review 缺不可变本地实验。入口没有新增跳过逻辑。正确安装 `analysis` 后，前者不会触发；后者可能显示为 skipped，应与错误/失败一起阅读，不能据此认定完整历史实验已验收。

以后新增测试时，先判断它依赖的是已提交样例/临时目录还是外部本地资料，再更新明确清单及说明。不要用“运行后删除失败项”的方式维护核心范围，也不要用这条较小的核心命令替代需要真实材料时的完整回归。
