# Data Agent 独立取材闭环 · 2026-10-09

本轮终点是相关原文、结构化记录、精确引用和复核记录组成的 **Data 证据包**。系统 Agent 自行查目录、生成取数条件、读取和选择材料；Codex 负责实现、测试与独立检查。本轮不调用 Analysis 生成报告，不接入 PageIndex 服务。原六题及一次目录分页针对性复跑均已独立核验通过；完整边界与费用见 [交付说明](DELIVERY.zh-CN.md)。

范围固定为仓库内的 Microsoft、Alphabet FY2025 HTML 10-K。准备层使用程序解析 HTML / inline XBRL；查询决策和内容复核使用 AIHubMix 的 Sonnet 5.5。具体边界见 [运行说明](../../../docs/DATA_QUERY_ANALYSIS_BOUNDARY.zh-CN.md)、[验收标准](../../../docs/DATA_AGENT_EVIDENCE_ACCEPTANCE.zh-CN.md)、[本轮计划](PLAN.zh-CN.md)。

## 六题配置只生成一次，每题独立运行

[cases.json](cases.json) 只包含问题和公司，不包含答案或预选原文。`configs-v3` 是本轮模型设置模板，不是换机后可直接执行的配置。

| case_id | 请求材料 |
|---|---|
| msft-business | Microsoft 报告分部及主要业务 |
| googl-business | Alphabet 报告分部及主要业务 |
| msft-revenue | Microsoft FY2025 / FY2024 公司总收入 |
| googl-revenue | Alphabet FY2025 / FY2024 公司总收入 |
| msft-cloud | Microsoft Cloud / Intelligent Cloud / Azure 口径 |
| googl-buyback | Alphabet 回购金额、剩余授权和费用限定 |

在仓库根目录、已安装锁定依赖后执行。先恢复需要延续的私密账本；本机 `.env` 中配置 `AIHUBMIX_API_KEY`，权限为 `600`。检查命令不读取密钥、不请求 API、不写文件。

```sh
PYTHONPATH=src .venv/bin/python experiments/agent_design/2026-10-09-data-agent-completion-v1/make_replay_configs.py \
  --cases experiments/agent_design/2026-10-09-data-agent-completion-v1/cases.json \
  --output-dir "$PWD/workspace/data-replay-configs-local-01" \
  --ledger "$PWD/experiments/agent_design/2026-10-09-data-agent-completion-v1/costs.sqlite" \
  --check-only
```

通过后去掉 `--check-only`，一次生成六份新配置。脚本从自身位置推导本机仓库根目录，验证 `datasets/msft` 和 `datasets/googl` 的冻结 hash、公司、来源、snapshot 和原问题；planner/worker 输出上限为 8192 token，reviewer 为 12000。每次请求允许一次瞬时故障重试，单次请求超时120秒，完整决策超时300秒。六份配置共用显式账本。生成器不清零账本、不继承旧 `initial_query_ref`、不修改旧配置或数据。

先运行一个问题。下面第二条会请求付费 API：

```sh
PYTHONPATH=src .venv/bin/python scripts/run_data_retrieval.py \
  --config workspace/data-replay-configs-local-01/msft-revenue.json \
  --output workspace/data-replay-runs-local-01/msft-revenue --check-only

PYTHONPATH=src .venv/bin/python scripts/run_data_retrieval.py \
  --config workspace/data-replay-configs-local-01/msft-revenue.json \
  --output workspace/data-replay-runs-local-01/msft-revenue
```

其他五题换成表中的 case_id，分别使用尚不存在的输出路径。已有输出不会覆盖；不要因一次失败删除旧运行或重建账本。每题最多三个取材 attempt，复核失败最多新目录再试一次；实际 SDK 重试由冻结模型配置决定。当前授权采用 `record_only`，没有美元硬上限，失败用量与未知费用预留仍保留。未知不能记成零。

## 查看结果和验收

[统一验收页面](http://127.0.0.1:8769/docs/design/data-agent-acceptance/data-agent-evidence-v1/) 显示六题和一次导航复跑；每条可打开最终原文、运行过程和独立评估。[最终显式选择](delivery-suite.json)固定每个 run 与 manifest hash，不自动选择“最新成功”。

- [准备层核查](preparation-review/README.md) 说明原件如何变为可查询的块、表格和记录。
- [runs/](runs/) 保留真实运行；每个已结束目录的 `result.json` 汇总状态，`attempt-*/review-packet.json` 是实际复核输入，`review-*/response.json` 和 `result.json` 保留复核判断。运行中尚无最终 manifest 时不能作为封存验收。
- `reviewed_data_ready` 表示本次程序检查与模型复核通过，不等于用户已确认正确，也不表示其他题通过。失败、limited、耗尽 attempt 的结果同样保留。
- [离线验证记录](validation/focused-regression.txt)、[换机配置验证](validation/replay-config-check.json)、[原件定位验证](validation/registered-source-preview.json) 分别说明工程检查；它们不是新的模型质量实验。

已封存复核可通过 `scripts/render_data_review.py --review-dir ... --review-manifest-sha256 ... --output ...` 生成单题页；六题页使用 `scripts/render_data_retrieval_suite.py --suite <明确的套件JSON> --output <新目录>`。renderer 不请求模型、不猜测“最新成功运行”，必须显式选择结束运行和 manifest hash。原件跳转可使用已登记的 `msft-data-agent-fy2025-v2`、`googl-data-agent-fy2025-v2`，预览端点为 `http://127.0.0.1:8765/data-workspace/source`；字符/单元格 URL 示例见上方定位验证。

**查看成品与重建历史不是一回事。** 已渲染页及其相对路径证据副本可随 Git 换机查看。旧运行、旧 review packet 仍保留原机器的绝对 `query_ref`、`dataset_ref`；当前 renderer 重新核验时会读取这些位置，不能在另一根目录自动重渲染。不要批量替换冻结 JSON 的路径。需要重新执行时生成新配置、新运行；需要阅读历史时优先使用已封存成品和原始记录。

## Git 与本机私密文件的界限

| 随项目提交 | 留在本机并单独迁移 |
|---|---|
| 代码、Skill、cases、普通模型配置、公开财报和冻结 dataset | `.env` / API key：不进 Git、不进迁移包，新机器单独配置 |
| 真实运行的非敏感过程/产物、失败记录、验证记录、验收页 | `costs.sqlite` 及 SQLite sidecar：账本与未知预留完整保留 |
| `evaluation-only` 独立评估材料；不作为生产 Agent 输入 | 私密 Claude 顾问对话、本机观测与含运营身份的获取配置 |

当前 `costs.sqlite*` 已明确忽略；私密转移工具 `scripts/transfer_local_state.py` 从被 Git 忽略的 `data/`、`experiments/`、`.local/claude-dialogues/` 收集文件，仓库外顾问会话要显式传 `--dialogue-root`。**先等模型任务和会话写入停止，再导出新包**；本轮队列已停止，新包位置为 `output/machine-handoff-20261009/private-state-v1.tar.gz`，校验记录同目录 `verification.json`，均不提交 Git。2026-10-08 的旧包不包含本轮新费用，不能用它代表当前状态。

```sh
python3 scripts/transfer_local_state.py create --root "$PWD" \
  --dialogue-root /absolute/path/to/current/private/claude-conversation \
  --output /absolute/private/path/new-state.tar.gz
python3 scripts/transfer_local_state.py verify /absolute/private/path/new-state.tar.gz
```

使用明确的真实会话目录。工具逐文件保存 hash、排除 `.env`，拒绝覆盖不同内容和不安全路径；它不上传文件，也不自动重定位旧运行内的绝对引用。恢复与启动说明见 [换机交接](../../../docs/MACHINE_HANDOFF.zh-CN.md)。迁移包本身通过用户控制的私密渠道传输，不提交 Git。

本轮上传前核查：公共实验目录、两个预览 dataset 副本和现有验收页没有被忽略；新共享账本忽略缺口已补。当前 Git 已跟踪及可加入的文件中未发现单文件达到 50 MiB，因而本次检查没有发现超大单文件阻塞。最终上传前复查记录见 `validation/final-public-file-audit.json`；本轮新私密包只通过用户控制的私密渠道迁移。文件大小检查不代替内容与密钥审查。
