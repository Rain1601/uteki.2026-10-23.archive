---
name: uteki-interface
description: Design and refine Uteki company research interfaces using Rain's established visual and interaction conventions. Use for Uteki UI work or when explicitly asked to reuse this style in another project.
---

# Uteki interface

Read [the style guide](references/style-guide.md) before changing UI. It is the maintained design baseline; the current screenshot or latest user correction takes precedence over it.

The intended product is a company research workspace: compact, calm, readable, with stable panels, explicit click navigation and native scrolling for reading. Rain should not need to specify type sizes, spacing or animation mechanics repeatedly.

Before editing, identify the page's main object and the existing component to reuse. Prefer shared tokens and a scoped component rule over another late CSS override. Do not redesign unrelated pages or treat styling as authorization to change research conclusions, adoption or data.

Default to validating data structures, field mappings and code behavior; the user reviews the page visually. Do not routinely run browser/screenshot/viewport reviews. Use the guide's visual checklist only when the user explicitly requests visual review or a concrete browser-dependent bug requires targeted reproduction. Separate implemented behavior, automated checks and any actual visual checks; user visual review does not block delivery or other authorized development. Never call tests visual approval. Do not infer approval to publish from this skill.

When a user changes a recurring preference, update the relevant rule in the guide instead of accumulating contradictory exceptions. Keep project-specific lifecycle and data requirements in the repository.
