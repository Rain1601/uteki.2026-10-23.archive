# 项目进度与 OpenSpec 命令

OpenSpec 管理新增变更的 proposal → specs/design → tasks → review/archive；项目盘点命令补充现有 TODO、Git 和文档声明。两者共同提供复核依据，不能自动判定研究验收。本轮接入终端命令，没有生成聊天 slash commands 或全局配置。

## 使用

首次安装需要 Node >= 20.19、npm 和 Python >= 3.11：

```bash
npm ci --ignore-scripts --no-audit --no-fund
npm run progress -- --limit 5
npm run --silent progress -- --json
npm run progress -- --check-links
npm run spec:list -- --json
npm run spec:list -- --specs --json
npm run spec:status -- --change add-project-progress-check --json
npm run spec:tasks -- --change add-project-progress-check --json
npm run spec:check
```

`progress` 只读、本地运行，不调用模型或测试，不联网刷新 Git。`--json` 需配 `npm run --silent` 才是纯 JSON。也可直接执行 `python3 scripts/check_project_progress.py --json`，无须安装 Node 依赖。默认退出 0 只表示盘点完成；`--check-links` 遇 TODO 缺失或本地链接缺失/越界退出 1，输入或 Git 错误退出 2。不验证链接锚点、内容充分性和外部 URL。

| 命令 | 回答的问题 | 不能推导 |
| --- | --- | --- |
| `progress` | 当前提交、工作树、TODO 勾选、规范标题/显式状态、TODO 本地链接是否存在 | 功能实现程度、研究验收、最新远端状态 |
| `spec:list` | 在途 change 或 `--specs` 已沉淀规范有哪些 | 没有规范的旧能力不存在 |
| `spec:show -- <id> --type change` | 某项变更声明了什么 | 声明已经实现 |
| `spec:status` | proposal/spec/design/tasks 文件是否齐全 | 任务已完成 |
| `spec:tasks` | tasks 勾选进度及下一步指引 | 勾选已经过独立验证 |
| `spec:check` | 格式、需求/场景及 delta 结构是否有效 | 测试、实现或语义正确 |

实际观察：本次任务尚有未勾选项时，`spec:status` 已返回 `isComplete: true`，并提示这是 planning artifacts 齐全。因此必须结合 `spec:tasks` 和实际验证证据阅读。

## 复核步骤

1. 执行 `progress`，打开相关 TODO 行和方案原文，再看对应 Git diff；提交标题只作线索。
2. 使用 `spec:list/status/tasks/show` 读取相关需求、场景和任务。对当前范围逐条给出：声明、代码/运行证据、未完成项、人工复核点。
3. 对有疑问的行为跑定向测试或读取已有运行记录，注明对应版本。未跑的检查标为未验证；不能直接使用旧测试总数。
4. 经复核后更新 tasks 和 TODO 的对应项。规范只随着实际变更逐步加入，不把旧路线图整体转换成完成声明。

新变更：`npm run spec:new -- <change-name>`；随后用 `npm run spec:instructions -- proposal --change <change-name>` 获取官方模板指引。产物写入 `openspec/changes/<change-name>/`。归档用官方 CLI，但先完成对应实现和验证；归档不会自动批准来源、Gold 或研究结果。

## 当前盘点与验证（2026-09-24）

- 基线 `217e173`：Watch 方案明确“提案，未实现”；`c07804c` 为 Data Agent 工程交付。独立 Analysis Agent 未接入，详见 TODO。
- 已修正 TODO 中 Opus ID 尚未确定的旧描述；一次连接失败不构成能力验证。
- 6 项临时仓库定向测试通过；真实仓库盘点与链接检查通过；OpenSpec 严格校验通过。未运行模型或全量回归。
- 当前只登记 `add-project-progress-check`，保持未归档以便 review；OpenSpec 尚未覆盖全部历史能力。
- 扫描范围：TODO、docs 下文件名含 PLAN/SCOPE/ROADMAP 的 Markdown、openspec/specs 与 changes。只抽取显式状态，不理解全部自然语言冲突；进度结论仍由复核人结合代码与证据得出。

## 选型依据

核验官方源码 `db2309783547a14e150dbcbfc19120e4028446c3`，npm 固定 `@fission-ai/openspec@1.13.2`，锁文件记录依赖完整性。npm 的 spec 命令关闭可选遥测。

- [官方 CLI 说明](https://github.com/Fission-AI/OpenSpec/blob/db2309783547a14e150dbcbfc19120e4028446c3/docs/cli.md)：status、validate、instructions 的职责。
- [存量项目接入](https://github.com/Fission-AI/OpenSpec/blob/db2309783547a14e150dbcbfc19120e4028446c3/docs/existing-projects.md)：从下一项真实变更开始，不先补全全库规范。
- [官方 verify 工作流](https://github.com/Fission-AI/OpenSpec/blob/db2309783547a14e150dbcbfc19120e4028446c3/src/core/templates/workflows/verify-change.ts)：由 Agent 检查完整性、正确性和设计一致性；不同于 CLI 结构校验，也不能代替研究验收。
