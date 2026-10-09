# Uteki Beta

基于原件证据的投资研究系统。当前维护两个本地入口：

| 入口 | 地址 | 当前范围 |
|---|---|---|
| 数据与 Agent 结果工作台 | <http://127.0.0.1:8765/> | 原件、冻结候选、引用、查询过程与审核状态；首页跳转当前结果 |
| 投资界面 Swiss C | <http://127.0.0.1:8769/docs/design/company-workspace-swiss-c/> | 已命名的模拟公司/报告/组合/风险；尚未连接真实发布 API |
| Data 验收结果 | <http://127.0.0.1:8769/docs/design/data-agent-acceptance/e1-evidence-benchmark-v3/> | 双年度七题阶段结果、出处、缺失/多余与费用 |

2026-10-09：E2季度收入、E3混合收入/版本重列及E4现金流/新公司地理收入指定题已通过独立内容验收与最终双审，R15/R16历史消费兼容与期间误拒已修。**当前下一项E5：冻结多公司问题及各公司独立范围/覆盖。** 最新结果从[E2](experiments/agent_design/2026-10-09-e2-msft-10q-v1/DELIVERY.zh-CN.md)、[E3](experiments/agent_design/2026-10-09-e3-mixed-sources-v1/DELIVERY.zh-CN.md)、[E4](experiments/agent_design/2026-10-09-e4-heldout-v1/DELIVERY.zh-CN.md)进入；尚未接入专用结果页。

Data 的真实流程、G0–G4 关口、逐题标准及 E1–E7 扩展状态已[统一](docs/DATA_AGENT_EVIDENCE_ACCEPTANCE.zh-CN.md)。两公司 FY2025 六题及 E1 七题有通过的独立内容验收；部分含恢复/补审，不是同一版本从零一次通过。完整财务、任意公司/格式、严格最小材料及稳定泛化仍未证明。Data 交材料，Analysis 的报告/图另验。

## 启动与检查

已有环境从仓库根目录启动（首次安装见[本地开发](docs/LOCAL_DEVELOPMENT.md)）：

```bash
PYTHONPATH=src:. .venv/bin/python -m apps.review_workbench.app --host 127.0.0.1 --port 8765
.venv/bin/python -m http.server 8769 --bind 127.0.0.1
```

两个服务分别运行。只读预检及核心离线检查：

```bash
PYTHONPATH=src:. .venv/bin/python -m apps.review_workbench.app --check
.venv/bin/python scripts/run_offline_checks.py
```

Python 3.11+、Node.js 20+；按锁文件安装 analysis/data/mcp 所需依赖。核心检查不调用模型；完整历史集成另见[测试边界](docs/OFFLINE_TESTS.md)，当前不能宣称全部通过。

## 当前入口与保留规则

- [当前行动与完整精简路线](TODO.md)
- [统一 Data 流程与验收](docs/DATA_AGENT_EVIDENCE_ACCEPTANCE.zh-CN.md) · [原 01–16 状态](docs/DATA_AGENT_EXTRACTION_TODO.zh-CN.md)
- [两公司六题](docs/design/data-agent-acceptance/data-agent-evidence-v1/) · [E1 七题](docs/design/data-agent-acceptance/e1-evidence-benchmark-v3/) · [单题模型对照](docs/design/data-agent-acceptance/e1-model-comparison-v1/)
- [CLI](docs/DATA_AGENT_CLI.zh-CN.md) · [只读 MCP](docs/DATA_AGENT_MCP.zh-CN.md) · [代码总览](docs/CODE_OVERVIEW.zh-CN.md)
- [备份、瘦身清单与恢复](docs/REPOSITORY_RETENTION.zh-CN.md) · [换机接续](docs/MACHINE_HANDOFF.zh-CN.md)
- [Agent 职责](docs/AGENT_SYSTEM_DESIGN.zh-CN.md) · [投资与评测约定](docs/INVESTMENT_EVALUATION_CHARTER.zh-CN.md)

历史实验与旧页面按依赖清理，清理前完整提交保存在本地 `codex/backup-20261009-before-cleanup`。冻结原件、当前结果和测试依赖保留；备份未推送。旧文档的归档路径需恢复后访问。

代码、公开材料与普通配置随 Git；凭据、私密会话、联系人设置、费用账本及机器缓存单独保留。AMD/TSMC 历史准备 manifest 的私密 source-config 未随仓库交付，不能声称仅靠 checkout 可完整重放所有历史结果。不修改冻结 hash 掩盖缺件。

数据注册与只读 MCP 使用显式冻结范围；缺输入报错，不替换公司、期间或来源。获取 SEC 原件需自行配置私密联系信息。E1 原账本缺件，不能恢复调用或清零历史费用。E2–E4原共享账本累计176请求、保守估算$2.0569908，unknown/在途0，$3硬上限未提高；原账本须私密迁移。本次整理提交未调用模型。
