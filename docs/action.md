# Using the GitHub Action

The runreckon repository is itself a reusable GitHub Action: it scores
a recorded agent run in CI and fails the step when the run's execution
quality regresses — the same way a lint or test gate fails on code.

## Minimal workflow

Record a trace in your agent's test suite (any harness that can emit
the [trace format](trace-format.md)), commit the trace and its
[spec](spec-format.md) with the test, and add:

```yaml
name: agent-run-quality
on: [pull_request]
jobs:
  score-runs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ranadhir19/runreckon@v0.1.0
        with:
          trace: tests/traces/checkout-run.jsonl
          spec: tests/traces/checkout-task.json
          min-score: "0.90"
```

The step fails (exit 1) when the composite falls below `min-score`, or
on any policy violation unless `fail-on-policy` is set to `"false"`.
A trace or spec that cannot be parsed exits 2, which also fails the
step — a gate that cannot read its inputs must not pass silently.

## Inputs

| Input | Required | Default | Meaning |
|---|---|---|---|
| `trace` | yes | — | path to the JSONL trace |
| `spec` | yes | — | path to the task spec JSON |
| `min-score` | no | `0.75` | minimum composite (0–1) to pass |
| `format` | no | `text` | scorecard format: `text` or `json` |
| `output` | no | — | also write the scorecard to this file (e.g. to upload as an artifact) |
| `fail-on-policy` | no | `true` | hard-fail on any policy violation |

## Notes

- The action installs runreckon from the GitHub repository (pure
  Python standard library; nothing else is installed). Once the
  package is on PyPI the install line will switch to the pinned PyPI
  release; the interface will not change.
- Golden traces rot when the agent's tools change. When a score drop
  is a deliberate behaviour change, regenerate the trace, review the
  scorecard diff in the PR like any other golden-file change, and
  commit the new trace with the change that caused it.
- Score several runs by adding one step per trace, or run the CLI in
  your own step: `runreckon score <trace> --spec <spec>` returns the
  same exit codes.
