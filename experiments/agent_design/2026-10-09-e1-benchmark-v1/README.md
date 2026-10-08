# E1 独立证据评测与成本对照

当前详细阶段报告：[DELIVERY.zh-CN.md](DELIVERY.zh-CN.md)。7题可读成品：[验收页 v3](../../../docs/design/data-agent-acceptance/e1-evidence-benchmark-v3/index.html)（原机服务：[本机入口](http://127.0.0.1:8769/docs/design/data-agent-acceptance/e1-evidence-benchmark-v3/)）。该页已做HTTP和86个链接/锚点检查；三模型对照见[比较页](../../../docs/design/data-agent-acceptance/e1-model-comparison-v1/index.html)（[本机入口](http://127.0.0.1:8769/docs/design/data-agent-acceptance/e1-model-comparison-v1/)），已做HTTP及4个链接检查，没有进行视觉审查。

当前实施状态：[PLAN.zh-CN.md](PLAN.zh-CN.md)。这是系统 Data Agent 的材料交付评测，不运行分析报告生成。Codex 负责代码和独立标准，系统运行时自行查询、取材、复核；参考答案隔离于 `evaluation-only/`。

本轮E1受限评测交付完成：7题冻结评测、一次三模型取材对照、可读页面及私密换机包均已交付。下一项是E2：同公司10-Q扩展，尚未启动。7题都有通过的阶段结果：E1-06 双审恢复r2由系统补齐Azure自身定义，独立7/7、聚焦和流程通过；E1-04旧基线及E1-05包含取材后补审，不能称七题在同一实现下从零一次成功。

E1-04 新对照：Sonnet、Qwen、DeepSeek 的最终材料均为独立3/3。Sonnet、DeepSeek流程通过；Qwen材料足够，但固定审核器追加“正文必须出现年度起日”的要求，最终流程未放行。本次对照固定为planner/worker/来源reviewer三个角色，没有启用E1-06新增的独立问题审核；Qwen的审核误报仍未修复。三者都未达到严格最小材料。详细费用、耗时、根因和未完成项见 DELIVERY，不据一道题宣布总体模型排名。

- `acquisition/`：两份独立官方 10-K 的获取清单与原件；SEC联系身份仅从本机环境加载。
- `datasets/`：固定的 FY2024、FY2025 与双年数据集；不可改写旧原件或 manifest。
- `evaluation-only/frozen/`：每题调用前冻结的要求和原件证据；不是运行输入。
- `evaluation-only/reviews/`：Codex原件核对、覆盖/遗漏/额外材料判定和程序统计。失败也保留。
- `configs-v1/`：初次5美元分段释放配置，记录历史；账本增至10后不再直接用于执行。
- `configs-v2/`：历史同一账本累计10美元释放配置；新增Qwen/DeepSeek配置是待实测配置，不代表成功。
- `configs-v3/`：同一账本累计20美元分段释放，继续修复与剩余冻结题；不是追加20美元授权。
- `configs-v4/`、`configs-v5/`：同一账本累计30、40美元的分段释放配置。后者用于后续新调用；历史恢复配置需单独核对，不能冒充全新运行。
- `runs/`：真实调用、响应、过程、最终交付及模型自审；模型自审不是独立验收。
- `preparation/`：准备层核对、模型价格/协议、根因与修复说明。

费用总授权为新增外部API合计100美元。当前只分段释放累计40美元，未新建独立额度。`costs.sqlite` 是同一私密账本，不进入Git；失败和未知预留不能删除。`budget-release-{10,20,30,40}.json`记录沿用用户100美元授权的分段释放。本轮最终已记录 **344次请求：已知估算$28.4473026834 + 未知预留$0.0358508674 = 总承诺$28.4831535508**，2次unknown保留，零在途；账本与收据已核对。包含全部失败、probe、恢复及对照。E1-06最新恢复增量$1.934868不能当成从零成本。供应商实际账单仍未对账，历史节点保留在DELIVERY。

## 换机重新运行一个题

先按 [换机交接文档](../../../docs/MACHINE_HANDOFF.zh-CN.md) 检出本轮提交并恢复私密状态。Git 提供已跟踪文件；`transfer_local_state.py` 只补回指定目录中被忽略的文件，不能代替 Git。恢复后，本实验根目录应同时具备所选版本配置（当前为 `configs-v5/`）、`datasets/`、`acquisition/`、`runs/` 与本轮真实 `costs.sqlite`。评测资料可以供 Codex 离线审查，但不得传给系统运行。

本轮新包已导出：`output/machine-handoff-20261009-e1/private-state-v1.tar.gz`，SHA-256 为 `40962ab3307a8b0324929012727fc4353ba3fab9f10fe5ccf5c9b69ae47fb889`。共2,434个文件、254个目录、11,711,925字节，权限600。包校验和本机空目录实际恢复通过，恢复后的E1账本逐字节相同；`.env`未包含。此包及校验记录不在Git中，须经用户控制的私密渠道另行传输。

这份包已显式包含仓库外的Claude顾问会话。恢复时必须按交接文档提供新机器的 `--dialogue-root /actual/private/conversation`，不能省略、猜测或指向公开目录。原服务停止写入后完成导出，再恢复服务。旧迁移包不能代表当前 E1 账本；缺少本轮真实 `costs.sqlite` 时，不能以新空账本继续同一授权。

`configs-v5/E1-06-sonnet-question-audit.json` 属于复用旧 query 的恢复配置，不能直接用作一次从零复跑模板。新增 `configs-v5/E1-06-sonnet-independent-review.json` 删除 `initial_query_ref`，保留显式双审核配置，可作为 E1-06 新运行的换机模板。原机runtime `--check-only` 已通过，**尚未按该模板从零真实执行**；不能把旧恢复结果当成该新模板的验收。生成器同时检查并重定位四个角色，共用原账本。

在新机器本地 `.env` 配置 `AIHUBMIX_API_KEY`；如选用官方DeepSeek取材，还需 `DEEPSEEK_API_KEY`。文件保持权限 `600`；密钥不在 Git 或私密迁移包中。重放冻结材料不重新获取 SEC；若后续重新获取，另行配置真实 SEC 联系标识及适用的网络配置，不沿用旧机器代理端口作为默认值。

从仓库根目录使用 `make_replay_config.py`，显式给题目、模板、数据集 manifest hash、已恢复账本、凭证根目录、workspace 和新输出目录。下面是 **E1-02 Sonnet 的新运行示例**，不是要求把它作为下一题；实际优先级见 PLAN。`--check-only` 只读；随后去掉该参数生成新配置。生成器不读取评测答案，不复用旧反馈或 `initial_query_ref`，不改写冻结历史，也不创建或扩充费用额度。

```sh
PYTHONPATH=src:. .venv/bin/python experiments/agent_design/2026-10-09-e1-benchmark-v1/make_replay_config.py \
  --case E1-02 \
  --template experiments/agent_design/2026-10-09-e1-benchmark-v1/configs-v5/E1-02-sonnet.json \
  --dataset experiments/agent_design/2026-10-09-e1-benchmark-v1/datasets/msft-acquired-fy2025 \
  --dataset-manifest-sha256 608c7d94a0aee59b6fe11f64b695fcb4c068f6807e49c8a5bd35e2e93e6ab69a \
  --ledger experiments/agent_design/2026-10-09-e1-benchmark-v1/costs.sqlite \
  --credential-root "$PWD" --workspace "$PWD/workspace/e1-replay" \
  --output-dir "$PWD/workspace/e1-replay-config" --check-only
```

当前原机已通过 E1-02 新模板生成器 `--check-only` 和 E1-06 从零双审模板runtime `--check-only`；记录见 [换机预检](preparation/machine-preflight.json)。这些检查没有调用模型，不代表新机器已安装或实跑成功。生成器要求账本无在途请求及非空 WAL/journal，预算仍有余量，且模板请求上限与账本一致；它会继承恢复账本的实际累计上限。拒绝时先核对状态，不能删除旁文件、清空 unknown 或另建账本绕过。

去掉上面的 `--check-only` 后，会在尚不存在的输出目录写入 `E1-02-replay.json`、`provenance.json` 和 `manifest.json`。随后执行：

```sh
PYTHONPATH=src:. .venv/bin/python scripts/run_data_retrieval.py \
  --config workspace/e1-replay-config/E1-02-replay.json \
  --output workspace/e1-replay-runs/E1-02-sonnet-r1 --check-only

# 仅在预检通过且确实需要新运行时执行；此命令会付费。
PYTHONPATH=src:. .venv/bin/python scripts/run_data_retrieval.py \
  --config workspace/e1-replay-config/E1-02-replay.json \
  --output workspace/e1-replay-runs/E1-02-sonnet-r1
```

每次新运行使用新输出目录，所有角色沿用同一恢复账本。其他题需要明确选择其模板、匹配的数据集和真实 manifest hash，不能只改题号；含旧选材引用的恢复配置不能当成一次全新自主运行。参考答案、冻结命中列表和旧审阅反馈不能加入新运行输入。

历史运行内绝对引用保留，不原地替换破坏 hash。浏览已生成的成品优先使用相对链接；重新运行使用新配置路径。部分旧原始过程链接仍可能绑定旧根目录，生成器不承诺迁移全部历史查看器。当前已完成私密包校验、本机空目录恢复和原机配置预检；没有执行另一台机器的依赖安装或模型调用，不能宣称异机全链路验收通过。
