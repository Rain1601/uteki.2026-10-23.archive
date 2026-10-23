# 仓库保留与历史归档

2026-10-09。本次只移除已确认不被活动代码、测试、配置、数据注册及当前结果页依赖的历史实验和旧页面。保留依赖闭包，未追踪/忽略的文件、密钥和原费用账本未删除。

- 清理前本地备份：原为分支 `codex/backup-20261009-before-cleanup`。该提交已在 main 历史中，分支于 2026-10-23 删除，恢复时直接用基线 SHA `a4595ba8`。
- 完整基线：`a4595ba82164f6597db72ee01891f3c2abf7cbf0`。备份未推送；在本机可恢复。
- 移除 **3,729 个受版本管理文件 / 226.51 MiB**，来自 65 个历史目录。
- 清理前 31,579 个跟踪文件，移除比例 11.8%。这降低工作目录文件量；Git 历史对象仍保留，不缩减完整历史克隆体积。
- [精确清单](REPOSITORY_ARCHIVE.v1.json)记录每个文件的路径、大小、SHA256 和备份提交。删除前逐个确认 Git 对象与备份一致。

保留：源码、脚本、测试、配置、数据注册、Swiss C、当前六题/E1 页面、completion/E1 冻结材料及传递依赖。部分大型旧实验是测试 fixture 的来源，不能因为日期旧就删除。历史业务图与市场回测可从备份恢复；它们的原始结果、失败和修订史在备份中完整保留。

流程和标准只维护在统一验收（已归档：`docs/DATA_AGENT_EVIDENCE_ACCEPTANCE.zh-CN.md`，恢复方法见[归档说明](REPOSITORY_RETENTION.zh-CN.md)）。旧复盘/代码总览文档保留为短入口；主 TODO 只呈现当前队列。其他历史说明中的归档路径需先恢复再访问，不代表当前运行入口。

只读查看旧文件：

```bash
git show a4595ba8:TODO.md
```

按需恢复一个归档目录（替换示例路径；先确认不会覆盖当前改动）：

```bash
git restore --source=a4595ba8 -- experiments/market_backtests
```

C2清理阶段验收（后续工程和当前提交核验见交接（已归档：`docs/MACHINE_HANDOFF.zh-CN.md`，恢复方法见[归档说明](REPOSITORY_RETENTION.zh-CN.md)））：

- 核心离线：562 项 Python 与 35 项 JavaScript 检查通过；不是新模型评测。
- 当前 Swiss C、六题与所有 e1-* 页面的 2,622 个本地链接目标均存在，零新增缺链。
- 工作台启动预检：基础输入就绪；保留原有 Alphabet review_excerpt 第90段 hash 不一致缺口，未重写原件/历史摘录消除告警。
- 工作台首页、结果/过程入口、Swiss C、六题、E1七题与模型对照：7 个 HTTP 请求均返回200；首页跳转 /agent-results。
- 两个本地服务运行于 127.0.0.1:8765 和 :8769。服务重启命令见 README；浏览器视觉审阅未执行。
- git diff --check 通过。修改仅为当前文档/归档清单和核对过的历史删除，未改源码、配置、冻结数据或当前结果页。

完整历史集成集上次仍有已记录失败，不宣称全部通过。未新增模型调用，未重置费用，未重写历史。此处为清理阶段记录；当前清理随本轮代码本地提交，备份分支保留本机，未推送。

## 2026-10-12：03-M3 重建时的可再生缓存清理

本轮仅清理未追踪的 Python 字节码和 OCR 安装下载归档，共 217,950,626 B（约 207.85 MiB）：586 个字节码文件、53 个空缓存目录、24 个 conda 安装包及一个 micromamba 下载包。安装包删除前与公开的 SHA256 显式锁逐项核对；安装后的 Tesseract / eng 和可复用管理器仍保留，实际版本命令通过。

原图、数据集、所有失败/修订记录、费用账本、旧迁移包和其他任务改动均保留。三个逐文件清单位于本机私密 `output/m3-recovery-20261012/`：`cache-cleanup-manifest.json`、`ocr-download-cleanup.v1.json`、`ocr-package-cache-cleanup.v1.json`。这次清理不删 Git 历史，不声称恢复已丢失的另一机器原包。

## 2026-10-13：单一设计入口

`DATA_AGENT_FRAMEWORK_DESIGN.zh-CN.md` 是唯一核心顶层设计。README/TODO 已收敛，AGENTS 保留当前协作与工程边界；专项资料按需读取，不代表当前并行任务。

本轮从 docs 顶层移除 48 份无保留文件引用的旧说明，顶层 Markdown 从 104 份降为 56 份。代码/测试/配置/Skill、历史结果及核心设计仍引用的文档保留；没有把“旧”直接等同“无用”。已有未提交改动保留，原件、结果、冻结契约和费用账本未改。

48 份原文和 README/TODO/两份 AGENTS 的修改前快照共 52 份，已逐一验证与清理前 Git 提交 `e6366df56c7c005499b2ef222fafe3bf406a3794` 的内容完全一致；路径、字节数、SHA256 及恢复提交见清单（已归档：`docs/archives/context-cleanup-2026-10-13.json`，恢复方法见[归档说明](REPOSITORY_RETENTION.zh-CN.md)）。旧文档仍可从该历史版本跨机器恢复，内部相对链接需恢复到原路径后使用；归档材料不默认搜索/加载。

原始压缩包 `docs/archives/context-cleanup-2026-10-13.tar.gz` 保持原始字节并留存本地。提交检查发现其中旧说明含机器路径，因此该压缩包被忽略、不随本次 Git 交付；没有改写原文或原有 Git 历史。换机器查看旧文档使用上述历史提交，不依赖本机压缩包。

从仓库根目录只读查看某份原文：

```bash
git show e6366df56c7c005499b2ef222fafe3bf406a3794:docs/EVOLUTION.md
```

需要恢复时先写入单独临时目录，按需替换所选路径，避免覆盖当前改动；浅克隆需先取得该历史提交：

```bash
restore_dir=$(mktemp -d /tmp/uteki-docs-restore.XXXXXX)
git archive e6366df56c7c005499b2ef222fafe3bf406a3794 -- docs/EVOLUTION.md | tar -xf - -C "$restore_dir"
```

本轮无生产功能修改、模型调用或新业务验收；归档不意味着历史问题已解决。下一步继续 review 核心设计。

## 2026-10-14：独立项目迁出与退役目录清理

用户要求清理与 Uteki 无关的内容。按目录用途和实际引用核对后，迁出以下 5 项；没有把名称相似、日期较旧或暂未使用直接作为删除依据。

| 原路径 | 清理依据 |
| --- | --- |
| `apps/attention-game/` | 独立注意力小游戏，具有自己的 Git 仓库；Uteki 主仓库未跟踪，也没有运行依赖 |
| `output/editorial-design-kit/` | 已独立维护的设计工具仓库；Uteki 页面使用仓库内的组件，已安装 Skill 也不是指向此目录的符号链接 |
| `output/editorial-design-kit-v0.1.0.zip` | 上述独立工具的导出包，没有活动代码依赖 |
| `docs/research/ida-runtime-reference/` | 本机私有的外部项目源码参考副本，没有导入 Uteki 运行代码；移至仓库外保留 |
| `apps/attention_studio/` | 原 Uteki 首页结构稿已退役，目录只剩一份历史 README，没有运行入口或保留文件的链接依赖 |

共 **656 个文件、2,047,304 B（约 1.95 MiB）**，完整复制到仓库外的本机私密归档 `uteki-cleanup-20261014`，逐文件核对 SHA256、大小、类型和权限后移除原路径。两个独立仓库的 `.git`、小游戏未提交的 `PLAN.md` 修改均完整保留；归档中的 `manifest.json` 记录原相对路径、逐文件清单和清理前工作区状态。该归档仅在本机，不属于公开提交或跨机器备份。

同时移除本机 IDE 中两个已迁出仓库的映射，原配置另存于同一归档。历史文档中当时的路径和记录保留原文，需追溯时从归档恢复到原路径；恢复前检查目标不存在，避免覆盖后续工作。

保留 `review_workbench`、项目专用 `claude_dialogue`、当前前台使用的 `uteki_zero` 模块和 `logo_studio` 原始素材；保留项目内设计组件、品牌探索、全部数据/验收原件、失败和费用记录。清理前已有的 7 份受跟踪文件修改逐一核对未变，当前 SDK 接入工作不受本次操作影响。未运行模型、发布站点或修改 Git 历史。

同日复查 `apps/`，另清理 38 个已确认被 Git 忽略且未跟踪的 Python 字节码文件，共 765,090 B，以及 5 个清空后的 `__pycache__` 目录。这些缓存可由 Python 自动重建，未归入上述原件归档；四个保留应用目录及包入口 `__init__.py` 未改。

## 2026-10-14：旧过程数据本机归档

用户授权为重建整理旧过程数据：先归档至本机 `archive/`，禁止提交归档，再从远程当前版本移除旧数据。此次仅处理以下 6 个目录，不扩大为全部 `data/` 的删除或迁移：

| 原路径 | 归档依据 |
| --- | --- |
| `data/company_workspace/official-filing-preparations/amd-v1/` | 旧解析基线；当前工作台及 MCP 登记使用 v2，原失败和缺口仍保留 |
| `data/company_workspace/official-filing-preparations/tsmc-v1/` | 旧解析基线；当前登记使用 v2，原件及解析结果整包保留 |
| `data/company_workspace/record_review/semantic-quality-v1/` | 已结束的历史语义评测过程；原始响应、失败及账本归档 |
| `data/company_workspace/record_review/semantic-integrity-v2/` | 历史语义协议评测过程；输入、版本、评分与账本归档 |
| `data/company_workspace/record_review/semantic-loop-v3/` | 历史语义循环评测过程；修订、独立评测及累计账本归档 |
| `data/agent_observation/` | 已结束的 7 次旧提取运行事件；保留与原实验 run ID 的对应关系 |

**本机归档：**`archive/data-process-20261014/`，共 **1,281 个文件、84,560,945 B（约 80.6 MiB）**。复制后逐文件校验 SHA256、大小、类型与权限，再移除原目录；归档含 **3 份完整费用账本**，未清零费用或改写失败。归档内 `manifest.json` 保存逐文件清单、原相对路径、清理前 Git 基线及保留数据的哈希，仅留本机，不公开提交。

**Git 范围：**移除 1,269 个已跟踪的旧过程文件；另 12 个原本未跟踪/被忽略的文件一并完整归档。`/archive/` 和上述 6 个原路径加入 `.gitignore`，避免本机归档或后续恢复的过程数据再次进入提交。空的 `data/company_update_sources/` 及其子目录同时移除。远程当前树随清理提交删除旧文件，Git 旧提交与历史不重写；本机归档不等于跨机器备份，也不代表整机磁盘空间已释放。

**保留与恢复：**复数的 `data/agent_observations/` 仍被历史核验脚本直接读取，因此保留；当前工作台/MCP 注册数据、公司名单、原件库、材料包、阅读库和研究状态不变。历史说明中的原路径与原运行记录不改写；需要重放归档案例时，先确认目标不存在，再从本机归档按原相对路径复制回仓库，并按归档清单核对哈希后执行。不要覆盖新工作，归档不将旧失败变成通过。

**核验：**1,281 份归档原件逐文件校验通过，其他保留数据的字节未变，归档文件全部被 Git 忽略；语义基准/评分、数据集页面与 Data Agent 基准的 47 项离线检查通过。本轮不调用模型、不重新获取数据、不修改当前 SDK 接入文件，也不提交其他开发改动。

## 2026-10-14：扩大历史实验与过程产物归档

用户进一步授权清理无当前用途的过程和历史产物。本轮从活动代码、测试、配置、数据登记及当前设计入口反查引用，连同保留实验的脚本与冻结输入检查传递依赖。仅将已退出当前依赖链的历史产物迁入本机 `archive/history-cleanup-20261014/`；旧失败、冻结标准、费用和原件均保留原样。

| 范围 | 文件数 | 内容与处理依据 |
| --- | ---: | --- |
| `experiments/` 的 19 个历史目录 | 2,615 | 早期 DeepSeek 架构/接入试验、旧获取链、DS-03 / E6-R4 / M3 / 收入稳定性试验、阅读器与研究数据候选；无保留代码的执行依赖 |
| `output/` 的 37 项旧产物 | 4,842 | DS-03 / DS-04 原始输出、E6-R4 与 M3 重建记录、三份旧机器交接包、设计截图与诊断记录；配套原件、修订和账本整包保留 |
| 两套旧 benchmark | 7 | `benchmarks/metric_extraction/v0.1/` 与 `benchmarks/data_agent/extraction_ab_v1/`；不再被当前脚本/测试使用，不涉及已登记的同名 data 语料 |
| 旧文档与原型 | 24 | 旧 `PROJECT_CLOSEOUT` / `PROJECT_TASK_REGISTER`，两份退役 Agent 工作台 README，以及 Swiss A/B 原型残留；现用 Swiss C 与产品评审页面保留 |
| 重复规划表与构建脚本 | 6 | `outputs/01a110b1-5b89-71a2-9e33-25b63fd06f2b/planning/`；已被当前唯一 TODO 和核心设计取代 |
| PDF 渲染中间文件 | 12 | `tmp/pdfs/`；正式 PDF 和源材料保留，原有渲染脚本可重新生成临时目录 |

合计 **66 项、7,506 个文件、902,757,386 B（约 860.9 MiB）**，其中 **2,417 个 Git 跟踪文件**、5,089 个未跟踪/忽略文件。先复制，再逐文件校验 SHA256、大小、类型与权限，全部通过后才移除原路径。4 份费用数据库及其历史记录完整归档；清理前另对 24,781 个保留文件记录并复核哈希，未发现变化。归档内 `manifest.json` 保存逐文件清单、原路径、清理前工作区状态与依赖核对记录，仅留本机。

本轮特意保留 E2 的共享账本、E3/E4/E5 与仍用于 E6 的冻结输入、当前登记的 E1/E6 结果和相关核验脚本，以及官方材料库、现用 benchmarks/config、SDK 与新存储代码、当前验收材料、PageIndex 调研证据、OCR 运行环境、品牌源素材和正式 PDF。`company-workspace-v2` 中仍被现用 Logo 来源说明引用的复现入口也保留。没有通过修改测试或冻结记录来消除依赖。

`/archive/` 已整体忽略；本轮退役的跟踪路径另加精确忽略规则，恢复到原位置也不会误提交。此前已验证归档的 `apps/attention_studio/README.md` 删除及独立项目迁出记录一并交付；其他开发改动不进入清理提交。归档只是移出活动目录，不表示本机磁盘空间已释放；Git 历史不重写。

**历史查阅与恢复：**旧文档、历史预检和冻结清单保留原文中的路径，相关链接在恢复前可能不存在。完整原始副本见本机归档；先确认目标不存在，再按原相对路径复制所需项目，并按清单核对哈希与权限。跨机器仅能从清理前提交 `980e52596074b515fc22d9eaa3ff6fa92c6984f1` 恢复当时已跟踪文件，私有运行/账本仍需本机归档；不能把恢复当作新执行授权或重置预算。

**核验：**现有核心离线检查 576 项 Python、37 项 JavaScript 全部通过；阅读器、材料、数据注册/页面、E6 冻结依赖与验收入口的 91 项 Python 回归通过。2,418 个预期 Git 删除逐项一致（含此前迁出的 1 份应用 README），归档及本轮恢复路径全部被忽略；提交新增文字检查未发现机器路径或凭据模式。本轮只做清理与离线检查，不调用模型、不获取新材料、不部署页面。

## 2026-10-23：S2 文档归档

瘦身队列 S2。从活动目录移除 **118 个已跟踪文件 / 3,019,984 B**：docs 根目录 43 份历史设计、计划、报告与交接文档，以及 `docs/research/`（62）、`docs/releases/`（5）、`docs/archives/`（5）、`docs/research_samples/`（2）、`docs/checks/`（1）。移除前确认工作区干净，并逐个确认文件字节与基线提交的 Git 对象一致。

- 基线：`38098480`（已在 origin/main，可从远端恢复，无需本机备份分支）。
- [精确清单](REPOSITORY_ARCHIVE.v2.json)记录每个文件的路径、字节数、SHA256、Git blob，以及保留入口和延后处理项。
- 保留：核心设计、设计历史、接口契约、LOCAL_DEVELOPMENT、OFFLINE_TESTS、FRONTEND_DESIGN、MODEL_COLLABORATION_PROTOCOL、COLLABORATION_FOCUS（`apps/claude_dialogue/service.py` 运行时读取）、本文件与两份归档清单、`docs/design/` 整体。
- 延后：`DATA_AGENT_CLI.zh-CN.md` 随 S3 迁移旧 CLI 处理；`ROADMAP.zh-CN.md`、`PROJECT_PROGRESS_COMMANDS.zh-CN.md`、`docs/schemas/current/` 仍被旧脚本、测试和工作台引用，随 S4 与代码一起归档；`docs/design/data-agent-acceptance/` 也在 S4 处理。
- 被忽略的本机文件（如 `docs/releases/V0_2_R2A_REPLAY*.json`、`docs/archives/*.tar.gz`）不在跟踪范围内，原样保留。

保留文档中指向这些文件的 40 处链接改成“已归档：`<原路径>`”加本节入口。设计历史、两份归档清单和 `data/` 下的冻结证据不改写，其中的旧链接在恢复前会失效。

只读查看或恢复（替换示例路径，先确认不会覆盖当前改动）：

```bash
git show 38098480:docs/MACHINE_HANDOFF_HISTORY_2026-10-12.zh-CN.md
```

```bash
git restore --source=38098480 -- docs/research
```
