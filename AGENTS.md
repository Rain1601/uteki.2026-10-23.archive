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
- End every completed task with a short, prioritized next-action list. State
  concrete actions and any required input or authorization; distinguish the
  immediate next step from later work. Do not treat that list as new approval.

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

For Uteki interface work, read `skills/uteki-interface/SKILL.md` and its linked style guide first. It records the agreed company-first, single-window, trackpad-first design rules. Reuse this baseline rather than inventing a new style each turn. Latest explicit user feedback takes precedence. The guide is a baseline, not a claim that current pages passed visual review.
