# 换机接续开发 · 2026-10-08

## 接手入口

先读 [八项待办](DATA_AGENT_EXTRACTION_TODO.zh-CN.md) 与 [系统自主取材入口](DATA_AGENT_RUNTIME_MATERIALS.zh-CN.md)。旧候选见[阶段记录](../experiments/agent_design/2026-10-08-business-granularity-v2/README.zh-CN.md)和[内容复核](../experiments/agent_design/2026-10-08-business-granularity-v2/evaluation/critic-revised-02-content-review.md)。完整历史在 [TODO.md](../TODO.md)。

范围是01–09，跳过06；10–16暂不做。**09业务图独立执行成立，内容仍未通过。** 不把协议通过当成内容正确。

仓库 [AGENTS.md](../AGENTS.md) 包含协作规则；项目内 `skills/` 是可迁移的规则来源，不依赖旧电脑的全局Skill副本。Claude顾问规则在 `apps/claude_dialogue/prompts/`，共享聚焦规则在 `docs/COLLABORATION_FOCUS.zh-CN.md`。

新机器开启Codex任务时可以直接交代：

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

[当前业务图](http://127.0.0.1:8769/docs/design/data-agent-acceptance/microsoft-opus-guided-business-v2/)已包含Mermaid SVG、业务明细、原文和索引链接。历史页面保留。

工程后台，另一个终端：

```sh
PYTHONPATH=src:. .venv/bin/python -m apps.review_workbench.app --check
PYTHONPATH=src:. .venv/bin/python -m apps.review_workbench.app --host 127.0.0.1 --port 8765
```

打开 [运行结果](http://127.0.0.1:8765/agent-results) 或 [运行过程](http://127.0.0.1:8765/agent-runs)。参数见 [本地开发](LOCAL_DEVELOPMENT.md)。查看已有图不依赖旧电脑临时工具；重新生成SVG可显式使用 `npx --yes --package @mermaid-js/mermaid-cli@11.12.0 mmdc`，沿用 `skills/uteki-business-diagrams/assets/mermaid-config.json`。首次安装可能下载浏览器。

## 私密状态单独迁移

用户已将GitHub仓库改为私有，并明确授权同步完整提交；推送前已通过GitHub接口确认`isPrivate=true`。代码、公开材料、候选、页面、实验产物、回测材料与Todo随Git同步。API密钥仍不进入Git。预算SQLite、私密Claude对话、本机观测和含运营身份的获取配置沿用单独迁移包：

`output/machine-handoff-20261008/private-state-v2.tar.gz`

此文件**未上传GitHub**。通过自己控制的本地传输方式带到新电脑。它包含原账本、被忽略的实验资料和Claude会话；排除`.env`凭据文件，权限600。恢复逐文件核对SHA-256，拒绝路径穿越、符号链接和覆盖不同内容，不修改冻结原件。

本次包共2,336个文件、235个目录，11,575,703字节。SHA-256：`c18a9358a002f8c208c470de9cc52d3e4f877caae3459e71828ace266686f082`。这是当前快照的指纹；后续重新导出需使用新指纹。它是私密资料，不应加入公开Git。

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

## 当前位置与下一步

| 顺序 | 工作 | 真实状态 |
|---|---|---|
| 当前 | 09：系统自主取材并提取 | 新入口离线已连通；真实模型选材充分性与业务内容仍待验收，旧103块输入不是自主选材 |
| 后续 | 03/04：整文解析质量 | 部分结构与相邻脚注通过；复杂表头、单位、跨节引用未完成 |
| 后续 | 07：结构化财务事实 | 小样本通过；三张主表及必要附注未全部覆盖 |
| 后续 | 08：财报精编 | Microsoft业务小节已执行，整文未完成 |
| 配套 | 02：官方材料获取 | 当前HTML 10-K范围部分完成；01定义、05契约消费完成 |

最新Microsoft候选为 `critic-revision-02`：19对象、16关系、68产品属性。系统Sonnet提取/修订，Opus独立复核；Codex评审与执行输入隔离。Google93块原文冻结，但新同规则运行尚未执行；Meta尚无系统候选。不能宣称多公司或陌生公司验收通过。

原任务账本：`experiments/agent_design/2026-10-07-business-coverage-v1/run-06/budget.sqlite`。

- 当前授权上限 **$8**；估算已用$7.305062，未知占用$0.383410，可用$0.311528。
- 下一次Opus04预留$1.027704，预检不通过，**没有发送请求**。
- 提高到$10只是待用户决定的建议，未获批准。不要重置账本、清除unknown或另建任务绕过。
- 当前没有该任务的在途请求。费用是冻结价表估算，不是供应商实际账单。

下一项仍是09内容验收。先核验恢复后的来源、原始响应、补丁与发表记录，再处理同一任务额度决定。程序校验、模型评价、用户验收是不同状态。

## 验证边界

本次执行默认离线检查及迁移完整性检查，具体结果见本次提交。完整历史资料回归、真实新机器依赖安装和用户视觉验收未执行。迁移包不含运行环境或旧电脑的全局Codex聊天记录；本文件、Todo、实验记录及私密Claude会话构成接续入口。

最终从Git暂存区导出独立目录，使用现有已安装依赖运行：**Python 540项、JavaScript 35项全部通过**。恢复迁移包后，11个运行的200个发表文件通过校验；同一账本的16k下一轮预检与原值一致（预留$1.027704，余额$0.311528，未发网）。这验证了文件和路径接续，不等同于已经在另一台电脑安装依赖。

当前工作区与后台启动预检通过，保留已知非必需资料缺口：历史Alphabet摘录第90段指纹不匹配（见本地开发说明）。没有改写历史原件以消除提示。依赖锁已通过离线一致性检查。`.gitattributes`固定数据、实验和基准材料的原始换行，避免跨机器检出改变证据指纹。

实际异目录恢复已验证：迁移文件逐项hash通过，16轮私密Claude会话可完整加载；空目录和新建私密目录权限均保留。旧版private-state.tar.gz未保留空目录，不用于本次交接；请使用上面的v2包。
