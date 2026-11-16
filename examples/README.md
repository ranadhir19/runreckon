# Examples

The three example runs are bundled inside the Python package (so they
ship with `pip install`) under `runreckon/examples/`:

| Case | Story |
|---|---|
| `clean-run` | A research agent does the task the short way: every dimension 100. |
| `sloppy-success` | The same task, completed — brief saved, answer grounded — via four identical searches, two undeclared tools, one malformed call, and two blown budgets. Composite 87.6. The showcase case. |
| `policy-breach` | A tidy, efficient run that also sends an email the spec forbids. Policy 0, hard fail. |

Run them:

```bash
runreckon demo
```

Or score one directly from a checkout:

```bash
runreckon score src/runreckon/examples/sloppy-success/trace.jsonl \
  --spec src/runreckon/examples/sloppy-success/spec.json
```

All three share one task spec (a public-source research brief); each
folder holds its own copy so every example is self-contained. The
expected scorecard bands for all three are pinned in
`src/runreckon/examples/expected.json` and reproduced by
`validate.py` on every run. All traces are synthetic fixtures authored
for this repository.
