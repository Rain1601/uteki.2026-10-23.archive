# R22-H：历史可见性重验与运行包恢复

2026-10-12。本轮目标是找到 E6 原始运行记录，重新判断模型实际收到了哪些内容。**本机检索未找到目标记录，12 次目标运行均未能重验，不能标为通过或内容失败。** 可执行的迁移机制修复和输出截断离线诊断继续推进；新增 API 调用为 0。

## 查找结果

检索覆盖项目（含忽略文件）、本机 Documents、Desktop、Downloads、Codex 目录、临时目录和已挂载卷。Git 只有当前一个 worktree，全部本地 Git 引用中也没有这两个运行目录的提交记录。未搜索未挂载磁盘、另一台机器或远程私密存储。

- 找到四个 10 月 8 日至 9 日的私密迁移包；逐一检查包内目录，没有 E6-R3/V3 目标文件，也没有 E6 文件成员。未恢复旧包、未读取旧顾问对话正文。
- 两个旧 Uteki 项目 ZIP 的目录也无目标记录或嵌套迁移包。
- 交接文档指定的 `output/machine-handoff-20261009-current/private-state-v1.tar.gz` 不存在。文档所记 SHA-256 为 `c09b423808f87b209b14dd44ef5e03141c94ab4bf6a56b953a6af8704b2dd1d9`，与找到的四个包均不同；它是否含 E6 记录仍未知，不能按文件名推断。
- 新的两个验收入口均可正常加载。问题是缺少历史证据，不是验收代码无法启动。

逐运行路径、缺失文件、三档数据集预期哈希、已找到迁移包哈希和新检查器哈希见 [可用性检查记录](checks/r22-h-20261012/availability.v1.json)。该记录是缺口检查，不是业务验收报告。

## 确切缺什么

| 目标 | 必需目录 | 当前状态 |
|---|---|---|
| E6-V3 九次运行 | `output/e6-repeatability-20261010-r3/`，其中 `R1`、`R2`、`R3` 各有 `S1`、`S2`、`S3` 的 `run-r1` | 九个运行目录均缺失 |
| E6-R3 三次运行 | `output/e6-delivery-boundary-20261010-r1/`，其中 `replay-original-R3-S1`、`fresh-S1`、`fresh-S3` 的 `run-r1` | 三个运行目录均缺失 |
| 冻结材料 | `output/e6-material-scale-20261010-r1/S1/preparation/dataset`，以及 S2、S3 对应目录 | 三份数据集 manifest 均缺失；这不代表本机完全没有同公司财报 |
| 运行冻结与历史追踪 | 两个实验的 `evaluation-only/freeze.v1.json`、V3 的 `evaluation-only/R3-S1-failure-trace.v1.json` | 均缺失 |

每次运行应保留完整目录，尤其是：

1. 封存 `manifest.json`、`config.json`、`result.json` 和同级执行回执。
2. 各 Query 的 `turn-*/input.json`、工具结果、分页内容、artifact 和最终交付。
3. `decision-*-attempt-*.json`、绑定的模型调用 start/end、原始响应和 usage。
4. 审核输入、审核输出、最终 review 引用及其哈希。

仅有最终 JSON、截图、公开汇总或财报原件，不能证明历史模型输入。重新调用模型也不能补造过去的可见性证据。

## 已处理的迁移机制缺口

检查源码确认：旧 `transfer_local_state.py` 默认只收集 `data/`、`experiments/` 和本地对话目录，未收集 `output/`；旧恢复器也不允许恢复该范围。E6 运行转存到 `output/` 后，旧迁移命令即使成功，也不能完整迁移这些运行。这是可复现的打包能力缺口；不能据此断言另一台机器具体用了什么打包方式。

现在新增可重复的 `--include-output` 参数，只有显式选定的 output 子目录才会进入包。新包使用 v2 清单记录选择；默认仍使用 v1，旧包兼容。校验/恢复只允许清单列出的范围，保留哈希检查、原字节、拒绝覆盖不同文件、拒绝软链和路径穿越；`.env` 仍排除。

在**原运行记录所在机器**，停止写入后可使用下列命令准备新私密包。当前机器缺少目录，执行时应明确失败，不能导出空包冒充恢复：

```sh
.venv/bin/python scripts/transfer_local_state.py create \
  --root "$PWD" \
  --include-output output/e6-repeatability-20261010-r3 \
  --include-output output/e6-delivery-boundary-20261010-r1 \
  --include-output output/e6-material-scale-20261010-r1 \
  --output /private/tmp/uteki-e6-history-recovery-v2.tar.gz

.venv/bin/python scripts/transfer_local_state.py verify \
  /private/tmp/uteki-e6-history-recovery-v2.tar.gz
```

这些参数是在原有收集范围上追加目录，不是 output-only 导出。原有默认范围含本地私密数据；包通过用户控制的私密渠道传递，不提交 Git。本轮没有实际导出、上传或恢复私密数据。外部账本、原受控复跑引用的其他历史目录等依赖若在所选范围之外，需要对照配置和引用另行显式收录。离线可见性检查不需要 API 密钥。

工具不重写冻结 JSON 中的绝对路径，也不声称自动解决跨机器路径映射。恢复到独立位置后，应先核对清单和引用，再决定只读路径适配；不能批量替换冻结文件内容后沿用原哈希。

## 恢复后如何重验

先 verify 包，再恢复到空目录并核对内容；检查运行、审核、调用、数据集的引用及哈希完整。保持旧运行、标准与报告不变，用当前 v2 验收器写新的报告文件。

已知入口：

```sh
PYTHONPATH=src:. .venv/bin/python \
  experiments/agent_design/2026-10-10-e6-repeatability-v3/evaluation-only/independent-real-acceptance.v1.py \
  --slot R1-S1 --report /private/tmp/e6-v3-R1-S1-visibility-v2.json

PYTHONPATH=src:. .venv/bin/python \
  experiments/agent_design/2026-10-10-e6-delivery-boundary-v1/evaluation-only/independent-real-acceptance.v1.py \
  --case fresh-S1 --report /private/tmp/e6-r3-fresh-S1-visibility-v2.json
```

所有路径和依赖就绪后，覆盖九个 V3 slot 和三个 R3 case，包括原失败及受控历史阶段。分别报告：实际输入绑定、交付标识可见性、完整原文可见性、内容验收、未完成或不适用项；不能用其中一项替代另一项。当前没有生成任何冒充历史重验成功的报告。

## 当前继续推进的工作

R22-H 保留“待原证据”状态。R24 的显式运行目录迁移已实现并通过 16 项离线检查，覆盖原字节导出/校验/空目录恢复、旧包兼容、选择范围与拒绝边界。

E6-R4 不依赖历史包的类型化诊断已完成。源码与模拟 SDK 调用已确认：`finish_reason=length` 会保存残稿与用量、记账并停止；不会当网络错误重试。现在通过 `ModelOutputLimitExceeded` 明确标识“输出额度耗尽”；planner attempt、Query feedback 与停止原因记录额度、已报告 token 用量和残稿路径/hash。缺失用量保持未知。保持拒绝执行残稿、不自动加额度/重试。历史第 8 次决策为什么耗尽推理额度，仍须读取原输入才能判断。

位置与剩余队列见 [TODO](../TODO.md)。缺历史包阻塞历史重验，不阻塞这些工程检查；输出恢复策略和真实原例回归不能提前标完成。

本轮验证：迁移工具 16 项检查通过；模型/格式/网络/计费 48 项以及 Query loop/Claude 兼容 39 项检查通过。新 SDK + MockHTTP 集成用例即使收到合法 JSON，只要结束原因为 length 就拒绝动作，且不进行网络重试；有 usage 正常结算，缺 usage 保留未知。全部为离线验证。E6-R4 仅诊断层完成，有界恢复策略与历史原例回归仍未完成。

源码：[输出额度错误](../src/uteki/agents/runtime/output_limit.py)、[调用诊断与残稿记录](../src/uteki/agents/data_query/autonomous_model.py)、[显式迁移工具](../scripts/transfer_local_state.py)。下一具体工作是制定并验证显式、有界的容量恢复契约；不把提高额度或降低推理强度作为未经验证的默认修复。
