---
name: data-agent-extract
description: Extract source-grounded financial candidates from explicitly scoped annual filing blocks, preserving reported periods, units, evidence and unresolved mappings.
metadata:
  version: "1"
---

# Annual financial extraction

Use this method for the supplied annual financial extraction task. The host loads this file and the pinned [annual extraction prompt](references/annual-financial-extraction-v2.txt) together. The method configuration, rather than a company name or conversational memory, determines the supported forms and execution strategy.

Prioritize the financial scope explicitly requested by the task and its metric catalog. Read row labels, column headers, unit captions and material qualifications together. Keep the financial framework, consolidated/parent scope, presentation currency and actual fiscal dates distinct. Do not infer a fiscal calendar or substitute an adjusted measure for a reported one.

For a table batch, use only the supplied table and context. A neighboring-block rule does not establish that all necessary notes are present. Request the missing caption or note explicitly. Pending batches and unassigned prose stay pending; no table result proves whole-filing completeness.

Preserve each presented comparative period for requested metrics. If a requested mapping is unresolved, retain source wording and evidence rather than forcing a broader metric. Extra metrics may be retained when useful, but describe their actual coverage accurately. Naming a line in `gaps` does not mean a candidate was retained. Do not say all comparative values were preserved unless the output contains them.

Keep printed numeric punctuation and financial signs in raw observations. Unit conversion is the host's responsibility. A dash or blank does not establish zero without explicit source support. Reported carrying amounts, principal, share capital, shares outstanding and per-share quantities are different observations.

Every relation must reference the actual candidate IDs for its stated relationship. A correct quote does not repair a relation pointing to another measure. Do not present a calculation or missing intermediate item as a reported number.

Return candidate observations, exact evidence, qualifications and specific gaps. Source/format checks, content review and adoption are separate. Review feedback points to issues to re-examine in the source; it is not a source of corrected financial answers. Leave prior versions unchanged.
