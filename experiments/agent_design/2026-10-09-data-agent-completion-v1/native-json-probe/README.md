# Native JSON compatibility probe

2026-10-09. Initial compatibility study used two real requests, the same AIHubMix Messages endpoint and Sonnet model already authorized for this project. Synthetic tasks only; no company source text. No hidden thinking or credentials saved. A subsequent separately authorized envelope probe is recorded below.

| Probe | Result | Local validation | Time | Cost estimate |
|---|---|---|---|---|
| `simple` | HTTP 200, `end_turn`, visible `{"status":"ok","count":2}` | Passed | 1.875 s | $0.000746; 298 input / 15 output tokens |
| `decision` | HTTP 400: compiled grammar too large | No response to validate | 2.624 s | Usage absent; $0.07296 reservation remains unknown |

Both requests use `thinking.type=between_tools`, `output_config.effort=high`, `stream=false`, `max_tokens=1024`, and `output_config.format={type:json_schema,schema:...}`. The shared `../costs.sqlite` ledger records both requests. The second reservation was not released as zero. Request/response receipts and manifest hashes are retained in each probe folder.

## Conclusion

AIHubMix accepts native JSON format for this model, but the entire AutonomousDecision grammar is too large. This is a transport-format blocker, not evidence that a different business prompt is required. The full transformed schema contains 61 optional properties and 31 union nodes. Anthropic documents limits of 24 optional parameters and 16 union parameters.

The original schema and probe-only transformed schema are saved separately. The transformation drops unsupported bounds/conditional constraints and closes open objects. Closing open objects restricts some action payloads, so this transformation is **not production-ready**. Even after this simplification the provider rejected the grammar. No third probe was attempted.

## Minimal engineering options

1. Use a small provider-enforced JSON envelope (for example action plus a payload string), then parse and validate the payload against the original AutonomousDecision locally. This avoids whole-message XML and large grammar compilation. It does not guarantee the inner payload is valid; retain strict local validation and bounded repair. The subsequently authorized implementation and live probe are recorded below.
2. Expose one native `submit_decision` client tool with `tool_choice:auto`, consume exactly one matching `tool_use.input`, then perform original strict host validation. The adapter must not execute a provider-requested action before validation. This tool-specific compatibility has not been probed.

Do **not** force `tool_choice:any` or `tool_choice:tool` for Sonnet 5.5 or Opus 5.5: current official documentation explicitly states these models reject those choices with 400. Do not claim auto guarantees a tool invocation. Do not turn on strict tool grammar with the same oversized full schema and expect to avoid the grammar limit.

## Implemented envelope and additional validation

After the initial two-probe limit, the coordinator explicitly authorized implementing a small native envelope and one additional compatibility call. `claude_messages.py` now offers opt-in `schema_protocol=native_decision_envelope`. The wire fields are action, requirement_ids, reason and payload_json; all are required, with no additional properties and only two nullable unions. Original decision constraints remain in the system instructions and local schema validation. Original wire text stays separate from the decoded SDK response.

The new envelope passed seven focused unit tests alongside 24 existing transport tests. These checks include malformed XML, duplicate keys, non-finite numbers, unexpected fields, action/payload mismatch, array and string payloads, exact configuration fingerprints and unchanged legacy behavior.

One additional real metered request succeeded: HTTP 200/end_turn, 3.085 seconds, 10,320 input and 70 output tokens, estimated $0.02134 recorded in the same shared ledger. `envelope/visible-wire-response.json` preserves the native JSON; `envelope/host-decision.json` preserves the strictly validated discover_catalog decision. The returned action was not executed. This demonstrates endpoint/format compatibility on one synthetic request; it does not establish production task success or a long-run reliability rate. Known estimates across the successful probes total $0.022086; the prior failed grammar request still retains its $0.07296 unknown reservation.

Sources: [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), [Forcing tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools#forcing-tool-use). Local Anthropic SDK is not installed; this probe used the existing credential loader, exact approved endpoint, local pricing snapshot and shared RunBudget.

## Approval audit

The first execution request was automatically rejected as a possible new export of an internal schema. No request was sent. A second approval review included evidence that the same schema was already sent in every authorized r2 system prompt (`autonomous_model.py` output_type and `claude_messages.py` schema serialization). That review approved the original command. No alternate execution path bypassed the rejection.
