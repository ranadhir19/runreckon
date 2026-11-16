# Compliance record — runreckon

Originality and IP record for this repository, kept in-tree per the
portfolio's pre-publication gate. The full ledger entry lives in the
brand goal's IP/legal compliance ledger.

## Name

`runreckon` — coined compound ("reckon" = to judge and to calculate;
the run is what gets reckoned). Collision checks run 2026-11-15:

- GitHub repository search `runreckon in:name`: **0 repositories**.
- PyPI `runreckon`: **not registered** (project JSON returns 404).
- Web search: no software product, company, or tool named "runreckon".
  "Reckon" alone is an Australian accounting firm (reckon.com) in an
  unrelated field; the compound name is unused, and no branding, copy,
  or assets of any third party are used.
- Portfolio: joins the coined `-reckon` family (swarmreckon,
  globereckon) without duplicating either tool's function.

Names checked and rejected in the same pass: `agentopsy`,
`trailgrade`, `runverdict`, `tracewarden` (already taken, per the
parent brief); `agentrial`, `trailmark`, `runwitness`, `runcard`,
`pathproof`, `loopledger` (exact-name GitHub repositories exist);
`runlint` (GitHub-clear but registered on PyPI by a third party for an
agent-observability tool — same field, rejected); `trajgauge`
(registrable, but one letter from the existing agent-trajectory
scoring tool `tracegauge` on PyPI — rejected as confusingly similar in
the identical niche); `stepaudit` (clear, but generic).

## Originality

The subject area — evaluating how an agent executed, not only whether
it finished — was taken as inspiration from a social-media post under
the portfolio's reference rule: only the subject area was taken. No
metric list, name, text, or structure from any external source is used;
the dimension taxonomy, trace/spec formats, scoring rules, and all
code and copy in this repository were authored for it.

Added value the reference lacks: a working deterministic scorer; a
trace and spec format; policy rules evaluated as code; a pluggable
judge whose calibration is measured and printed; a fault-injection
self-test that measures the scorer itself; a CI gate (exit codes and a
GitHub Action).

Position against the author's existing portfolio: evalcrucible audits
benchmarks and graders (static task suites); runreckon scores recorded
execution traces against a task spec. Different input artifact,
different object of measurement; neither duplicates the other.

## Licence and dependencies

- This repository: MIT, see [LICENSE](LICENSE) (portfolio-standard
  text, Copyright (c) 2026 Ranadhir Ghosh), consistent with
  `pyproject.toml`.
- Dependencies: **none**. The package, tests, and harness use only the
  Python standard library. Nothing vendored; no third-party code,
  assets, fonts, images, or data in the tree. All example traces are
  synthetic and authored for this repository (the port figures in them
  are illustrative fixture content, labelled as examples).
