# v4 heldout independent evaluation 01

Two frozen synthetic cases used 4 reviewer calls and 1 critic call. This independent evaluation used no model calls and changed neither the frozen cases nor scoring key. Input/run manifests and key SHA256 were verified.

| Case | Initial labels | Revised labels | Host outcome | Independent outcome |
| --- | --- | --- | --- | --- |
| Harbor | 3/4 | 3/4 | Rejected twice | Not accepted |
| Juniper | 4/4 | 4/4 | Accepted after citation repair | Fail |

Initial and revised labels each total **7/8**. Independent case passes: **0/2**. Label correctness on rejected drafts is diagnostic, not accepted-case success.

Harbor's revision selects the actual duplicate row by offset, but dimensions claims still omit record rows. Its missing-evidence/contradiction confusion and overstatement that the adjusted metric applies only to FY2022 remain unchanged. The source also displays the FY2021 adjusted amount. No critic ran for this case.

Juniper adds table-row evidence to the two supported assertions and passes the host's mechanical checks. Recast scope and labels are correct. However, the unchanged free text says “Note 9内容未提供”, establishing document delivery absence from an unresolved reference. The frozen negative condition disallows that inference. This finding concerns delivery-state wording, not a claim that the issuer never published the note. The evidence supports an unresolved definition, and the insufficiency verdict itself is correct.

The single critic returns pass with no issues; independent review identifies one missed semantic case and zero observed false-positive issues. This tiny sample is not a general critic accuracy estimate. Neither revision changes semantic conclusions: one is partial offset repair, the other successful claim-local citation repair.

Artifacts:

- [Run](../../../data/company_workspace/record_review/semantic-loop-v3/heldout-v4-run-01/result.json)
- [Independent notes](../../../data/company_workspace/record_review/semantic-loop-v3/heldout-v4-independent-notes-01.json)
- [Independent evaluation](../../../data/company_workspace/record_review/semantic-loop-v3/heldout-v4-independent-evaluation-01.json)

Next: review the unresolved-reference wording boundary and generic repair behavior before any further authorized run; preserve this run and frozen scoring key unchanged.
