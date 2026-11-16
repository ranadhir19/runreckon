"""Fault injection: plant known defects in clean traces.

The self-test takes traces that score clean and plants one defect of a
known class in each copy. A scorer earns trust only by catching defects
it was not tuned on in this file's wording: each plant is defined by the
*behaviour* it introduces (a wrong tool, an invalid argument, a claim
with no evidence, a forbidden action, wasted steps, a masked failure),
and the catch test is behavioural too — the corresponding dimension's
score must drop versus the same trace unmodified.

Plants are deterministic: same input, same mutated trace, every run.
"""

from __future__ import annotations

import copy
import json

from .trace import Call, Final, Result, Trace

DECOY_TOOLS = ["web_scrape", "shell_exec", "file_write", "db_delete", "send_sms"]


def _clone(trace: Trace) -> Trace:
    return copy.deepcopy(trace)


def _first_call(trace: Trace, predicate) -> Call | None:
    return next((c for c in trace.calls if predicate(c)), None)


def plant_wrong_tool(trace: Trace, spec: dict) -> Trace | None:
    """Swap a required tool call for a plausible tool the spec never
    permitted. Detector: tool_selection."""
    expected = set(spec.get("expected_tools") or [])
    permitted = set(spec.get("allowed_tools") or []) | expected
    target = _first_call(trace, lambda c: c.tool in expected)
    if target is None:
        return None
    decoy = next((d for d in DECOY_TOOLS if d not in permitted and d != target.tool), None)
    if decoy is None:
        return None
    mutant = _clone(trace)
    for call in mutant.calls:
        if call.step == target.step:
            call.tool = decoy
    return mutant


def plant_invalid_args(trace: Trace, spec: dict) -> Trace | None:
    """Break one schema-checked call: drop a required argument, or if the
    schema has no required fields, mistype a declared property.
    Detector: argument_validity."""
    schemas = spec.get("tool_schemas") or {}
    target = _first_call(trace, lambda c: c.tool in schemas)
    if target is None:
        return None
    mutant = _clone(trace)
    call = next(c for c in mutant.calls if c.step == target.step)
    tool_schema = schemas[call.tool]
    required = tool_schema.get("required") or []
    if required and required[0] in call.args:
        del call.args[required[0]]
        return mutant
    props = tool_schema.get("properties") or {}
    for name, sub in props.items():
        if name in call.args and sub.get("type") == "integer":
            call.args[name] = "not-a-number"
            return mutant
        if name in call.args and sub.get("type") == "string":
            call.args[name] = 12345
            return mutant
    return None


def plant_ungrounded_claim(trace: Trace, spec: dict) -> Trace | None:
    """Append a precise, fabricated statistic to the final answer — a
    number that appears in no tool result, state, or prompt.
    Detector: groundedness."""
    if trace.final is None:
        return None
    mutant = _clone(trace)
    mutant.final.answer = (
        mutant.final.answer.rstrip(".")
        + ". Independent analysts estimate adoption grew 37.4 percent last year.")
    return mutant


def plant_policy_breach(trace: Trace, spec: dict) -> Trace | None:
    """Commit the first forbidden action the spec names: call a forbidden
    tool, use a gated tool without its prerequisite, or fetch an argument
    matching a forbidden pattern. Detector: policy."""
    rules = spec.get("policy") or []
    if not rules or not trace.calls:
        return None
    mutant = _clone(trace)
    last_step = max(c.step for c in mutant.calls)
    for rule in rules:
        if "forbid_tool" in rule:
            tool = rule["forbid_tool"]
            mutant.calls.append(Call(step=last_step + 1, tool=tool, args={}, line=0))
            mutant.results[last_step + 1] = Result(
                step=last_step + 1, ok=True, output="done")
            return mutant
        if "require_before" in rule:
            rb = rule["require_before"]
            mutant.calls.insert(0, Call(step=0, tool=rb["tool"], args={}, line=0))
            mutant.results[0] = Result(step=0, ok=True, output="done")
            return mutant
        if "forbid_arg" in rule:
            fa = rule["forbid_arg"]
            tool = fa.get("tool") or (trace.calls[0].tool)
            mutant.calls.append(Call(
                step=last_step + 1, tool=tool,
                args={fa["arg"]: "http://internal.corp/secret"}, line=0))
            mutant.results[last_step + 1] = Result(
                step=last_step + 1, ok=True, output="done")
            return mutant
    return None


def plant_loop_waste(trace: Trace, spec: dict) -> Trace | None:
    """Repeat one successful call, with identical arguments, three extra
    times. Detector: step_economy."""
    target = _first_call(trace, lambda c: trace.result_for(c).ok)
    if target is None:
        return None
    mutant = _clone(trace)
    result = mutant.result_for(target)
    next_step = max(c.step for c in mutant.calls) + 1
    for _ in range(3):
        mutant.calls.append(Call(
            step=next_step, tool=target.tool, args=copy.deepcopy(target.args), line=0))
        mutant.results[next_step] = copy.deepcopy(result)
        mutant.results[next_step].step = next_step
        next_step += 1
    return mutant


def plant_silent_failure(trace: Trace, spec: dict) -> Trace | None:
    """Fail a required tool's only successful call and leave the final
    answer claiming success. Detector: error_recovery."""
    expected = set(spec.get("expected_tools") or [])
    candidates = [c for c in trace.calls
                  if c.tool in expected and trace.result_for(c).ok]
    if not candidates or trace.final is None:
        return None
    target = candidates[0]
    mutant = _clone(trace)
    for call in mutant.calls:
        if call.tool == target.tool and mutant.result_for(call).ok:
            result = mutant.results[call.step]
            result.ok = False
            result.output = None
            result.error = "service unavailable (planted)"
    return mutant


PLANTS = {
    "wrong_tool": (plant_wrong_tool, "tool_selection"),
    "invalid_args": (plant_invalid_args, "argument_validity"),
    "ungrounded_claim": (plant_ungrounded_claim, "groundedness"),
    "policy_breach": (plant_policy_breach, "policy"),
    "loop_waste": (plant_loop_waste, "step_economy"),
    "silent_failure": (plant_silent_failure, "error_recovery"),
}


def trace_to_jsonl(trace: Trace) -> str:
    """Serialise a (possibly mutated) trace back to JSONL, for debugging."""
    lines = []
    if trace.run_id or trace.task_id:
        lines.append(json.dumps({"type": "run", "run_id": trace.run_id,
                                 "task_id": trace.task_id, "agent": trace.agent}))
    events = []
    for call in trace.calls:
        events.append((call.step, 0, {"type": "call", "step": call.step,
                                      "tool": call.tool, "args": call.args}))
        result = trace.results[call.step]
        events.append((call.step, 1, {
            "type": "result", "step": call.step, "ok": result.ok,
            "output": result.output, "error": result.error,
            "latency_ms": result.latency_ms,
            "tokens_in": result.tokens_in, "tokens_out": result.tokens_out}))
    for _, _, event in sorted(events):
        lines.append(json.dumps(event))
    if trace.final is not None:
        final: Final = trace.final
        lines.append(json.dumps({
            "type": "final", "answer": final.answer, "state": final.state,
            "latency_ms": final.latency_ms,
            "tokens_in": final.tokens_in, "tokens_out": final.tokens_out}))
    return "\n".join(lines) + "\n"
