---
name: data-agent-materialize
version: 2
---
Use the host materialize callback to build a new candidate snapshot from acquired evidence. Preserve company, source policy, cutoff and candidate permissions. Unknown fields stay unknown. Normalization needs explicit units, periods and provenance; do not infer business mappings from examples. Model extracts are verbatim candidate quotes referencing returned context and block IDs, not verified numeric facts. Calculations belong to the query service. New data does not imply adoption or semantic review.

Call materialize with arguments={"source_run_id":"ID returned by acquire in this query"}. The host merges the acquired originals with the current source set, reuses verified unchanged datasets, and validates all required source IDs before switching the active scope. Partial indexing, cancellation or failure preserves the old query scope and a gap. After a successful switch, use the new scoped catalog; append requirements for the new snapshot without rewriting requirements pinned to the old one.
