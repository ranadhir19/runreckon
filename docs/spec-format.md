# Task spec format

A spec is a single JSON object describing what a good run of one task
looks like. Every field is optional; each scorer uses the fields it
needs and reports `n/a` — excluded from the composite — when they are
absent. A spec that declares nothing scores nothing.

```json
{
  "task_id": "research-brief",
  "goal": "Research the port's 2024 container volume and save a brief",
  "task_prompt": "the exact prompt the agent saw",
  "allowed_tools": ["web_search", "fetch_page", "save_brief"],
  "expected_tools": ["web_search", "fetch_page", "save_brief"],
  "tool_schemas": {"web_search": {"type": "object", "required": ["query"]}},
  "reference_path": ["web_search", "fetch_page", "save_brief"],
  "policy": [{"forbid_tool": "send_email"}],
  "final_checks": [{"state_equals": {"path": "brief.saved", "value": true}}],
  "budgets": {"max_steps": 8, "max_tokens": 6000, "max_cost_usd": 0.10},
  "pricing": {"input_per_1k_usd": 0.003, "output_per_1k_usd": 0.015}
}
```

## Fields

- `task_id`, `goal`: labels. `goal` is also a grounding source.
- `task_prompt`: the prompt the agent saw. It is a grounding source —
  figures the user supplied are grounded when the agent cites them.
- `allowed_tools`: the permitted tool set. Calls to anything else are
  undeclared-tool findings. When absent, the permitted set falls back
  to `expected_tools` plus the `reference_path` tools.
- `expected_tools`: tools a complete run should use; coverage of this
  set is half of the tool-selection score.
- `tool_schemas`: per-tool JSON Schemas for the call arguments. The
  validator implements the common subset (type, required, properties,
  additionalProperties, items, enum, const, pattern, string/number
  bounds, anyOf/oneOf) and never coerces: `true` is not an integer and
  `"5"` is not a number.
- `reference_path`: the expected tool sequence. Reported as a fact
  next to the actual step count; budgets enforce hard ceilings.
- `policy`: a list of rules (below). Any violation scores the policy
  dimension 0 and hard-fails the run (exit 1) unless
  `--no-fail-on-policy` is passed.
- `final_checks`: checks on the final event (below).
- `budgets`: `max_steps`, `max_tokens` (input + output),
  `max_latency_ms` (sum of recorded latencies), `max_cost_usd`.
  Each budgeted quantity scores 1.0 at or under budget, grading to 0
  at twice the budget; the dimension takes the worst subscore.
- `pricing`: `input_per_1k_usd`, `output_per_1k_usd` — turns token
  counts into a cost figure.
- `weights`: optional per-dimension overrides of the composite
  weights. Defaults: outcome 0.20, policy 0.15, argument_validity
  0.15, tool_selection 0.13, step_economy 0.13, error_recovery 0.08,
  groundedness 0.08, cost_latency 0.08.

## Policy rules

| Rule | Meaning |
|---|---|
| `{"forbid_tool": "send_email"}` | the tool must never be called |
| `{"forbid_arg": {"tool": "fetch_page", "arg": "url", "pattern": "internal\\."}}` | the named argument (on the named tool, or any tool when `tool` is omitted) must never match the regex |
| `{"require_before": {"tool": "send_reply", "before": "request_approval"}}` | the first use of `tool` must be preceded by a call to `before` |
| `{"max_calls": {"tool": "web_search", "count": 5}}` | a per-tool call ceiling |
| `{"forbid_state": {"path": "billing.charged", "equals": true}}` | the final state must not hold this value at this dotted path |

An unrecognised rule is reported as a violation, never silently
skipped: a policy the scorer cannot verify must not read as a policy
that passed.

## Final checks

| Check | Meaning |
|---|---|
| `{"state_equals": {"path": "brief.saved", "value": true}}` | dotted path into the final state equals the value |
| `{"state_present": {"path": "brief.path"}}` | the path exists in the final state |
| `{"answer_contains": "TEU"}` | the final answer contains the text (case-insensitive) |
| `{"answer_not_contains": "as an AI"}` | the final answer must not contain the text |
