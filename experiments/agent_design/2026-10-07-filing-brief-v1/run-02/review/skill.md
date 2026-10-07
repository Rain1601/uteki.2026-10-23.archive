---
name: data-agent-brief
description: Condense an explicitly selected annual report into an evidence-linked bilingual filing brief, prioritizing decision-relevant information and recording important omissions, qualifications and source gaps.
metadata:
  version: "0.1-candidate"
  runtime_status: "not-yet-bound"
---

# Evidence-led filing brief

This is a candidate method shared by Codex and Uteki. It is not yet bound to a production Uteki task. A file on disk does not establish runtime loading or extraction quality. When invoked explicitly, follow the supplied task and available tools; report missing capabilities instead of pretending to have executed them.

Produce a compact, faithful reading aid for a selected company filing. Explain how the business earns money, what changed, the resources it requires, and material qualifications and risks. The Data Agent supplies a shared source-grounded view. Managers own investment theses, valuation, trading decisions and portfolio weights.

## Required task scope

Use an explicit company identity, source manifest with URL/edition/language/content hash, reporting period, information cutoff, reading purpose, and available source units. Keep publication date, reporting period and later updates distinct. An issuer annual report, SEC filing and translation are different editions even if they describe the same fiscal year.

Specify whether the reader is learning the business for the first time or updating a prior brief. Essential stable background in the first case can be compressed in the second only when the prior context is explicitly available.

Use supplied financial records only within their verified scope and review status. If only one report is provided, comparisons can use its stated comparative data; do not claim a year-over-year disclosure change without the earlier disclosure. Record referenced but unavailable exhibits, notes and other documents as gaps. A missing identity or mismatched source stops that scoped task; it is not repaired with a familiar company or latest document.

## Decide what deserves attention

Rank information by what a reader would misunderstand if it were removed, not by chapter order, word count, promotional emphasis or whether it favors the company.

- **Must read:** needed to understand the business and its economic drivers, financial quality, cash needs, material obligations, dependencies, execution constraints or a major risk. Include counterevidence and conditions that would change an apparent conclusion.
- **Watch:** relevant developments, management commitments, uncertain effects or possible changes whose significance depends on future evidence. State what is known, what remains unknown and how an official future disclosure could resolve it.
- **Not expanded in this brief:** duplicate statements, formatting noise or low-relevance detail whose compression does not hide a meaningful qualification. Retain the source and a defensible disposition; do not delete original information.

Unread, inaccessible or ambiguous material is **pending assessment**, never automatically low priority. Importance and evidential confidence are separate: an uncertain but consequential risk can be important. Stable background can still be essential for a first-time reader.

A plan or commitment is not automatically a Watch item: a major planned investment or binding obligation may be Must read while remaining clearly labeled as future or conditional.

Treat business-specific priorities as explicit reasoning from the selected source and task. A reusable completeness checklist may guide scanning, but does not decide importance by itself. Do not label an entire governance, sustainability, legal or footnote chapter useless. For example, resource constraints or governance conflicts can affect the central business model.

Do not introduce universal percentage cutoffs for importance. Quantitative screens can flag items for review when explicitly configured, but small amounts, unquantified events and a concentrated dependency can be decisive. Check the meaning of missing, near-zero or negative denominators before using a ratio. A table of all line items is useful source data, not automatically a readable brief.

## Build the evidence before the prose

1. Inventory the full source: sections, tables and captions, notes, material charts, appendices and references to other documents. Track acquired, parsed, assessed, unread and unavailable units separately. A parsed block count is not proof of semantic coverage.
2. Read through the questions that explain the business: customers and products, revenue drivers, competition and dependencies, earnings and cash, capital allocation and commitments, financial position, accounting judgments, audit/control findings and risks. Adapt depth to the company; preserve a record of reviewed areas.
3. Form concise evidence-backed information items. Preserve actor, entity scope, period, amount/unit/currency, denominator, comparative basis and qualifications. Distinguish reported facts, management explanations, forecasts/targets and analyst interpretations. Company confidence is not an independently established fact.
4. Cross-check apparently positive statements against notes, concentrations, commitments and negative evidence. Distinguish absence of a retrieved result from absence of disclosure. Unresolved contradictions remain visible.
5. Select a readable structure from the assessed items. A useful starting point is a business map, must-read findings, a small financial table, constraints and changes, watch items and remaining gaps. Do not force a fixed number of charts or a compression percentage.

Use existing exact financial records for tables and charts. Missing facts require cited new candidates and review, not guesses. Calculations preserve formula and input references. An investing cash-flow subtotal is not a replacement for capital expenditure; a segment label is not a substitute for a narrower business label.

Use diagrams when they clarify transactions, dependencies or cash conversion. Label analytical causal interpretations and cite their supporting items. Do not draw an unsupported causal arrow as if it were disclosed. If a source chart cannot be read reliably, record a gap rather than inventing its values.

## Deliver readable and traceable results

See [output contract](references/output-contract.md) for the minimum saved information. Keep long IDs and technical paths out of the primary narrative, but retain them in the evidence layer.

Use short sentences, clear subjects and consistent terms. Preserve necessary technical vocabulary with a plain-language definition. “Simplified technical English” is a writing preference, not a compliance claim without the corresponding review. Produce Chinese and English from the same reviewed item set; neither version may introduce extra facts or remove qualifications.

## Review in both directions

Use [review rubric](references/review-rubric.md). Check brief → source for correctness and source → brief for omission. A citation match establishes location, not that the cited text supports the whole claim. Review important exclusions, unread units and evidence against the main narrative.

Programs check identity, hashes, citation targets, actual periods, units, exact amounts and arithmetic when available. Semantic review checks meaning, attribution, qualifications, importance and omissions. Keep these outcomes separate; valid JSON and passing deterministic checks do not prove completeness.

Matching the excerpt or source coordinates does not grant a claim `verified` status. Keep source-location checks separate from semantic support and publication/review state. Illustrative placeholders never have real verified status or an invented source locator.

Revise factual content against demonstrated evidence or acknowledged gaps. Reordering, defining terms and simplifying sentences may follow reading feedback without new source facts, while preserving meaning, qualifications and citations. Preserve the previous output, reviewer issue and revision reason. An unsupported reviewer assertion or teacher answer is not new source evidence. A source gap requires acquisition or an explicit limitation, not a fluent replacement sentence.

## Learn from comparisons

Before sharing answers, freeze common task scope, source bytes, permitted tools and output constraints. Keep producer outputs independent. Hide authors for human review where practical, and inspect raw source for omissions both producers share. Record tool, context, model and budget differences before comparing outcomes.

Adopt specific improved methods, not a model's prestige or an entire unchecked answer. Keep example answers in evaluation artifacts, not general extraction instructions. Validate a proposed improvement on another company or period not used for teaching before making it the default method.

For Uteki integration, the host must explicitly bind the task to this allowed method, load the effective Skill/Prompt/output contract, save their versions and hashes with the actual model configuration, and persist results and review status. Codex uses the same decision rules through its available tools; it must not claim its own extra tools were available to Uteki.
