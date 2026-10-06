# Semantic review v3 heldout fixtures

Evaluation status: the first frozen heldout execution is preserved in
`heldout-run-01`. Its failures subsequently informed generic evidence-feedback
changes, so subsequent runs of these cases are **development regression**, not
unseen heldout evidence. The cases and expected hashes below remain unchanged.

Two synthetic Northstar Medtech cases use independent source snapshots and explicit
fiscal dates. `sv3-001` covers calendar FY2026/FY2025, equal net-income and operating-cash-flow
values, and an available adjusted-operating-income reconciliation. `sv3-002` covers
June-year-end FY2024/FY2023, a historical segment recast, the explicitly bounded
current/prior consolidated exception, and an adjusted-cash-earnings measure whose
reconciliation is not present in the supplied excerpt.

The eight assertions have five supported, two contradicted and one insufficient-evidence
expectations. Model inputs are only the `packet` objects in `cases.json`; `expected.json`
is independent scoring material and must never enter reviewer, critic or revision
requests. Case IDs remain manifest metadata. The packets use input v3, the unchanged
V2 output schema, table-row anchors and host-derived context inventories.

Prepare a new run directory by validating each packet with `validate_semantic_packet`,
writing its unchanged JSON to `packets/001.json` and `packets/002.json`, and creating
the normal `semantic-review-input-manifest-v1` manifest. Use `source_origin=synthetic_fixture`,
`dataset=null`, `scope=null`, and per-packet `case_id/path/sha256/packet_id/record_ids`
references. Seal all written files. Do not use the old benchmark preparation function,
which defaults to v1, or reconstruct packets from expected answers.

Frozen before model execution:

| Artifact | SHA256 |
| --- | --- |
| cases.json | `3c8d11f9b4a1daa7a61e309ba8577effc4b6045d757cb08c5e33eb65db6414cb` |
| expected.json | `c4bac353aa3c3f89c9c167c4e81dc71b89d5fdb842ed8cb00e6bcfabbb3e1b39` |

No model calls were made while preparing these fixtures. Preserve v1/v2 cases and
expectations. Do not change these expectations in response to model output. If a
failure guides further prompt or implementation tuning, treat this suite as a
development regression set and use a new unseen suite for subsequent heldout claims.

The critic is another model opinion, not independent ground truth. Score initial and
revised proposals separately against the frozen expected assertions, original quotes,
record coverage and fiscal/entity boundaries. Also report critic false positives,
missed errors, cancellations and total calls. A critic pass and schema acceptance do
not establish semantic correctness. Unresolved note references do not prove that a
complete note was or was not delivered; context requests remain unverified questions.
