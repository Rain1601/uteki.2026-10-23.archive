# TODO 05 / 08：系统 Agent 精编小节试跑

本轮交付正式 `filing-brief-v1` 契约、通用执行入口和消费者。输入是显式选择的冻结原文；不读取旧业务图、人工精编、参考答案或顾问历史。当前真实案例是 Microsoft FY2025 10-K 的完整 Operating Segments 小节，103 个输入块。整份报告尚未完成精编。

## 看什么，怎样算通过

输入：原始公司、报告版本、期间与内容 hash 已验证的 source packet，加 [阅读任务](input/task.json)。系统执行“生成精编 → 原文和自身候选的双向自检”。每阶段最多一次临时网络重试，全部调用共用 $3 账本；失败原文和未知费用预留保留。

产物：同一组内容项 ID 对应中文、英文精编；每个声明有说话方、期间、原文或推断类型、重要性理由、限定及精确引文。原文块可直接打开。每个输入块有 included / compressed / context / layout_noise / unprocessed / unsupported 处置。未读、未知和原文明示未披露分别保存。

通过要求：字段与源文绑定成立；来源到精编的重要披露没有未解释遗漏；精编到来源的主张保留范围与限定；两种语言不增删事实。程序检查位置和绑定，模型自检检查全部内容项、原文块和缺口。模型自检通过仍不是 Codex 的独立内容验收，更不是整文精编完成。

## 实际结果（2026-10-08）

系统 Agent 已真实生成并修订小节精编：[打开阅读页](http://127.0.0.1:8769/docs/design/data-agent-acceptance/microsoft-filing-brief-v1/)。共 22 个双语内容项、103 个原文块处置、2 项缺口。最终可读稿来自 Sonnet 根据 Opus 审阅的自主修订，Codex 没有编辑模型答案或把具体公司纠错传入执行器。

| 轮次 | 实际结果 | 费用（估算，非账单） |
|---|---|---|
| run-01 / Sonnet 生成 | 完整返回；6 处覆盖映射缺少对应引文，被程序拒绝 | $0.289796 |
| run-02 / Sonnet 机器错误修订及自检 | 位置校验通过；Sonnet 自检 pass，但 Codex 内容复核未通过 | 累计 $0.805628 |
| run-03 / Opus 初审 | 12k 上限截断；有用量，原文保留，不采用不完整审阅 | 累计 $1.267472 |
| run-04 / Opus 初审恢复 | 24k 上限、缩短理由；发现 17 处引文问题及 7 处重要内容遗漏 | 累计 $1.711376 |
| run-04 / Sonnet 内容修订 | 完整新稿；重要引文和用途/范围问题明显修复 | 累计 $2.095028 |
| run-04 / Opus 最终复核 | 发网前被 $3 保守预留挡住，未发请求、未收费 | 无新增费用 |

全部轮次共享 `run-01/budget.sqlite`，没有复制或重建费用上限；共 6 次实际请求、未知费用 0。一次格式修订、一次内容修订均有唯一后继认领。12k 截断是输出上限问题，不是网络重试；`output_tokens` 包含 adaptive thinking，不能把可见字符长度当成完整计费用量。

[最终复核预算明细](final-audit-budget-block.json)：剩余 $0.904972；该请求保守预留需 $1.244444，已用加预留为 $3.339472，因此没有发网。这不是实际支出已经超过 $3，也不是新的未知费用。

Codex 已独立重读新稿的全部 22 项双语内容及实际摘录。主要引用与重要内容已补齐；仍保留小范围缺陷：中文把 sponsored content 写成“推送内容”，GitHub 云子集的列举措辞可更明确，游戏平台触达范围仍分散。故 [独立复核](evaluation/independent-review-round2.json)仍记为 `needs_revision`，未把“比上一版好”写成完整通过。Opus 最终复核尚未运行，不能套用修订前的审阅状态。

## 可查看入口

- [正式 JSON Schema](filing-brief.schema.json) 与 [自检 Schema](filing-brief-review.schema.json)。
- [预检记录](preflight.json)：输入 hash、真实请求 hash、配置和费用预留。
- [最新运行结果](run-04/summary.json)：保留最终模型复核预算阻止；新稿仍可检查。
- [中文精编](run-04/revision/brief.zh.md)、[English](run-04/revision/brief.en.md)、[原文索引](run-04/revision/evidence.html)。
- [完整 Opus 初审](run-04/audit_initial/review.json)、[旧 Sonnet 自检](run-02/review/review.json)、[修订前独立复核](evaluation/independent-review-round1.json)。
- [输入隔离核对](input-isolation-check.json)、[原 trace 发表 hash 核对](provenance-check.json)、[剩余费用预检](remaining-path-preflight.json)。

运行中断、格式失败或覆盖问题均保留状态，不人工编辑模型产物补成“通过”。新尝试发布新目录；不能通过重建账本绕过同一次任务费用。

## 实现与读取

- `src/uteki/agents/filing_brief/contract.py`：正式类型、源文归属、hash、引用和覆盖校验。
- `src/uteki/agents/filing_brief/run.py`：原件 DOM/文本核对、Skill 加载、生成、自检、观察日志和费用。
- `src/uteki/agents/filing_brief/consume.py`：先验证契约，再将同一内容项渲染为双语 Markdown 和固定原文索引。
- `scripts/run_filing_brief_agent.py`：调用方必须指定 packet、task、skill、model、output、observation-root、budget。

本版本支持现有完整 HTML 小节 source-packet 验证能力，复用原有严格范围和 DOM 校验。没有宣称 PDF、全财报或所有公司完整支持。`source_language` 是显式任务输入；中文/英文是派生阅读层，原文语言不改写。

模型真正加载的 Skill 字节、Schema、请求、配置、响应、源文和 task 都保存到运行目录。Skill 主文件是候选方法；这次显式 runtime 绑定不自动将全局 `runtime_status` 改成默认生产发布。格式合法、模型自检和独立语义验收分开记录。

## 已完成与下一步

此前只有人工局部设计例。本轮新增可真实运行的正式契约与执行器。离线合成检查包含缺失/跨公司/跨期间范围、引用与覆盖错误、source hash 修改、缺口状态、输出截断、无用量、费用阻止、断流重试、共享账本、唯一后继、模型切换和发表 hash 篡改拒绝。这些不是模型质量评测。

最终 21 项离线检查通过；页面的 199 个链接、22 个内容锚点和 103 个原文锚点已核对，本机页面 HTTP 200。没有浏览器截图或视觉验收。所有 6 次真实模型阶段的关键文件均已与原 trace 的 `artifact.published` hash 对上。后续恢复入口强制同类检查，并拒绝切换至另一任务账本。

当前：已有真实候选和独立内容复核，最终模型复核未运行且仍有少量内容缺陷。后续：处理这些实测缺陷，再扩展完整报告和另一公司的迁移检查。05 的“精编正式契约、真实生成与消费”子项已实现；08 的小节质量和整文验收尚未完成。

运行中发现旧 summary 的 `self_review` 会沿用修订前状态。历史 JSON 原样保留；新执行器会在新稿出现后清空该状态，并绑定 `reviewed_brief_sha256`。阅读页只采用 hash 与当前稿一致的审阅，不将旧候选 verdict 显示为新稿的判定。
