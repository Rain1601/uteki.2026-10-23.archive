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
