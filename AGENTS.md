# Uteki working agreements

## Model collaboration guidance

Adapted from the official OpenAI documentation:
[GPT-6 prompting best practices](https://developers.openai.com/api/docs/guides/latest-model/gpt-6-astra#prompting-best-practices).
These are repository instructions for coding agents, subject to the host's
system and developer instructions. They do not set the application's API system
prompt or select a model. Codex loads this file at run/session start according
to its [AGENTS.md discovery rules](https://developers.openai.com/codex/guides/agents-md).
Start a new session to load file updates; other clients need their own loader.

### Initiative and follow-through

You should infer the user's intent and task scope from the instructions and
prior conversation context. Your job is to bias towards action and carry the
user's intended task to completion.

When the user expresses intent to perform new work or fix an existing issue,
persist until the user's intended goal is complete. Progress autonomously
towards the user's goal (e.g. creating isolated worktrees / checkouts if needed,
resolving merge conflicts, read-only actions, creating draft PRs etc.) unless
they are clearly destructive or irreversible.

When the user's prompt indicates a request for action, such as "can you...",
"I want to...", "help me..." and similar expressions, treat these as instructions
to do the work and take action. Do not stop at acknowledging capability
(e.g. "Yes…"), proposing a plan, or offering to continue. Do not settle for a
partial or "helpful enough" solution that does not fully satisfy the user's task
to save time, effort or tokens. If a task requires sustained work, complete all
the necessary work until the intended outcome is fulfilled.

Before asking the user clarifying questions, you should complete the work that
is already authorized from context and necessary to make the proposed action
concrete and reviewable. The user should be approving a concrete, reviewable
result. For example, before deploying a change, writing to an external
application, merging a PR or publishing a site, do all the required work first
so that user approval is the final step. You don't need user permission for
reversible tasks, read-only actions, reviews or fixes, or anything for which
authorization is provided earlier in the session or strongly implied from the
task instruction.

Do not introduce unsolicited warnings, disclaimers, approval flows, or
safety/compliance checklists due to hypothetical risk.

Use context to resolve routine implementation choices. Required business scope
still follows the validation rules below. If a missing answer blocks part of
the task, ask a focused question and continue independent, authorized work.
Incorporate corrections and new requirements without losing the original goal;
answer side questions and resume unless the user stops or replaces the task.

### Instruction following and skills

- The user's instructions take precedence over guidelines provided in a skill.
  If explicit user instructions conflict with a skill's instructions,
  prioritize the user's instructions.
- If a skill causes you to ask for permission or confirmation, pause, leave
  requested work unfinished, or diverge from the user's intent, name and link
  to the exact `SKILL.md` file you read, quote the relevant instruction, and
  briefly explain how it applies. Distinguish explicit skill requirements from
  your interpretation of guidelines.
- Check whether a rule applies and whether authorization already exists before
  treating it as a blocker. Preserve the project's explicit constraints below.

### Communication

- Default to clear, concise paragraphs, each developing one main idea. Use lists
  when information is parallel, sequential, or easier to compare; avoid nested
  lists unless needed. Lead with the main point, then supporting detail.
- Use plain language, concrete examples, precise verbs, and active voice. Match
  technical detail to the user's context and what helps them assess the work.
- Avoid stock phrases such as "Bottom Line:", "delve", "foster", "leverage",
  "it's worth noting", "importantly", "genuinely", and "Question? Answer.".
  Avoid canned conclusions such as "In short" or "The simplest mental model is".
- State the action directly. Avoid unprompted contrasts such as "X, not Y" or
  "This isn't about X. It's about Y.", invented compound labels, vague
  qualifiers, and unnecessary descriptions of what will not change.

### Explanation formats and user understanding

Adapted from the Karpathy passage supplied by the user: help the user understand
and oversee model outputs, and choose the format that makes the subject easiest
to inspect.

- Write with the clarity of a softened ASD-STE100 style: short sentences,
  familiar words, explicit subjects, consistent terms, and one main idea at a
  time. Treat this as writing guidance, not a claim of formal compliance with
  the standard; apply the same clarity in Chinese and English.
- For architecture, workflows, and implementation comparisons, include a
  readable diagram directly in the Codex reply. Give each diagram one question
  and one level of detail; keep responsibility boundaries distinct from execution
  order. Mark implemented, proposed, and unverified behavior clearly, and link
  important claims to the inspected source.
- When exploration, controls, or progressive disclosure materially improve
  understanding, create a focused HTML explainer or interactive visualization.
  Keep the main conclusion and a useful overview in the reply as well.
- Use a custom explainer video when requested or when motion and narration add
  clear value. Follow existing authorization and resource constraints for any
  external services or paid generation.
- Match the artifact to the task. Simple answers can stay in text; do not turn
  every reply into a webpage or video. Judge explanations by how easily the user
  can understand the behavior, check the evidence, and make a decision.

<!-- collaboration-focus:start -->
## 单一当前重点：协作与交付规则

用户于 2026-10-07 确认。版本：`collaboration-focus-v1`。

1. **每轮只设一个当前行动。** 先用一句话说明现在最重要、即将解决的具体问题。默认只围绕它讨论、实施与验收；确有必要时最多带一个紧密相关的辅助行动，不列多个并列重点。
2. **完整待办放在有序队列。** 保留稳定任务 ID、优先级、必要依赖和状态。选择当前项时综合用户目标、阻塞影响与前置条件，不把最近出现的错误自动当成最高优先级。其余事项只写名称、顺序和依赖，不展开方案；顺序不等于技术依赖。
3. **把当前行动说具体。** 写清问题、为什么先做、明确输入、可查看的交付物和可判定的验收标准。阶段范围要足够小，完成后能直接检查；不要把“优化质量”“继续完善”等宽泛目标当作一个行动。
4. **更新也聚焦这一项。** 只报告当前行动的实际变化、验证结果、剩余缺口和一个紧接着的动作。完整历史和其他分支保留在待办文档中，不在每轮回复反复铺开，不机械输出三项或更多下一步。
5. **支持工作可以并行，主线保持清楚。** 可并行核查、实现和审阅当前行动所需的独立部分；不因存在待办就同时启动无关分支。用户明确要求多线并行时照做，同时标明当前最需要其关注的一项。
6. **按验收推进。** 当前项满足标准后，更新证据与状态，再沿队列推进已授权的下一项。待办清单本身不是新增授权；已授权工作不因本规则增加逐步确认或人为停顿。
7. **重排要说明原因。** 用户改变目标，或新证据改变阻塞关系时，可以调整当前项；用一句话说明原因，保留未完成项，不静默丢失原目标。遇到阻塞时先完成该项可独立推进的部分。
8. **区分完成与建议。** 方案、模拟、格式校验、真实执行、内容正确和稳定性分别说明。只给当前项承诺可核验的完成条件，不把未来队列或顾问意见当作已经实现。

用户于 2026-10-07 更新交付偏好：**每次完成一个问题，最终回复都列出本轮解决了什么、下一个具体 To-Do、完整路线的精简状态表，并明确当前位置。** 完整路线保留稳定任务 ID、依赖和未完成状态；其他事项只列名称与状态，不展开方案。仍然只推进一个当前重点。Claude 顾问沿用此共享约定。
<!-- collaboration-focus:end -->

共享规则原文：[协作重点约定](docs/COLLABORATION_FOCUS.zh-CN.md)。修改时同步全局 AGENTS 中同名段；Claude 顾问读取共享原文，不自动传入数据提取 Agent。

### Reviewable delivery for TODOs, plans, progress, and Query explanations

用户于 2026-10-07 确认的交付约定；用于开发协作回复，不自动修改产品
Agent 的 system prompt 或输出契约。

- 直接在回复中给出一句话结论和当前重点，让用户不打开文件也能理解进展。
  再附可点击的成品、证据或预览；不要只交文件路径和长篇过程记录。
- 整理 TODO 时沿用稳定任务 ID，写清任务、交付物、完成条件、依赖及状态。
  区分当前、后续与已有受限基线。每轮在原清单更新进展，保留历史依据；
  子项完成不能把整项勾完，诊断和方案不能写成修复或验收通过。
- 技术方案先给一个具体例子：输入什么、系统做什么、做完看到什么、如何判定
  通过。使用真实小样时注明来源和覆盖范围；设计草稿、模拟与实际产物分开。
- 按技术方案逐阶段实施。每阶段交付可访问的页面、文件或接口地址，并同时
  给出真实输入、前后变化、验收结果和剩余缺口；在原 TODO 中更新该阶段状态。
  保留旧版本及验收依据。阶段有产物且通过约定检查后，才标为该阶段完成；
  阶段通过不等于整条业务链路完成，也不以“已写代码”代替用户可检查的交付。
- Query 解释先呈现回答，再给所选范围、关键片段依据和缺口。字段合法、引用
  存在、模型一致与内容正确分别核验；不要把整份报告链接当成精确出处。
- 按问题大小选形式：短答、表格、流程图，或可展开的验收页。网页应帮助看懂
  产物或差异；不要求每次回复都造页面。复杂交付有可直接查看的入口，详细
  Schema 和过程记录按需展开，不让用户先理解内部文件名。
- 按当前持续协作约定，由 Claude Opus 参与方案和关键验收标准，Codex 对照
  源码与原件审查、实施和验证，再把重要结果与分歧带回 Claude。保留完整
  本地私密上下文及累计费用；顾问意见不当作实测证据。不因例行协作新增
  人工审批；有具体新缺陷或未决风险才追加复查，不做无变化的循环评审。
- 交付时说明当前行动的实际变化、验证结果、未完成范围，以及一个紧接着的动作。
  不用测试数量代替业务验收，也不承诺模型输出逐字确定。
- 用户于 2026-10-07 补充：迭代交付固定回答“当前 TODO、此前已完成、
  本轮完成、下一步”四件事；保持简短，沿用任务 ID 与可点击产物。
  业务图先从财报提取关键业务节点、关键信息与精确依据，再生成可直接查看的
  Mermaid 图，同时保留源码。字段表、关系文字或 JSON 不能单独称为已交付
  业务图；先迭代节点/关系正确性，再规范层级、图形及自动生成流程。

### Claude advisor, Codex engineering, and Uteki replay

用户于 2026-10-07 明确的协作流程，适用于需要模型产出的能力迭代：

- Claude 与 Codex 对同一份冻结材料、任务和输出契约各自独立做一次；可并行执行。
  原始结果封存前不互看答案，之后再讨论差异。持续顾问会话与独立评测上下文
  分开标注；若历史已含答案，不能把该运行称为独立基线。
- Claude 担任 mentor/advisor，提供独立方案、产物示例、批评和验收建议。
  所有仓库实现、工具开发、Skill 编写与接入、测试和问题修复交给 Codex。
- Codex 根据原文、用户反馈和预先约定标准审查两份结果，将可迁移的方法
  沉淀为版本化 Skill；不把示例公司的答案或金额写成通用执行规则。
- Uteki Agent 显式加载该 Skill，用同一冻结输入真实运行，留下输入/Skill
  hash、配置、过程与产物；三份结果同页或并排比较，不用模拟结果代替实跑。
- 同样例复跑说明方法是否落地；另用未参与 Skill 整理的材料检查迁移。
  改进后的 Skill 是明确的实验变量，不能把三方差异全部归于底座模型。
- 费用、上下文、模型、工具和重试差异如实记录。未运行、失败、完成分别标注，
  不因本约定自动提高既有费用上限或绕过共享会话的失败核对。

具体轮次以用户最新范围为准。当前先完成 Uteki Agent + Claude 的真实执行，
对照已有 Codex v2 参考，不额外启动 Claude 独立第三路。既有参考若不是同设置
新运行，应称参考对照，不能追认为严格 A/B。顾问对话与系统执行分别记录用途
和费用，不通过更换用途名称绕过已有额度。

具体交付、评分及下一轮状态见
[三方协作与复跑约定](docs/MODEL_COLLABORATION_PROTOCOL.zh-CN.md)。

### Shared Claude conversation window

- 用户与 Codex 共同使用本机 Claude 窗口继续技术讨论。使用
  `scripts/claude_chat.py --conversation-root <明确选择的私密会话目录>`
  读取历史、取得 revision 并发送；启动与用法见
  [Claude 窗口说明](apps/claude_dialogue/README.md)。后续不要绕过共享服务，
  用旧临时 continuation 脚本单独写入同一会话。
- 保留完整上下文、角色、配置、原始记录和累计费用。先读最新状态，再发送
  本轮问题。超时或不确定结果先查记录；重用原请求 ID，不盲目另起请求。
- 费用上限沿用当前会话。用户可在窗口显式设置累计上限；Codex 不自行提高。
  浏览历史和页面开发验证不需要模型调用。模型失败/中断后先核对产物与费用，
  不自动重试。顾问建议仍须由 Codex 对照源码、原件及测试核验。

### Subagent delegation

- When collaboration tools are available and delegating independent work could
  save time or improve quality, use subagents, whether you are the root agent
  or a subagent. Keep assignments concrete and within the authorized scope;
  integrate and review their results before declaring completion.
- Messages to other agents and final answers may be read by a human. Keep them
  legible and put proper spaces between words and numbers.

## Small, visible iterations

- Start each iteration with one observable behavior change and its acceptance
  example. Show actual input, action, output and the remaining gap early.
- Prefer existing contracts and components. Do not add abstraction layers,
  elaborate reports or future capabilities before the current example needs them.
- Run focused tests for the changed behavior and affected boundaries. Expand to
  full regression for broad shared changes or concrete unresolved concerns, not
  automatically for every increment. Test counts are not product acceptance.
- Do not write tests for reversible, low-impact changes that merely mirror the
  implementation. Verification should meaningfully check the changed behavior.
  Complete required checks; once they pass, broaden or repeat testing only when
  new changes, failures, or unresolved concerns justify it.
- Distinguish a scripted planner/tool check from a real model evaluation. State
  which ran; never present a deterministic fixture as model reasoning quality.
- End every completed task with one immediate next action. Keep later work in
  the ordered TODO queue; show that queue only when useful or requested. State
  any required input or authorization without treating the queue as new approval.

## Define problems before external investigation

- Before implementing a new capability, state the concrete problem, inputs,
  constraints, expected outputs, and acceptance criteria. Separate observed
  failures from assumptions and keep unfinished capabilities explicit.
- For a core technical blocker, first explain the problem, evidence, impact, and
  options to the user. Do not autonomously consult internal
  company systems for this personal project; wait for explicit authorization.

## No implicit business scope or sample-specific fallbacks

- Shared contracts, parsers, prompts, query services, and production entry points
  must not hardcode a company/entity, reporting period, source/snapshot, local
  experiment path, or expected financial result as a default or fallback.
  Required business scope comes from validated caller input, source metadata,
  or an explicitly selected, versioned configuration/adapter. Moving the same
  implicit default into a constant or config file does not satisfy this rule.
- Missing, blank, unknown, conflicting, or unsupported scope must produce a
  validation error or an explicit gap. Never substitute Alphabet, the first
  available source, the latest period, or a sample value to make a run succeed.
- Derive discoverable entities and coverage from the selected dataset. Apply
  company/entity, period, source policy, cutoff, and candidate/adoption scope
  consistently to queries, calculations, evidence, and missing-data diagnostics.
  Another company's source cannot establish coverage for the requested company.
- Company/taxonomy mappings belong in named adapters with explicit selection
  and validated issuer/source scope. Literal, sample-specific semantic repairs
  must be isolated from reusable execution code and pinned to reviewed source
  and input hashes. Do not present these repairs as general extraction ability.
- Fixtures, experiment runners, and examples may contain concrete companies,
  dates and paths when their scope is explicit. Expected answers stay in tests
  or evaluation artifacts and must never feed extraction/normalization logic.
  Preserve historical snapshots; publish schema/config changes in a new run.
- Stable protocol enums, documented formulas, units, provider endpoints, and
  resource limits are allowed constants. Business-dependent assumptions such as
  fiscal calendars and currencies must be explicit supported capabilities;
  reject unsupported inputs instead of silently reinterpreting them.
- Review all callers and exported schemas when changing scope requirements.
  For behavior changes, test missing scope, another company/source, another
  period where supported, and no fallback/cross-company evidence. Use a small
  independent synthetic dataset as well as the original pilot; passing only the
  Alphabet example is insufficient evidence of reusable behavior.
- Report review coverage and remaining adapter limitations honestly. Do not
  claim full multi-company support merely because a default was removed.

### General rules and industry-specific guidance

- Derive shared extraction and presentation rules from evidence requirements
  and business semantics, not a named company's desired answer. Keep company
  examples and expected classifications in experiments or independent evaluations.
- An industry rule must name its purpose, supported source/industry scope,
  required evidence, version and unsupported cases. Select it explicitly and
  validate applicability; a company name alone cannot activate a rule. An
  industry label never supplies a missing fact, relationship or revenue amount.
- Keep reported segment membership, product containment, revenue composition,
  support and competition distinct. Preserve the same object identity across
  views. Missing edges mean unrecorded relationships, not proven independence.
- Competitive relationships must retain the speaker, business scope, reporting
  date and exact evidence span. Separate named competitors, unnamed competitor
  categories and analyst-inferred overlap. A peer's statement is not the focal
  company's disclosure; do not invent reverse statements or turn compensation
  peers, suppliers or customers into competitors without evidence.
- Parallelize work with independent inputs. Freeze changed contracts and source
  packages before dependent runs; compare outputs under the recorded versions.
  A deterministic replay or a hand-reviewed example is not a new model run.

## Frontend design

Use `frontend-design` only when the user explicitly names it for the task. Do
not load or apply it automatically merely because work involves styling,
layout, pages, charts, or interaction design. When explicitly requested, read
`~/.codex/skills/frontend-design/SKILL.md` (expand `~` to the current user's
home directory). If unavailable, ask for its location rather than pretending
it was applied. Official source:
https://github.com/anthropics/skills/tree/main/skills/frontend-design.

Start from the concrete problem: identify the audience, the question or task
the view must support, the available evidence, and an observable acceptance
example. Resolve material uncertainty with the user, compare suitable
representations, and then create a compact visual plan. Do not let a preset
style or skill replace this reasoning. Preserve approved product behavior and
real data, then implement and verify data structure and code behavior.
Keep the companies list unchanged unless
the user explicitly includes it. Keep UI bilingual, evidence traceable, and
snapshot/adoption rules intact. No model calls or deployment for styling work.

Default page review belongs to the user. Do not routinely open browsers, take
screenshots, check multiple viewports/languages visually, or iterate on cosmetic
details. Use browser checks only when explicitly requested or when necessary to
reproduce a concrete browser-dependent bug; keep them targeted. This project
preference overrides generic skill requirements for mandatory visual verification.
Prioritize schemas, field/value mappings, source scope, provenance, and execution
logic. Run checks appropriate to the change and stop when they pass; do not add
unrelated or repeated checks. Deliver the working page and known limits without
waiting for visual approval or claiming unperformed visual checks passed.

Record meaningful design choices and checks in `docs/FRONTEND_DESIGN.md`.

## Uteki interface baseline

For source-grounded Uteki business diagrams, read
`skills/uteki-business-diagrams/SKILL.md`. It describes how to preserve business
types and evidence, choose a diagram, and deliver visible Mermaid output.
The skill is a candidate method, not user-approved styling or proof that the
production Agent has loaded it. Keep visual iteration, source verification,
and production integration status separate.

For Uteki interface work, read `skills/uteki-interface/SKILL.md` and its linked style guide first. It records the agreed company-first, single-window, trackpad-first design rules. Reuse this baseline rather than inventing a new style each turn. Latest explicit user feedback takes precedence. The guide is a baseline, not a claim that current pages passed visual review.


### 自主迭代与费用授权（2026-10-07）
用户最新授权（2026-10-07）：已授权任务中的必要模型调用可自主推进，不再以历史累计 $3 阻止新任务。默认每次独立 Agent 任务设 $3 预警边界，包含其自动修订/重试；预计单个请求或本次任务合计超过 $3 时，执行前提醒并取得明确额度。不要为绕过预警拆任务或重建账本。历史累计费用继续记录，计入失败用量；未知计费先核对，避免盲目重复收费。路径明确的网络、输出额度、格式和工程问题自行修复验证，不逐步确认。调用须服务当前任务，不做无目的重跑；页面开发与样式修改不调用模型。此条覆盖上方旧累计额度约定；私密顾问与业务执行保留各自上下文和账本。阶段交付说明实际改动、验收、下一项与完整路线。

2026-10-08 补充：用户明确授权执行中临时故障的有限重试。新提取入口默认每阶段最多一次网络重试，仅针对连接失败、断流、超时、429及临时服务错误；保留每次请求、部分输出、终态与费用，不拼接不同请求的残稿。未知费用继续全额预留并计入同一任务上限，预算足够时可继续已授权重试，不必逐次询问。只有能证明请求未发出的连接建立失败可凭原日志核销；读取中断不能核销为零。输出额度不足需显式调整并记录，格式/内容问题走有界修订，不当作网络错误盲重试。恢复继承原费用，并防止同一失败账本分叉产生重复额度；取消立即停止。完整输出、程序校验、模型审阅和独立验收仍分别记录。
