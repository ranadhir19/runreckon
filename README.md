![runreckon — Score an agent run](banner.svg)

# runreckon

**Score how an agent executed a run, not just whether it finished.**

An agent can complete a task and still do it badly: call the same search
four times, reach for tools it was never given, pass malformed arguments,
blow the token budget, quietly break a policy on the way — and deliver a
final answer that passes every outcome check. Outcome-only evaluation
calls that run a success. runreckon scores the *execution*: feed it a
recorded run (a JSONL trace) and the task spec it was supposed to
follow, and it produces a scorecard for the run itself.

## The showcase case

This run **succeeded**. Its brief was saved, its final checks pass, its
answer is fully grounded. Here is its scorecard (`runreckon demo`, the
`sloppy-success` example, real output):

```text
outcome              100.0
tool_selection        88.9
    - step 5: tool 'web_scrape' is not in the spec's permitted set
    - step 6: tool 'summarize' is not in the spec's permitted set
argument_validity     85.7
    - step 7 (fetch_page): $: missing required property 'url'
step_economy          66.7
    - step 2: 'web_search' repeated with identical arguments after already succeeding — wasted step
    - step 3: 'web_search' repeated with identical arguments after already succeeding — wasted step
    - step 4: 'web_search' repeated with identical arguments after already succeeding — wasted step
    - 'web_search' called 4 times with identical arguments — loop pattern
error_recovery       100.0
policy               100.0
cost_latency          43.8
    - budget exceeded: max_steps 9 > 8
    - budget exceeded: max_tokens 9370 > 6000
groundedness         100.0
------------------------------------------------------------
COMPOSITE             87.6  — serviceable
```

The task succeeded; the run was still bad — four identical searches, two
undeclared tools, one malformed call, two budgets blown. With
`--min-score 0.90` this run fails CI. That gap between "it worked" and
"it ran well" is what runreckon measures.

## Quickstart

```bash
pip install git+https://github.com/ranadhir19/runreckon.git
runreckon demo                                   # the three bundled examples
runreckon score my-run.jsonl --spec my-task.json # your own run
runreckon score my-run.jsonl --spec my-task.json --format json
runreckon selftest                               # measure the scorer itself
```

Pure Python standard library. No dependencies, no API keys, no network:
the deterministic core runs fully offline. Developed on Python 3.12;
any Python ≥ 3.10 works.

Exit codes are CI-shaped: `0` pass, `1` fail (composite below
`--min-score`, default 0.75, or any policy violation), `2` the trace or
spec could not be read.

## What it scores

| Dimension | What it checks | How |
|---|---|---|
| outcome | Did the run deliver? Final-state checks, required answer content | exact |
| tool_selection | The tools the spec expected were used; no undeclared tools were touched | exact |
| argument_validity | Every call's arguments against the spec's JSON Schemas | exact |
| step_economy | Repeated calls that already succeeded, loop patterns, calls after the final event | exact |
| error_recovery | Failures that were recovered vs failures silently stepped over | exact |
| policy | Forbidden tools, forbidden argument patterns, required ordering (approval before action), call limits, forbidden end-states | exact — and a hard gate |
| cost_latency | Steps, tokens, recorded latency, and priced cost against the spec's budgets | exact |
| groundedness | Every checkable claim in the final answer (numbers, URLs, emails, quoted strings) appears in the evidence the agent actually had | exact |

Two design rules:

- **Deterministic first.** Everything that can be computed exactly is
  computed exactly. A repeated call after an *error* is a retry, not
  waste; a repeat with *different arguments* is new work; a number the
  *user* put in the task prompt is grounded, not invented. The scorers
  encode those distinctions, and the self-test's negative controls
  prove they hold.
- **Judges are optional and measured.** Groundedness can also be
  assessed by a pluggable judge (`--judge module:function`, or the
  bundled deterministic stand-in). A judge is only trusted as far as it
  has been measured: whenever one is enabled, its agreement, Cohen's
  kappa, and per-class precision and recall on a bundled labelled
  calibration set are printed on the scorecard next to its verdict —
  reported alongside the deterministic score, never blended into it.
  The stand-in's measured calibration:
  agreement 0.833, kappa 0.667, precision 0.833, recall 0.833 on
  12 items, with two instructive
  failures (a heavy-paraphrase miss, a negation false-pass). That is
  the point: an unmeasured judge is a hope, a measured one is an
  instrument with known error.

This calibration is a disclosure about runreckon's own optional
judge, printed so its verdicts are never taken on faith. Systematic
grader validation — measuring any grader against labelled data and
auditing the task suites it scores — is evalcrucible's job, not
runreckon's.

## The evaluator evaluates itself

runreckon ships a fault-injection self-test. It takes clean traces that
score perfectly, plants one known defect per copy — a wrong tool, an
invalid argument, an ungrounded claim, a silent policy breach, loop
waste, a masked failure — and checks that the scorer responsible for
that defect class catches it. It also runs negative controls:
legitimate traces that resemble defects and must not be flagged.

Measured on this tree (3 clean bases × 6 defect classes, regenerated
and byte-verified by `validate.py`; full detail in
[SELFTEST_RESULTS.md](SELFTEST_RESULTS.md)):

| Defect class | Scorer responsible | Planted | Caught | Rate |
|---|---|---|---|---|
| wrong_tool | tool_selection | 3 | 3 | 1.000 |
| invalid_args | argument_validity | 3 | 3 | 1.000 |
| ungrounded_claim | groundedness | 3 | 3 | 1.000 |
| policy_breach | policy | 3 | 3 | 1.000 |
| loop_waste | step_economy | 3 | 3 | 1.000 |
| silent_failure | error_recovery | 3 | 3 | 1.000 |

**18/18 planted defects caught; 3/3 negative controls pass.** The base
set is small and author-built — treat the rates as a regression floor
for the scorers, not as a field measurement. Widen the bases before
quoting the rates as evidence about anyone else's agents.

The self-test also caught a real bug during development: an email
address at the end of a sentence ("…sent to ana@example.com.") was
extracted with its sentence-final period attached and falsely flagged
as ungrounded. The fix is in, and a regression test pins it.

## Inputs

A **trace** is JSONL — one event per line: `run`, `call`, `result`,
`note`, `final`. A **spec** is JSON: expected/allowed tools, argument
schemas, a reference path, policy rules, final-state checks, budgets.
Full formats: [docs/trace-format.md](docs/trace-format.md) and
[docs/spec-format.md](docs/spec-format.md). The three bundled examples
(a clean run, the showcase above, and a policy breach) live in the
package under `runreckon/examples/` and run with `runreckon demo`.

## Gate a pull request on run quality

This repo is also a GitHub Action. Record a trace in your agent's test
suite, commit the trace and its spec, and fail the PR when execution
quality regresses:

```yaml
- uses: ranadhir19/runreckon@v0.1.0
  with:
    trace: tests/traces/checkout-run.jsonl
    spec: tests/traces/checkout-task.json
    min-score: "0.90"
```

See [docs/action.md](docs/action.md) for inputs and a fuller workflow.

## How this differs from evalcrucible

[evalcrucible](https://github.com/ranadhir19/evalcrucible) is the
grader tool: it validates graders against labelled data and audits
static (prompt → gold) task suites, so the benchmark itself can be
trusted. runreckon is the eval tool: given a task spec you already
trust, it scores how an agent executed a recorded run.

## Limits

- Scoring is only as good as the spec. A spec with no schemas, no
  policy, and no budgets scores only what it declares; dimensions
  without inputs report `n/a` and are excluded from the composite,
  never silently zeroed or gifted.
- Groundedness checks *checkable* claims — numbers, URLs, emails,
  quoted strings. A fluent falsehood with no checkable token in it is
  invisible to the deterministic layer; that is what the (measured)
  judge layer is for.
- Latency is the sum of per-event recorded latencies, not wall-clock;
  traces that do not record tokens or latency cannot be scored on them.
- The fault-injection bases are three small author-built runs. The
  mechanism generalises; the specific rates are a floor, not a census.

## Development

```bash
git clone https://github.com/ranadhir19/runreckon.git
cd runreckon
python3 validate.py   # must end with OVERALL PASS
```

The harness compiles the package, runs the unit tests (authored from
the failure-mode domain, including the near-miss negatives), reproduces
all three example scorecards against their expected bands, re-runs the
self-test and requires `SELFTEST_RESULTS.md` to come back
byte-identical, and runs the portfolio's pre-push integrity gates.

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Ranadhir Ghosh.
