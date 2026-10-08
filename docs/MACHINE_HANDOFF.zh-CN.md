# 换机接续开发 · 当前入口 2026-10-09

## 当前：E1 双年材料独立评测与换机交付

最新入口为 [E1计划与状态](../experiments/agent_design/2026-10-09-e1-benchmark-v1/PLAN.zh-CN.md)、[E1阶段报告](../experiments/agent_design/2026-10-09-e1-benchmark-v1/DELIVERY.zh-CN.md) 和 [E1换机重放说明](../experiments/agent_design/2026-10-09-e1-benchmark-v1/README.md)。本轮新增 API 总授权上限为 **$100**，目前在**同一账本分段释放到累计 $40**，不是追加 $40。必须保留失败费用和未知预留。不要沿用下方历史 completion-v1 的无限额度配置，也不要缺账本时新建空额度。

当前只验系统 Data Agent 的材料交付。系统自行查询、读取、选择和复核；Codex 的预期答案与独立评审保留在 `evaluation-only/`，不得作为运行配置、查询输入或选段提示。

换机顺序如下；本节是当前入口，下方两份历史快照仅供追溯。

1. 本轮调用已停止，344笔请求已逐笔核对，0在途；Claude窗口确认空闲后停写导出，再恢复服务。新私密包已生成并通过逐文件校验、本机空目录恢复和E1账本逐字节核对。
2. 新机器检出包含本轮工作的提交，按下方“安装与启动”安装依赖。Git 恢复已跟踪的代码、数据与实验文件；私密包补回被忽略的原件、过程和账本，两者缺一不可。
3. 校验并恢复新包，单独配置本机 `.env`，保持权限 `600`。密钥不随 Git 或迁移包传递。
4. 按 [E1 README 的完整命令](../experiments/agent_design/2026-10-09-e1-benchmark-v1/README.md#换机重新运行一个题) 重建本机配置。先只读检查，再生成新配置；通过运行预检后，才开始一个真实调用。

新包路径为 `output/machine-handoff-20261009-e1/private-state-v1.tar.gz`，权限600，2,434个文件、254个目录、11,711,925字节。SHA-256：`40962ab3307a8b0324929012727fc4353ba3fab9f10fe5ccf5c9b69ae47fb889`。校验记录为同目录 `verification.json`，包和记录均不上传Git。已包含本轮真实 `costs.sqlite` 和显式选定的外部Claude会话。账本已知估算$28.4473026834、未知预留$0.0358508674；未知不能清空。API密钥不包含在包内。此前的2026-10-08包和completion-v1包不能恢复当前E1费用状态。

本包已经创建，不要覆盖。若以后重新导出，调用停止后使用新的输出文件名。已纳入的Claude会话来自原机明确选择的目录；新机恢复时必须显式提供新的 `--dialogue-root`。下面以 `$HOME/.local/share/uteki/claude-data-products` 为新机目的地，启动窗口时也选择同一目录。

```sh
# 新机器：先通过自己的私密渠道传输包，替换实际存放位置。
python3 scripts/transfer_local_state.py verify /actual/private/path/private-state-v1.tar.gz
python3 scripts/transfer_local_state.py restore /actual/private/path/private-state-v1.tar.gz \
  --root "$PWD" --dialogue-root "$HOME/.local/share/uteki/claude-data-products"
```

导出器收集 Git 忽略的 `data/`、`experiments/`、`.local/claude-dialogues/` 内容及显式选定的外部会话；排除 `.env*`、依赖和缓存。它校验逐文件 hash，拒绝覆盖不同内容；它不会自动停止调用或把在途费用核销。E1 重放生成器拒绝非空 WAL/journal 和未完成请求，继承恢复账本中的真实上限与占用。若预检拒绝，应先核对状态，不能删除旁文件或重置账本绕过。

新机器可直接交代：

> 先读 AGENTS.md、docs/MACHINE_HANDOFF.zh-CN.md、E1 的 PLAN、DELIVERY 和 README。E1系统Data Agent独立材料交付评测与三配置对照已完成阶段交付；先核对Git与私密状态恢复，保留原costs.sqlite。原E1授权上限$100、累计释放$40是已记录的实验范围，不把它解释成所有后续阶段的自动追加预算。Codex 只开发、测试和独立验收，不能把 evaluation-only 参考答案给系统。按最新PLAN沿E2加入10-Q的顺序准备下一阶段，不复跑已通过的题来凑结果；保留失败、未知费用和冻结历史。先做离线与配置检查，再启动有目的的一题。

本次完成原机配置预检、归档校验和本机空目录恢复；没有在另一台机器安装依赖或执行模型。配置预检见 [记录](../experiments/agent_design/2026-10-09-e1-benchmark-v1/preparation/machine-preflight.json)。Git提供代码与公开产物，私密包只补被忽略的文件；导出清单中的Git父提交时间早于本轮最终提交，不应只检出该父提交。新机使用包含本轮交付的最新main。

## 历史：Data-only 证据闭环已验收

以下记录属于先前的 `2026-10-09-data-agent-completion-v1`，不是当前 E1 的操作入口。旧问题、运行命令、无限额度授权和私密包均不得用于继续 E1；当前请使用上方入口。

该历史任务验证系统 Data Agent 独立取材、选择原文/记录和复核补取；不运行 Analysis 报告生成。说明见 [运行边界](DATA_QUERY_ANALYSIS_BOUNDARY.zh-CN.md) 与 [证据验收](DATA_AGENT_EVIDENCE_ACCEPTANCE.zh-CN.md)。原六题与目录分页针对性复跑均独立验收通过。[打开统一结果](http://127.0.0.1:8769/docs/design/data-agent-acceptance/data-agent-evidence-v1/) · [范围、费用和验证明细](../experiments/agent_design/2026-10-09-data-agent-completion-v1/DELIVERY.zh-CN.md)。

该历史轮次目录、六题列表、产物查看和上传边界集中在 [completion-v1 README](../experiments/agent_design/2026-10-09-data-agent-completion-v1/README.md)。旧运行内部的绝对引用不会自动迁移；已渲染的相对路径成品可以阅读，重新生成历史页仍可能需要原路径。不要修改冻结 JSON 来消除这个限制。

仅复查 completion-v1 历史任务时，安装依赖后在仓库根目录执行下列旧入口。该脚本从自身位置确定本机仓库路径，读取显式 `cases.json`、版本化 `configs-v3` 模板和仓库内 `datasets/msft`、`datasets/googl`。它核对冻结 manifest、公司、来源、snapshot 与原问题；只重定位数据集、凭证根目录、workspace 和 ledger 路径，不复制旧 `initial_query_ref`、选段或预期答案。

```sh
PYTHONPATH=src .venv/bin/python experiments/agent_design/2026-10-09-data-agent-completion-v1/make_replay_configs.py \
  --cases experiments/agent_design/2026-10-09-data-agent-completion-v1/cases.json \
  --output-dir "$PWD/workspace/data-replay-configs-local-01" \
  --ledger "$PWD/experiments/agent_design/2026-10-09-data-agent-completion-v1/costs.sqlite" \
  --check-only
```

该检查不调用模型、不读取 key、不写文件。通过后去掉 `--check-only`，生成六份新配置及输入 hash 清单；输出目录必须尚不存在。planner/worker 使用 Sonnet 5.5、8192 输出 token；reviewer 保留 12000。随后先检查一个问题，再启动它：

```sh
PYTHONPATH=src .venv/bin/python scripts/run_data_retrieval.py \
  --config workspace/data-replay-configs-local-01/msft-revenue.json \
  --output workspace/data-replay-runs-local-01/msft-revenue \
  --check-only

PYTHONPATH=src .venv/bin/python scripts/run_data_retrieval.py \
  --config workspace/data-replay-configs-local-01/msft-revenue.json \
  --output workspace/data-replay-runs-local-01/msft-revenue
```

最后一条会真实调用模型。其他五题分别使用同目录对应配置，每题用新输出路径；不自动并发启动六题。输出保留原始请求、实现与数据 hash、每个 attempt、模型配置、复核结果和最终状态。旧配置内的绝对路径仅为历史记录，不能直接当新机器入口，也不要原地替换冻结文件。

`AIHUBMIX_API_KEY` 在新机器本地 `.env` 配置并保持权限 `600`，不要加入 Git。先按下方迁移说明恢复需要延续的私密费用账本；`--ledger` 指定所有角色共用的真实本机路径，生成器不会创建、清空或搬迁账本。completion-v1 当时授权使用 `record_only`、无美元硬上限；这不是当前 E1 授权。该历史任务的失败费用和未知预留继续保留，attempt、请求超时与重试仍有界。不要把旧账本漏迁移解释为历史费用为零。

completion-v1 导出时该任务的模型队列已停止，不代表当前 E1 调用状态。该历史私密包为 `output/machine-handoff-20261009/private-state-v1.tar.gz`，校验记录为同目录 `verification.json`。它们不在Git中，需要通过用户控制的私密渠道带到新机器；恢复步骤可复用下文，但这份包不含当前 E1 的最新状态。`experiments/**/costs.sqlite*` 已忽略，可被 `transfer_local_state.py` 纳入包；2026-10-08 的旧包不包含本轮新增账本状态。仓库外的 Claude 会话必须使用真实的 `--dialogue-root` 显式选择；`.env` 不在包内。

## 历史交接快照 · 2026-10-08

以下安装步骤仍可参考；旧业务图状态、旧私密包指纹和预算是 2026-10-08 的历史记录，不是当前 E1 任务的进度或费用限制。下方状态、授权、下一项与已验证结论均限定于该历史日期；安装命令可参考，历史执行入口不可当作当前入口。

## 历史接手入口（2026-10-08）

先读 [八项待办](DATA_AGENT_EXTRACTION_TODO.zh-CN.md) 与 [系统自主取材入口](DATA_AGENT_RUNTIME_MATERIALS.zh-CN.md)。旧候选见[阶段记录](../experiments/agent_design/2026-10-08-business-granularity-v2/README.zh-CN.md)和[内容复核](../experiments/agent_design/2026-10-08-business-granularity-v2/evaluation/critic-revised-02-content-review.md)。完整历史在 [TODO.md](../TODO.md)。

范围是01–09，跳过06；10–16暂不做。**09业务图独立执行成立，内容仍未通过。** 不把协议通过当成内容正确。

仓库 [AGENTS.md](../AGENTS.md) 包含协作规则；项目内 `skills/` 是可迁移的规则来源，不依赖旧电脑的全局Skill副本。Claude顾问规则在 `apps/claude_dialogue/prompts/`，共享聚焦规则在 `docs/COLLABORATION_FOCUS.zh-CN.md`。

当时用于旧业务图任务的接续说明（当前 E1 不使用）：

> 先读AGENTS.md、docs/MACHINE_HANDOFF.zh-CN.md、docs/DATA_AGENT_EXTRACTION_TODO.zh-CN.md和docs/DATA_AGENT_RUNTIME_MATERIALS.zh-CN.md，从09系统自主取材→提取入口的真实模型验收继续。旧103块材料是Codex预选的，不能再当自主输入。Codex只开发与测试；系统自己选章节、读原文和补读。保留冻结证据、失败记录和同一预算，不把参考答案放回执行输入。先核对迁移完整性；当前超额调用须先取得授权。

## 安装与启动

支持macOS / Linux，Python 3.11+、Node.js 20+、Git、uv。Windows请使用WSL；归档使用POSIX锁。

```sh
git clone https://github.com/Rain1601/uteki.beta.git
cd uteki.beta
uv sync --locked --extra analysis --extra data --extra mcp
npm ci
.venv/bin/python scripts/run_offline_checks.py
.venv/bin/python scripts/check_workspace.py
```

安装依赖需要联网；上述检查不请求模型。查看已生成页面不需要模型密钥。工作区检查发现缺失资料会返回非零，按清单恢复，不能替换成其他公司数据。

静态验收页面，单独一个终端：

```sh
python3 -m http.server 8769 --bind 127.0.0.1
```

[历史业务图](http://127.0.0.1:8769/docs/design/data-agent-acceptance/microsoft-opus-guided-business-v2/)已包含Mermaid SVG、业务明细、原文和索引链接。历史页面保留。

工程后台，另一个终端：

```sh
PYTHONPATH=src:. .venv/bin/python -m apps.review_workbench.app --check
PYTHONPATH=src:. .venv/bin/python -m apps.review_workbench.app --host 127.0.0.1 --port 8765
```

打开 [运行结果](http://127.0.0.1:8765/agent-results) 或 [运行过程](http://127.0.0.1:8765/agent-runs)。参数见 [本地开发](LOCAL_DEVELOPMENT.md)。查看已有图不依赖旧电脑临时工具；重新生成SVG可显式使用 `npx --yes --package @mermaid-js/mermaid-cli@11.12.0 mmdc`，沿用 `skills/uteki-business-diagrams/assets/mermaid-config.json`。首次安装可能下载浏览器。

## 历史私密状态单独迁移（2026-10-08）

用户已将GitHub仓库改为私有，并明确授权同步完整提交；推送前已通过GitHub接口确认`isPrivate=true`。代码、公开材料、候选、页面、实验产物、回测材料与Todo随Git同步。API密钥仍不进入Git。预算SQLite、私密Claude对话、本机观测和含运营身份的获取配置沿用单独迁移包：

`output/machine-handoff-20261008/private-state-v2.tar.gz`

此文件**未上传GitHub**。通过自己控制的本地传输方式带到新电脑。它包含原账本、被忽略的实验资料和Claude会话；排除`.env`凭据文件，权限600。恢复逐文件核对SHA-256，拒绝路径穿越、符号链接和覆盖不同内容，不修改冻结原件。

本次包共2,336个文件、235个目录，11,575,703字节。SHA-256：`c18a9358a002f8c208c470de9cc52d3e4f877caae3459e71828ace266686f082`。这是该历史快照的指纹；后续重新导出需使用新指纹。它是私密资料，不应加入公开Git。

用实际存放位置替换下面的文件路径：

```sh
python3 scripts/transfer_local_state.py verify /path/to/private-state-v2.tar.gz
mkdir -p "$HOME/.local/share/uteki/claude-data-products"
chmod 700 "$HOME/.local/share/uteki/claude-data-products"
python3 scripts/transfer_local_state.py restore /path/to/private-state-v2.tar.gz \
  --root "$PWD" --dialogue-root "$HOME/.local/share/uteki/claude-data-products"
```

恢复包后，登记当前业务图所依赖的 **11 个明确历史运行**。旧绝对路径只出现在单独本机映射中；历史descriptor及发表hash不改写：

```sh
.venv/bin/python scripts/relocate_observation_history.py create \
  --root "$PWD" --old-root /Users/rain/Documents/ChatGPT/uteki.beta \
  --trace run-18b6b1aaf340405596334908628f7be4 \
  --trace run-2d3065ac1ca74cfda3103082c15b8a0f \
  --trace run-3089d2c377a14f9eb4ee3c59d0aff534 \
  --trace run-48bfdf815d5c4f0f91117f993e6b557f \
  --trace run-4b7d09949895415aa81cc6c326080a2b \
  --trace run-8771b73c2a6f420f92ba348cf9e6e41f \
  --trace run-8a4552f71c7d48c4a1df4a398b52893c \
  --trace run-8bf14d07cd10496ebbd1d91915e99da6 \
  --trace run-8cd94f26b6ce452a88094f4e9fde646d \
  --trace run-a1ec38a4da2740dc83639cdb05e237d9 \
  --trace run-aace75c60d84490d876c7e2071eb1e4a

.venv/bin/python scripts/relocate_observation_history.py check --root "$PWD"
```

当前快照预期核对11个运行、200个原发表文件。生成的`.local/observation-relocation.json`仅属于新机器，不提交Git；已有文件不覆盖。它绑定旧/新根目录、trace、原descriptor hash和精确相对目录；无映射、错目录/trace/hash或产物篡改会拒绝。无需API密钥，不调用模型。

适用范围是当前业务图的历史发表校验及后续复核预检。其他旧工作台消费者和`fact_completion`自己的绝对路径校验尚未统一接入，不能宣称全部历史界面都已跨路径恢复。详见[观测路径恢复说明](OBSERVATION_RELOCATION.zh-CN.md)。新root离线重放当前11个运行、200个发表文件及最新候选的下一阶段预检已验证；没有修改原机器的历史记录。

旧电脑如又产生新运行，停止写入后导出到新文件，不覆盖这份快照：

```sh
python3 scripts/transfer_local_state.py create --root "$PWD" \
  --dialogue-root /absolute/path/to/private/claude-data-products \
  --output /absolute/private/path/new-state.tar.gz
```

API密钥在新机器单独配置：复制`.env.example`为`.env`，填入自己的密钥，执行 `chmod 600 .env`。不要将密钥放入聊天、Git或交接文档。

恢复后启动Claude窗口：

```sh
PYTHONPATH=src .venv/bin/python -m apps.claude_dialogue \
  --conversation-root "$HOME/.local/share/uteki/claude-data-products" \
  --credentials-root "$PWD" --port 8770
```

只查看不付费。窗口账本和业务提取账本分别保留；不新建空账本冒充原会话。

## 历史位置与下一步（2026-10-08）

| 顺序 | 工作 | 真实状态 |
|---|---|---|
| 当前 | 09：系统自主取材并提取 | 新入口离线已连通；真实模型选材充分性与业务内容仍待验收，旧103块输入不是自主选材 |
| 后续 | 03/04：整文解析质量 | 部分结构与相邻脚注通过；复杂表头、单位、跨节引用未完成 |
| 后续 | 07：结构化财务事实 | 小样本通过；三张主表及必要附注未全部覆盖 |
| 后续 | 08：财报精编 | Microsoft业务小节已执行，整文未完成 |
| 配套 | 02：官方材料获取 | 当前HTML 10-K范围部分完成；01定义、05契约消费完成 |

最新Microsoft候选为 `critic-revision-02`：19对象、16关系、68产品属性。系统Sonnet提取/修订，Opus独立复核；Codex评审与执行输入隔离。Google93块原文冻结，但新同规则运行尚未执行；Meta尚无系统候选。不能宣称多公司或陌生公司验收通过。

历史业务图任务账本（以下额度与余额仅记录当时状态）：`experiments/agent_design/2026-10-07-business-coverage-v1/run-06/budget.sqlite`。

- 当前授权上限 **$8**；估算已用$7.305062，未知占用$0.383410，可用$0.311528。
- 下一次Opus04预留$1.027704，预检不通过，**没有发送请求**。
- 提高到$10只是待用户决定的建议，未获批准。不要重置账本、清除unknown或另建任务绕过。
- 当前没有该任务的在途请求。费用是冻结价表估算，不是供应商实际账单。

下一项仍是09内容验收。先核验恢复后的来源、原始响应、补丁与发表记录，再处理同一任务额度决定。程序校验、模型评价、用户验收是不同状态。

## 历史验证边界（2026-10-08）

本次执行默认离线检查及迁移完整性检查，具体结果见本次提交。完整历史资料回归、真实新机器依赖安装和用户视觉验收未执行。迁移包不含运行环境或旧电脑的全局Codex聊天记录；本文件、Todo、实验记录及私密Claude会话构成接续入口。

最终从Git暂存区导出独立目录，使用现有已安装依赖运行：**Python 540项、JavaScript 35项全部通过**。恢复迁移包后，11个运行的200个发表文件通过校验；同一账本的16k下一轮预检与原值一致（预留$1.027704，余额$0.311528，未发网）。这验证了文件和路径接续，不等同于已经在另一台电脑安装依赖。

当前工作区与后台启动预检通过，保留已知非必需资料缺口：历史Alphabet摘录第90段指纹不匹配（见本地开发说明）。没有改写历史原件以消除提示。依赖锁已通过离线一致性检查。`.gitattributes`固定数据、实验和基准材料的原始换行，避免跨机器检出改变证据指纹。

实际异目录恢复已验证：迁移文件逐项hash通过，16轮私密Claude会话可完整加载；空目录和新建私密目录权限均保留。旧版private-state.tar.gz未保留空目录，不用于本次交接；请使用上面的v2包。
