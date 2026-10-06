# Retrieval acceptance, 2026-09-30

Human-readable results: [召回验收与资料发现边界](../../../docs/design/data-agent-acceptance/retrieval-acceptance-2026-09-30.zh-CN.md).

- Existing run: literal search/read replay matches; five candidate citations match indexed blocks and original HTML; two main capital-investment categories are preserved. This is a bounded content audit, not user sign-off or general recall measurement.
- Offline probes: `literal-probe-results-v1.json`. Evaluator-selected phrases; zero model calls. `capex`, `capital spending`, and Chinese `资本支出` produce no literal match, not a not-disclosed verdict.
- Discovery audit: `discovery-audit-v1.json`, current company/source metadata and interface fields. No global company-alias, industry-membership, or cross-dataset query implementation is inferred.
- Real paraphrase input: `paraphrase-config-v1.json`. Same frozen source/scope, fixed models, shared ledger and limits as the original handoff; only the question changes. No expected answer, page numbers or suggested search terms enter the model input.
- `paraphrase-01`: APIConnectionError before a model decision, two failed transport attempts with unknown costs. Preserved.
- `paraphrase-02`: network-enabled retry, query limited by no-progress after four model decisions. The model proposed 2024/2025 periods; host period grounding omitted 2024 in the reworded question. Later requirement protocol errors prevented recovery. No Worker or source search ran. `period-grounding-replay-v1.json` independently reproduces the parser difference.
- Final Reviewer verdict: `needs_revision / question_coverage=incomplete`, because no established plan or candidate facts existed. One review timeout preceded a successful final configured retry. Across both runs: 8 request attempts, 3 with unknown costs, known estimate $0.801735 (not a bill). Analysis was not run.

No production parser, prompt, source snapshot, original query, adoption status, Analysis or publication was changed. These scripts are explicit experiment runners, not new production search capabilities.

Offline reproduction (use a new output filename):

```bash
PYTHONPATH=src:. .venv/bin/python experiments/architecture_baseline/2026-09-30-retrieval-acceptance-v1/probe_literal_retrieval.py --config experiments/architecture_baseline/2026-09-30-retrieval-acceptance-v1/paraphrase-config-v1.json --query-run experiments/architecture_baseline/2026-09-30-data-handoff-v1/e2e-01/data-query/query --probe experiments/architecture_baseline/2026-09-30-retrieval-acceptance-v1/literal-probe-v1.json --output /tmp/uteki-literal-replay-new.json
```

Next: fix and test period resolution/error feedback under explicit business scope; skip model review when no reviewable facts exist; design company identity and material discovery before claiming multi-company or industry retrieval.
