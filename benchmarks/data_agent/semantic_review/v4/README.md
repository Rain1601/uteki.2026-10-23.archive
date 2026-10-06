# Independent v4 fixtures

Two new synthetic cases contain eight assertions, separate company/source scopes and
explicit fiscal dates. Packets use input schema v3 and the current strict local anchor
coverage rules. The model-visible suite and independent expected key are separate files.
`frozen-hashes.json` pins both files before any model execution.

Prepare inputs without reading the expected key or making model calls:

```sh
.venv/bin/python experiments/data_agent_query/semantic-review-v4/benchmark.py prepare \
  --cases benchmarks/data_agent/semantic_review/v4/cases.json \
  --output /tmp/semantic-review-v4-inputs
```

The preparation path opens only `cases.json`, preserves each packet and seals a new
input directory. Do not send `expected.json` to a reviewer, critic, revision prompt or
any model. Independent scoring is available through the script's `evaluate` subcommand;
it reuses the fixed-rule scorer and requires separate source-grounded notes for a final
semantic pass. Full evaluation metadata belongs in an ignored archive directory.

Keep the frozen key unchanged after observing outputs. If failures from these cases
guide further tuning, describe subsequent runs as development regressions rather than
new unseen evaluations. Model execution requires separate authorization and is not part
of preparation or validation. No model calls were made to create this suite.
