"""Parsing of recorded agent runs (JSONL traces).

A trace is a JSON Lines file with one event per line:

    {"type": "run",    "run_id": "...", "task_id": "...", "agent": "..."}
    {"type": "call",   "step": 1, "tool": "web_search", "args": {...}}
    {"type": "result", "step": 1, "ok": true, "output": ..., "error": null,
                        "latency_ms": 420, "tokens_in": 0, "tokens_out": 0}
    {"type": "note",   "step": 2, "text": "agent reasoning or message"}
    {"type": "final",  "answer": "...", "state": {...},
                        "latency_ms": 0, "tokens_in": 0, "tokens_out": 0}

Rules the parser enforces or records:

- A malformed JSON line, a non-object line, or a call/result/final event
  missing its required fields is a hard format error (the CLI exits 2).
- A call with no matching result is NOT a parse error: the run happened,
  its outcome simply was never recorded. The parser synthesises an error
  result ("no result recorded") so scorers treat the step as failed
  rather than silently crediting it.
- Events after the final event are kept and counted; the step-economy
  scorer flags them as waste.
- Unknown event types are ignored but counted in the facts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


class TraceFormatError(Exception):
    """Raised when a trace file cannot be parsed. Carries the line number."""

    def __init__(self, message: str, line: int | None = None):
        self.line = line
        super().__init__(f"line {line}: {message}" if line else message)


@dataclass
class Call:
    step: int
    tool: str
    args: dict
    line: int


@dataclass
class Result:
    step: int
    ok: bool
    output: object = None
    error: str | None = None
    latency_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    synthesised: bool = False


@dataclass
class Final:
    answer: str = ""
    state: dict = field(default_factory=dict)
    latency_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class Trace:
    run_id: str | None = None
    task_id: str | None = None
    agent: str | None = None
    calls: list[Call] = field(default_factory=list)
    results: dict[int, Result] = field(default_factory=dict)
    final: Final | None = None
    calls_after_final: int = 0
    unknown_events: int = 0
    notes: int = 0

    def result_for(self, call: Call) -> Result:
        return self.results[call.step]

    @property
    def total_tokens(self) -> int:
        t = sum(r.tokens_in + r.tokens_out for r in self.results.values())
        if self.final:
            t += self.final.tokens_in + self.final.tokens_out
        return t

    @property
    def total_latency_ms(self) -> float:
        t = sum(r.latency_ms for r in self.results.values())
        if self.final:
            t += self.final.latency_ms
        return t


def _num(value, default=0.0):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def parse_trace(text: str) -> Trace:
    trace = Trace()
    seen_final = False
    known_events = 0
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TraceFormatError(f"invalid JSON ({exc.msg})", lineno) from exc
        if not isinstance(event, dict):
            raise TraceFormatError("event is not a JSON object", lineno)
        etype = event.get("type")
        if etype in ("run", "call", "result", "note", "final"):
            known_events += 1
        if etype == "run":
            trace.run_id = event.get("run_id")
            trace.task_id = event.get("task_id")
            trace.agent = event.get("agent")
        elif etype == "call":
            step, tool = event.get("step"), event.get("tool")
            if not isinstance(step, int) or isinstance(step, bool):
                raise TraceFormatError("call event needs an integer 'step'", lineno)
            if not isinstance(tool, str) or not tool:
                raise TraceFormatError("call event needs a non-empty string 'tool'", lineno)
            args = event.get("args", {})
            if not isinstance(args, dict):
                raise TraceFormatError("call event 'args' must be an object", lineno)
            if seen_final:
                trace.calls_after_final += 1
            trace.calls.append(Call(step=step, tool=tool, args=args, line=lineno))
        elif etype == "result":
            step = event.get("step")
            if not isinstance(step, int) or isinstance(step, bool):
                raise TraceFormatError("result event needs an integer 'step'", lineno)
            if not isinstance(event.get("ok"), bool):
                raise TraceFormatError("result event needs a boolean 'ok'", lineno)
            trace.results[step] = Result(
                step=step,
                ok=event["ok"],
                output=event.get("output"),
                error=event.get("error"),
                latency_ms=_num(event.get("latency_ms")),
                tokens_in=int(_num(event.get("tokens_in"))),
                tokens_out=int(_num(event.get("tokens_out"))),
            )
        elif etype == "note":
            trace.notes += 1
        elif etype == "final":
            if seen_final:
                raise TraceFormatError("trace has more than one final event", lineno)
            seen_final = True
            state = event.get("state", {})
            if not isinstance(state, dict):
                raise TraceFormatError("final event 'state' must be an object", lineno)
            trace.final = Final(
                answer=event.get("answer", "") or "",
                state=state,
                latency_ms=_num(event.get("latency_ms")),
                tokens_in=int(_num(event.get("tokens_in"))),
                tokens_out=int(_num(event.get("tokens_out"))),
            )
        else:
            trace.unknown_events += 1
    if known_events == 0:
        raise TraceFormatError(
            "no trace events found — the file holds no run/call/result/"
            "note/final events (is this a runreckon trace?)")
    called_steps = {c.step for c in trace.calls}
    for step in sorted(called_steps - set(trace.results)):
        trace.results[step] = Result(
            step=step, ok=False, error="no result recorded", synthesised=True)
    orphan = set(trace.results) - called_steps
    if orphan:
        raise TraceFormatError(
            f"result event(s) with no matching call at step(s) {sorted(orphan)}")
    return trace


def load_trace(path: str) -> Trace:
    with open(path, encoding="utf-8") as fh:
        return parse_trace(fh.read())


def canonical_args(args: dict) -> str:
    """Stable string form of a call's arguments, for duplicate detection."""
    return json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
