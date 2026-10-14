# 仓库保留与历史归档

2026-10-09。本次只移除已确认不被活动代码、测试、配置、数据注册及当前结果页依赖的历史实验和旧页面。保留依赖闭包，未追踪/忽略的文件、密钥和原费用账本未删除。

- 清理前本地备份：`codex/backup-20261009-before-cleanup`。
- 完整基线：`a4595ba82164f6597db72ee01891f3c2abf7cbf0`。备份未推送；在本机可恢复。
- 移除 **3,729 个受版本管理文件 / 226.51 MiB**，来自 65 个历史目录。
- 清理前 31,579 个跟踪文件，移除比例 11.8%。这降低工作目录文件量；Git 历史对象仍保留，不缩减完整历史克隆体积。
- [精确清单](REPOSITORY_ARCHIVE.v1.json)记录每个文件的路径、大小、SHA256 和备份提交。删除前逐个确认 Git 对象与备份一致。

保留：源码、脚本、测试、配置、数据注册、Swiss C、当前六题/E1 页面、completion/E1 冻结材料及传递依赖。部分大型旧实验是测试 fixture 的来源，不能因为日期旧就删除。历史业务图与市场回测可从备份恢复；它们的原始结果、失败和修订史在备份中完整保留。

流程和标准只维护在[统一验收](DATA_AGENT_EVIDENCE_ACCEPTANCE.zh-CN.md)。旧复盘/代码总览文档保留为短入口；主 TODO 只呈现当前队列。其他历史说明中的归档路径需先恢复再访问，不代表当前运行入口。

只读查看旧文件：

```bash
git show codex/backup-20261009-before-cleanup:TODO.md
```

按需恢复一个归档目录（替换示例路径；先确认不会覆盖当前改动）：

```bash
git restore --source=codex/backup-20261009-before-cleanup -- experiments/market_backtests
```

C2清理阶段验收（后续工程和当前提交核验见[交接](MACHINE_HANDOFF.zh-CN.md)）：

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

48 份原文和 README/TODO/两份 AGENTS 的修改前快照共 52 份，已逐一验证与清理前 Git 提交 `e6366df56c7c005499b2ef222fafe3bf406a3794` 的内容完全一致；路径、字节数、SHA256 及恢复提交见[清单](archives/context-cleanup-2026-10-13.json)。旧文档仍可从该历史版本跨机器恢复，内部相对链接需恢复到原路径后使用；归档材料不默认搜索/加载。

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
