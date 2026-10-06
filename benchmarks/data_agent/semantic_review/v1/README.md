# Semantic review fixtures v1

Twelve independent synthetic Cedar Instruments cases cover restated comparability,
allocated segment profit, overlapping revenue categories, year and unit errors,
missing adjusted-profit definitions, and geographic attribution. Expected assertion
verdicts are balanced: six supported, five contradicted, one insufficient evidence.
These fixtures do not depend on a real company's financial answers.

`cases.json` contains model-visible evidence, records, metric definitions and assertions.
`expected.json` is a separate scoring-only file. Preparation does not read it, and case
IDs do not encode their expected answers. Every prepared packet has its own source
scope and source hash. Prepared inputs are sealed in a new output directory.

From the repository root, prepare one packet per case without calling a model:

```sh
.venv/bin/python experiments/data_agent_query/semantic-review-v1/benchmark.py prepare \
  --cases benchmarks/data_agent/semantic_review/v1/cases.json \
  --output /tmp/semantic-review-inputs-v1
```

The separately authorized semantic-review runner consumes that directory. Score its
result directory after execution:

```sh
.venv/bin/python experiments/data_agent_query/semantic-review-v1/benchmark.py evaluate \
  --inputs /tmp/semantic-review-inputs-v1 \
  --responses /tmp/semantic-review-run-v1 \
  --expected benchmarks/data_agent/semantic_review/v1/expected.json \
  --output /tmp/semantic-review-score-v1.json
```

Scoring first applies the host's semantic-assessment validator, then checks allowed
axis statuses, exact assertion verdicts and required source quotations. Value checks
allow either `constraints_found` or `none_found_in_context` when evidence is available;
the missing-definition case requires `insufficient_evidence`. Explicit comparability,
allocation and overlap restrictions still require `constraints_found`. This policy
was fixed before model execution; `expected-preflight-v0.1.json` preserves the earlier
preflight policy and is not the scoring input. Anchors must appear
in the assertion's citations; a correct-looking verdict alone is insufficient. Missing
responses count as `not_run`, never as passes. Quote anchors are intentionally strict
and do not measure flexible paraphrase quality. Fixture passes establish only this
bounded synthetic behavior, not real-company research correctness or recall.

Offline checks:

```sh
.venv/bin/python -m unittest tests.unit.test_semantic_review_benchmark
```
