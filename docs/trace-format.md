# Trace format

A trace is a JSON Lines file: one event per line, in the order the
events happened. Blank lines are ignored. Every event is a JSON object
with a `type` field.

## Events

### `run` (optional, first line)

```json
{"type": "run", "run_id": "checkout-2026-11-15-001", "task_id": "checkout", "agent": "buyer 2.1"}
```

Metadata only; carried onto the scorecard.

### `call`

```json
{"type": "call", "step": 1, "tool": "web_search", "args": {"query": "..."}}
```

- `step` (integer, required): pairs the call with its result. Steps need
  not be contiguous, but order in the file is execution order.
- `tool` (string, required).
- `args` (object, optional, default `{}`).

### `result`

```json
{"type": "result", "step": 1, "ok": true, "output": {"...": "..."}, "error": null, "latency_ms": 420, "tokens_in": 120, "tokens_out": 40}
```

- `step` must match a call's step; an orphan result is a format error.
- `ok` (boolean, required). `output` is whatever the tool returned;
  `error` a string when `ok` is false.
- `latency_ms`, `tokens_in`, `tokens_out` are optional and default to
  0; they feed the cost/latency dimension.

A call with **no** result event is not a format error: the parser
synthesises a failed result ("no result recorded"). A step whose
outcome was never recorded must not earn silent credit.

### `note` (optional)

```json
{"type": "note", "step": 2, "text": "The first source looks stale; trying another."}
```

Agent reasoning or messages. Counted, never scored, and never treated
as evidence for groundedness (an agent's own notes are not evidence).

### `final` (exactly one)

```json
{"type": "final", "answer": "...", "state": {"brief": {"saved": true}}, "latency_ms": 900, "tokens_in": 300, "tokens_out": 80}
```

- `answer`: the final answer text (groundedness checks its claims).
- `state`: the run's end-state as an object; final checks and
  `forbid_state` policy rules read dotted paths into it.
- A second `final` event is a format error. Calls after the final
  event are kept and counted as waste by the step-economy scorer.

## Format errors

Malformed JSON, a non-object line, a call/result missing its required
fields, an orphan result, or a file with no trace events at all make
the CLI exit `2` with the offending line number. Unknown event types
are ignored but counted (forward compatibility).
