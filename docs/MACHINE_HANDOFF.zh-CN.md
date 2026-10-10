# 换机接续开发 · 2026-10-09

2026-10-10 更新：本机已启动 E5，完成 Microsoft/Alphabet 双公司完整语料与独立标准，修复旧 builder 漏传 form 导致财历丢失的问题。四项收入的工具预检通过，但尚未运行模型；本机未收到下述 E2–E4 原共享账本与迁移包。[当前 E5 交付](../experiments/agent_design/2026-10-10-e5-multi-company-v1/DELIVERY.zh-CN.md)含新相对路径准备入口、冻结标准与恢复缺口。下方是上一台机器的交接记录；“E5 尚未冻结”的历史描述已由本更新取代，费用账本不重建。

**当前位置：E2–E4指定题完成；R15/R16修复与历史消费验收通过。下一项为E5：先冻结多公司问题及各公司独立范围、覆盖标准。** 本文件是当前操作入口；完整队列和修复历史见[TODO](../TODO.md)。不从历史“下一步”或旧不限额配置启动调用。

## 接手后先做什么

1. 阅读[工作约定](../AGENTS.md)、本文件、[统一验收标准](DATA_AGENT_EVIDENCE_ACCEPTANCE.zh-CN.md)和[逐题交付](../experiments/agent_design/2026-10-09-e4-heldout-v1/DELIVERY.zh-CN.md)。
2. 检查代码、公开交付和私密状态是否齐全。Git可恢复代码和公开解释；继续原实验还需要本机迁移包中的原件、冻结运行和真实账本。
3. 先安装依赖、只读检查。当前E5尚未冻结或执行：Codex先独立读原件并审阅问题对应的必需信息、可选证据、必要上下文及冗余标准；再冻结评测。参考答案、精确必需块和批评不得传给运行Agent。

## 已完成与剩余范围

| ID | 状态 / 依赖 | 可查看交付 |
|---|---|---|
| C1–C3 | 验收统一、清理备份、本地启动完成 | [统一标准](DATA_AGENT_EVIDENCE_ACCEPTANCE.zh-CN.md)、[归档清单](REPOSITORY_RETENTION.zh-CN.md) |
| E1 | 双年度七题受限基线；旧账本及私密包缺失 | [历史阶段报告](../experiments/agent_design/2026-10-09-e1-benchmark-v1/DELIVERY.zh-CN.md) |
| E2 | 指定10-Q收入题r3必要4/4、原件/范围/聚焦及双审通过 | [季度逐题结果与失败](../experiments/agent_design/2026-10-09-e2-msft-10q-v1/DELIVERY.zh-CN.md) |
| E3 | 混合收入4/4；原列报/后续重列指定题r2通过 | [混合/版本逐题结果](../experiments/agent_design/2026-10-09-e3-mixed-sources-v1/DELIVERY.zh-CN.md) |
| E4 | H1现金流r2独立取材通过、r3仅恢复双审；H2新公司收入/地理归属r2必要5/5及完整规则通过 | [两题实际材料、遗漏/冗余、失败与费用](../experiments/agent_design/2026-10-09-e4-heldout-v1/DELIVERY.zh-CN.md) |
| R15/R16 | 新修订v2、旧v1精确兼容；期间解析v5。7份旧修订及5份成功产物加载通过，2份失败仍拒绝 | [核验脚本及记录](../experiments/agent_design/2026-10-09-e4-heldout-v1/evaluation-only/R15-R16-verification-v1/) |
| E5 | **下一项，未执行**；依赖E4指定题 | 多公司冻结问题、各公司独立来源/期间/覆盖与逐题标准 |
| E6 | 未完成；需固定规模及评价分母 | 材料增长下的质量/费用 |
| E7 | 后置；需关系类型及原文依据 | 公司relations |

整份数据仍为`prepared_with_gaps`。上述指定题通过不证明完整财务、全部修订、任意公司/格式或稳定泛化；本轮没有调用Analysis。历史失败和原冻结标准保留，恢复审核不追认为从零一次成功，参考对照不称严格A/B。

## 本轮工程状态

已修R1及R8–R16：共享原预算恢复、大包分页读取、逐块审核Schema、显式期间、无损compact大表读取、问题限定范围引用、增量计划、reader导航投影，以及旧审核协议兼容。修复是通用机制，未把公司答案写入执行逻辑。

R2–R7仍未修：探索来源先验、无期末来源审核、部分临时错误分类、简报审核token预算、business_map发布前hash复验、reading_groups旧版本回放。精确问题及状态见[标准中的review表](DATA_AGENT_EVIDENCE_ACCEPTANCE.zh-CN.md#本次代码-review-状态)。R15/R16发现时点的“未修”记录只作为历史，当前状态为已修。

## 模型与费用：继承原状态

用户明确不使用AIHubMix/MiniMax。当前实验四角色显式使用官方DeepSeek `deepseek-flash`；planner/worker为low、8192输出token，审核为none、16384；32步、取材attempt上限1，网络重试及问题协议修订有界。worker配置通过离线检查，本轮指定题没有委派worker，不能称四角色均有真实调用。

| 账本 | 已结请求 / 保守列表价估算USD | 限制 |
|---|---:|---|
| E2→E3→E4原共享`experiments/agent_design/2026-10-09-e2-msft-10q-v1/costs.sqlite` | 176 / 2.0569908；unknown及在途0 | USD硬上限3；请求护栏220，变更留痕，未清零/分叉 |
| 官方迁移独立历史`experiments/agent_design/2026-10-09-deepseek-official-v1/costs.sqlite` | 13 / 0.1280133；unknown0 | 原任务上限3，保留首轮失败 |
| E1旧机缺件历史 | 已知28.4473026834；unknown预留0.0358508674 | 总授权100、曾累计释放40；本机不能恢复调用 |

176笔包含全部失败、审核恢复及有界修订。E3→E4指定目标新增113笔/$1.3504302，已经闭合。费用不是已核对的供应商账单；Codex账户额度与API费用分开。缺账本不能新建空账本冒充继承；E1用户确认无旧私密包，不重复索取或清空旧费用。E5先做零API材料与标准冻结，再核对原预算和下一阶段配置，不把旧余额解释成自动新增预算。

## Git与私密状态边界

Git提交源码、测试、Skill、公开逐题解释、独立验收文字及审阅过的公开标准/核验脚本。新的四个实验目录采用显式公开文件清单；其余完整运行、准备层、配置、机器路径、联系人和费用SQLite保留本地，按忽略规则纳入迁移包。公开文档中指向这些材料的链接标为本地证据入口；未恢复私密包时不能仅靠checkout打开或完整重放。原文件逐字节保留，不为去除机器路径改写冻结JSON/hash。

凭据`.env`不随Git或迁移包传递；新机器单独配置`DEEPSEEK_API_KEY`与SEC联系身份，权限600。已提供的SEC身份在原机私密配置中保留。私密Claude完整对话保留本机；普通工程接续不依赖该会话，不随Git发布。

本轮迁移包入口：`output/machine-handoff-20261009-current/private-state-v1.tar.gz`，校验记录为同目录`verification.json`。只通过用户控制的私密渠道传输。它用于当前机器的忽略状态，不补回缺失的E1账本；包不含API密钥或外部Claude会话。包权限600，共3,246文件/477目录，14,747,230字节；SHA-256为`c09b423808f87b209b14dd44ef5e03141c94ab4bf6a56b953a6af8704b2dd1d9`。逐文件verify和空目录恢复均通过，两份现有账本逐字节一致；没有.env或Claude对话。最终回归结果见下方“本次交接验证”。

```bash
# 新机器：安装后，用实际收到的包路径替换示例。
.venv/bin/python scripts/transfer_local_state.py verify /actual/private/path/private-state-v1.tar.gz
.venv/bin/python scripts/transfer_local_state.py restore /actual/private/path/private-state-v1.tar.gz --root "$PWD"
```

导出须停模型请求和写入，使用新文件名，不能覆盖已有包。恢复器逐文件hash校验、拒绝符号链接/路径穿越和不同内容覆盖。原运行引用旧绝对路径；新机器应从明确冻结输入生成**新的**本机配置，绑定恢复后的同一账本和来源，先`--check-only`。当前E2–E4尚无专用换机配置生成器，不能直接执行旧配置或批量替换冻结文件；E5配置开发须纳入显式重定位及scope/hash预检。

## 安装、检查与启动

运行环境：macOS/Linux，Python3.11+、Node.js20+。在包含本轮提交的检出目录执行：

```bash
git pull --ff-only
uv sync --locked --extra analysis --extra data --extra mcp
.venv/bin/python scripts/run_offline_checks.py
PYTHONPATH=src:. .venv/bin/python -m apps.review_workbench.app --check
```

检查不调用模型。完整历史集成入口如下；缺私密历史材料时会保留非零结果，不生成占位资料使其通过：

```bash
.venv/bin/python scripts/run_offline_checks.py --integration
```

分别启动两个本地服务：

```bash
PYTHONPATH=src:. .venv/bin/python -m apps.review_workbench.app --host 127.0.0.1 --port 8765
.venv/bin/python -m http.server 8769 --bind 127.0.0.1
```

工作台为<http://127.0.0.1:8765/agent-results>；Swiss C与已有六题/E1页面可从[README](../README.md)进入。当前E2–E4逐题结果使用上方公开文档入口，尚未接入专用结果页。启动/HTTP可用与用户视觉验收分别记录。

## 清理与历史恢复

本地备份`codex/backup-20261009-before-cleanup`绑定基线`a4595ba82164f6597db72ee01891f3c2abf7cbf0`。本轮删除3,729个已确认无活动依赖的旧跟踪文件，226.51MiB；逐文件Git blob/hash与备份一致。Git历史仍保留，备份分支未推送。精确清单、恢复方法及保留依赖见[归档说明](REPOSITORY_RETENTION.zh-CN.md)。无关`apps/attention-game/`不属于本轮提交。

更早的E1、completion-v1及2026-10-08交接状态从各自PLAN/DELIVERY/README及备份提交追溯；旧AIHubMix、无限额配置和旧私密包指纹不作为本轮入口。整理前完整交接快照保留在本机`output/machine-handoff-20261009-current/`，未修改实验冻结记录。

## 本次交接验证

- 从实际暂存区导出独立目录后运行核心检查：567项Python、35项JavaScript全部通过。使用现有已安装依赖；不是另一台机器重新安装验证。
- 本轮受影响Data检查此前为218项通过、1历史路径fixture跳过，含重叠，不与核心数相加为业务分数；最后源码与这些检查一致。
- 完整历史集成实际运行2,360项：6失败、14错误、1跳过；JavaScript35通过。9错误来自沙箱禁止本地监听，开放本地端口后定向10项全部通过。其余6失败/5错误分别是旧审核/版本/错误文本断言、旧303路由、指标定义文本、旧event回放及未分发dataset；均对照a4595ba源码+Skill定向复现，未发现本轮新增失败。**完整集成仍未通过**，这些问题保留，不修改原件、跳过测试或放松运行校验。
- 私密包逐文件verify及新空目录restore通过；两份账本逐字节一致。共享账本仍176笔settled、上限3、unknown/在途0；无新增模型API。
- 实验公开白名单58文件约0.32MiB；完整运行/来源状态保留本机。暂存新增/修改文件逐项隐私扫描及清单审阅；费用SQLite、个人联系、凭据、机器路径和无关attention-game均排除。CLI可编辑示例已使用本机$PWD。
- 删除集3,729文件与归档清单及备份完全一致；提交前`git diff --cached --check`通过。新交接整理未重新进行视觉审阅、完整新机器模型复跑或供应商账单核对。
- 整理前main与远端main均为a4595ba；本轮只做本地提交，不推送。实际提交以Git记录为准。清理备份分支保留本机。

完整集成的后续修复不自动覆盖当前E5顺序；若新证据表明它阻断E5，说明原因并重排队列。新机器先完成离线材料/配置检查，再开始有目的的一题。
