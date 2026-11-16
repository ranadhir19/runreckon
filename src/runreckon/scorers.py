"""Deterministic scorers.

Every scorer here computes its dimension exactly from the trace and the
spec — no model, no sampling, no network. A scorer returns a Dimension
with a score in [0, 1], the findings that explain it, and the raw facts
behind the arithmetic. A scorer that lacks the spec fields it needs
returns score=None (not applicable) and is excluded from the composite;
the scorecard says so rather than silently treating it as zero or one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import schema as schema_mod
from .spec import dig
from .trace import Trace, canonical_args


@dataclass
class Dimension:
    name: str
    score: float | None
    findings: list[str] = field(default_factory=list)
    facts: dict = field(default_factory=dict)


def score_outcome(trace: Trace, spec: dict) -> Dimension:
    dim = Dimension("outcome", None)
    if trace.final is None:
        dim.score = 0.0
        dim.findings.append("run has no final event — it never delivered an outcome")
        return dim
    checks = spec.get("final_checks", [])
    if not checks:
        dim.score = 1.0
        dim.facts["final_checks"] = "none in spec — presence of a final event only"
        return dim
    passed = 0
    for check in checks:
        ok, label = _run_final_check(trace, check)
        if ok:
            passed += 1
        else:
            dim.findings.append(f"final check failed: {label}")
    dim.score = passed / len(checks)
    dim.facts["checks_passed"] = f"{passed}/{len(checks)}"
    return dim


def _run_final_check(trace: Trace, check: dict) -> tuple[bool, str]:
    final = trace.final
    if "state_equals" in check:
        path, want = check["state_equals"]["path"], check["state_equals"]["value"]
        got, found = dig(final.state, path)
        return (found and got == want), f"state {path} == {want!r} (got {got!r})"
    if "state_present" in check:
        path = check["state_present"]["path"]
        _, found = dig(final.state, path)
        return found, f"state {path} present"
    if "answer_contains" in check:
        needle = str(check["answer_contains"])
        return needle.lower() in final.answer.lower(), f"answer contains {needle!r}"
    if "answer_not_contains" in check:
        needle = str(check["answer_not_contains"])
        return needle.lower() not in final.answer.lower(), \
            f"answer does not contain {needle!r}"
    return False, f"unknown final check {check!r}"


def score_tool_selection(trace: Trace, spec: dict) -> Dimension:
    dim = Dimension("tool_selection", None)
    expected = spec.get("expected_tools")
    allowed = spec.get("allowed_tools")
    if expected is None and allowed is None:
        dim.facts["note"] = "spec names no expected or allowed tools"
        return dim
    used = [c.tool for c in trace.calls]
    used_set = set(used)
    coverage = 1.0
    if expected:
        missing = [t for t in expected if t not in used_set]
        coverage = (len(expected) - len(missing)) / len(expected)
        for tool in missing:
            dim.findings.append(f"expected tool '{tool}' was never used")
        dim.facts["expected_coverage"] = f"{len(expected) - len(missing)}/{len(expected)}"
    permitted = set(allowed) if allowed is not None else (
        set(expected or []) | set(spec.get("reference_path", [])))
    if allowed is None:
        dim.facts["permitted_set"] = "expected tools + reference path (no allowed_tools in spec)"
    offending = [c for c in trace.calls if c.tool not in permitted]
    discipline = 1.0 - (len(offending) / len(used)) if used else 1.0
    for call in offending:
        dim.findings.append(
            f"step {call.step}: tool '{call.tool}' is not in the spec's permitted set")
    dim.facts["calls"] = len(used)
    dim.facts["undeclared_calls"] = len(offending)
    dim.score = 0.5 * coverage + 0.5 * discipline
    return dim


def score_argument_validity(trace: Trace, spec: dict) -> Dimension:
    dim = Dimension("argument_validity", None)
    schemas = spec.get("tool_schemas") or {}
    if not schemas:
        dim.facts["note"] = "spec carries no tool schemas"
        return dim
    checked = valid = 0
    for call in trace.calls:
        tool_schema = schemas.get(call.tool)
        if tool_schema is None:
            continue
        checked += 1
        errors = schema_mod.validate(call.args, tool_schema)
        if errors:
            for err in errors:
                dim.findings.append(f"step {call.step} ({call.tool}): {err}")
        else:
            valid += 1
    if checked == 0:
        dim.facts["note"] = "no calls to schema-described tools"
        return dim
    dim.score = valid / checked
    dim.facts["schema_checked_calls"] = checked
    dim.facts["valid_calls"] = valid
    dim.facts["unchecked_tools"] = sorted(
        {c.tool for c in trace.calls} - set(schemas))
    return dim


def score_step_economy(trace: Trace, spec: dict) -> Dimension:
    """Waste = repeating a call that already succeeded, with identical
    arguments. A repeat whose previous attempt ERRORED is a retry, not
    waste — retries are scored by error_recovery, never punished here.
    A repeat with different arguments is new work, not waste."""
    dim = Dimension("step_economy", None)
    total = len(trace.calls)
    if total == 0:
        dim.score = 1.0
        dim.facts["calls"] = 0
        return dim
    last_outcome: dict[str, bool] = {}
    signature_counts: dict[str, int] = {}
    waste = 0
    for call in trace.calls:
        sig = f"{call.tool}|{canonical_args(call.args)}"
        signature_counts[sig] = signature_counts.get(sig, 0) + 1
        if last_outcome.get(sig) is True:
            waste += 1
            dim.findings.append(
                f"step {call.step}: '{call.tool}' repeated with identical "
                "arguments after already succeeding — wasted step")
        last_outcome[sig] = trace.result_for(call).ok
    for sig, count in signature_counts.items():
        if count >= 3:
            tool = sig.split("|", 1)[0]
            dim.findings.append(
                f"'{tool}' called {count} times with identical arguments — loop pattern")
    waste += trace.calls_after_final
    if trace.calls_after_final:
        dim.findings.append(
            f"{trace.calls_after_final} call(s) made after the final event")
    dim.score = max(0.0, 1.0 - waste / total)
    dim.facts["calls"] = total
    dim.facts["wasted_calls"] = waste
    ref = spec.get("reference_path")
    if ref:
        dim.facts["reference_path_length"] = len(ref)
    return dim


def score_error_recovery(trace: Trace, spec: dict) -> Dimension:
    """An error is recovered when the same tool later succeeds, or — for
    tools the spec does not require — when the run still delivers its
    final event. An unrecovered error on a required tool, with a final
    answer delivered anyway, is a silent failure: the run reports
    success over a step that never worked."""
    dim = Dimension("error_recovery", None)
    expected = set(spec.get("expected_tools") or [])
    errors = [c for c in trace.calls if not trace.result_for(c).ok]
    if not errors:
        dim.score = 1.0
        dim.facts["errors"] = 0
        return dim
    recovered = 0
    for call in errors:
        later_ok = any(
            c.tool == call.tool and c.step > call.step and trace.result_for(c).ok
            for c in trace.calls)
        if later_ok:
            recovered += 1
            continue
        if expected and call.tool not in expected and trace.final is not None:
            recovered += 1
            dim.facts.setdefault("ignored_optional_errors", []).append(call.step)
            continue
        err = trace.result_for(call).error or "error"
        dim.findings.append(
            f"step {call.step}: '{call.tool}' failed ({err}) and never succeeded afterwards")
        if call.tool in expected and trace.final is not None:
            dim.findings.append(
                f"silent failure: final answer delivered although required "
                f"tool '{call.tool}' never succeeded")
    dim.score = recovered / len(errors)
    dim.facts["errors"] = len(errors)
    dim.facts["recovered"] = recovered
    return dim


def score_policy(trace: Trace, spec: dict) -> Dimension:
    dim = Dimension("policy", None)
    rules = spec.get("policy") or []
    if not rules:
        dim.facts["note"] = "spec carries no policy rules"
        return dim
    violations: list[str] = []
    for rule in rules:
        violations.extend(_check_policy_rule(trace, rule))
    dim.findings.extend(violations)
    dim.facts["rules"] = len(rules)
    dim.facts["violations"] = len(violations)
    dim.score = 0.0 if violations else 1.0
    return dim


def _check_policy_rule(trace: Trace, rule: dict) -> list[str]:
    out: list[str] = []
    if "forbid_tool" in rule:
        tool = rule["forbid_tool"]
        for call in trace.calls:
            if call.tool == tool:
                out.append(f"policy: forbidden tool '{tool}' called at step {call.step}")
    elif "forbid_arg" in rule:
        fa = rule["forbid_arg"]
        arg, pattern = fa["arg"], fa["pattern"]
        for call in trace.calls:
            if fa.get("tool") and call.tool != fa["tool"]:
                continue
            if arg in call.args and re.search(pattern, str(call.args[arg])):
                out.append(
                    f"policy: step {call.step} ({call.tool}) argument '{arg}' "
                    f"matches forbidden pattern {pattern!r}")
    elif "require_before" in rule:
        rb = rule["require_before"]
        tool, before = rb["tool"], rb["before"]
        first_tool = next((c.step for c in trace.calls if c.tool == tool), None)
        if first_tool is not None:
            first_before = next((c.step for c in trace.calls if c.tool == before), None)
            if first_before is None or first_before > first_tool:
                out.append(
                    f"policy: '{tool}' used at step {first_tool} without a prior "
                    f"'{before}' call")
    elif "max_calls" in rule:
        mc = rule["max_calls"]
        count = sum(1 for c in trace.calls if c.tool == mc["tool"])
        if count > mc["count"]:
            out.append(
                f"policy: tool '{mc['tool']}' called {count} times, limit is {mc['count']}")
    elif "forbid_state" in rule:
        fs = rule["forbid_state"]
        if trace.final is not None:
            got, found = dig(trace.final.state, fs["path"])
            if found and got == fs["equals"]:
                out.append(
                    f"policy: final state {fs['path']} == {fs['equals']!r} is forbidden")
    else:
        out.append(f"policy: unknown rule {rule!r} — cannot verify, counted as a violation")
    return out


def score_cost_latency(trace: Trace, spec: dict) -> Dimension:
    dim = Dimension("cost_latency", None)
    tokens_in = sum(r.tokens_in for r in trace.results.values())
    tokens_out = sum(r.tokens_out for r in trace.results.values())
    if trace.final:
        tokens_in += trace.final.tokens_in
        tokens_out += trace.final.tokens_out
    tokens = tokens_in + tokens_out
    latency = trace.total_latency_ms
    dim.facts["steps"] = len(trace.calls)
    dim.facts["tokens"] = tokens
    dim.facts["latency_ms"] = latency
    pricing = spec.get("pricing")
    cost = None
    if pricing:
        cost = (tokens_in / 1000.0) * pricing.get("input_per_1k_usd", 0.0) \
            + (tokens_out / 1000.0) * pricing.get("output_per_1k_usd", 0.0)
        dim.facts["cost_usd"] = round(cost, 6)
    budgets = spec.get("budgets") or {}
    if not budgets:
        dim.facts["note"] = "spec carries no budgets"
        return dim
    actuals = {"max_steps": len(trace.calls), "max_tokens": tokens,
               "max_latency_ms": latency, "max_cost_usd": cost}
    subscores = []
    for key, budget in budgets.items():
        actual = actuals.get(key)
        if actual is None:
            dim.facts[key] = f"budget {budget}, actual not measurable (no pricing)"
            continue
        ratio = (actual / budget) if budget else float("inf")
        dim.facts[key] = f"{actual} of budget {budget}"
        if ratio > 1.0:
            dim.findings.append(f"budget exceeded: {key} {actual} > {budget}")
        subscores.append(1.0 if ratio <= 1.0 else max(0.0, 2.0 - ratio))
    if subscores:
        dim.score = min(subscores)
    return dim


DETERMINISTIC_SCORERS = [
    score_outcome,
    score_tool_selection,
    score_argument_validity,
    score_step_economy,
    score_error_recovery,
    score_policy,
    score_cost_latency,
]


def run_deterministic(trace: Trace, spec: dict) -> list[Dimension]:
    return [fn(trace, spec) for fn in DETERMINISTIC_SCORERS]
