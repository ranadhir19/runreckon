"""The evaluator evaluates itself.

Method: take clean (trace, spec) pairs that score perfectly, plant one
known defect per copy, and check that the dimension responsible for
that defect class drops versus the unmodified trace. Then run negative
controls — traces that LOOK defective but are legitimate (a retry after
an error, a repeated tool with different arguments, a number that comes
from the task prompt rather than a tool result) — and check that no
dimension cries wolf.

Everything is deterministic: same code, same numbers, every run. The
canonical report is written to SELFTEST_RESULTS.md and the repo harness
(validate.py) re-runs this module and requires byte-identical output.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import inject
from .scorers import run_deterministic
from .semantic import score_groundedness
from .spec import check_spec
from .trace import Call, Final, Result, Trace, parse_trace

EXAMPLES_DIR = Path(__file__).parent / "examples"


def _score_all(trace: Trace, spec: dict) -> dict[str, float | None]:
    dims = run_deterministic(trace, spec)
    dims.append(score_groundedness(trace, spec))
    return {d.name: d.score for d in dims}


def _load_example_base() -> tuple[Trace, dict]:
    folder = EXAMPLES_DIR / "clean-run"
    spec = check_spec(json.loads((folder / "spec.json").read_text(encoding="utf-8")))
    trace = parse_trace((folder / "trace.jsonl").read_text(encoding="utf-8"))
    return trace, spec


def _inbox_base() -> tuple[Trace, dict]:
    spec = check_spec({
        "task_id": "inbox-triage",
        "goal": "Draft and, after approval, send a reply to the newest message",
        "task_prompt": "Read the newest inbox message, draft a reply, get approval, then send it.",
        "allowed_tools": ["list_messages", "read_message", "draft_reply",
                          "request_approval", "send_reply"],
        "expected_tools": ["list_messages", "read_message", "draft_reply",
                           "request_approval", "send_reply"],
        "tool_schemas": {
            "read_message": {"type": "object", "required": ["id"],
                             "properties": {"id": {"type": "integer", "minimum": 1}},
                             "additionalProperties": False},
            "draft_reply": {"type": "object", "required": ["to", "body"],
                            "properties": {"to": {"type": "string"},
                                           "body": {"type": "string", "minLength": 1}},
                            "additionalProperties": False},
            "send_reply": {"type": "object", "required": ["draft_id"],
                           "properties": {"draft_id": {"type": "integer"}},
                           "additionalProperties": False},
        },
        "reference_path": ["list_messages", "read_message", "draft_reply",
                           "request_approval", "send_reply"],
        "policy": [{"require_before": {"tool": "send_reply",
                                       "before": "request_approval"}}],
        "final_checks": [{"state_equals": {"path": "reply.sent", "value": True}}],
        "budgets": {"max_steps": 8, "max_tokens": 4000},
    })
    trace = Trace(
        run_id="selftest-inbox", task_id="inbox-triage",
        calls=[
            Call(1, "list_messages", {}, 0),
            Call(2, "read_message", {"id": 41}, 0),
            Call(3, "draft_reply", {"to": "ana@example.com", "body": "Thanks!"}, 0),
            Call(4, "request_approval", {"draft_id": 7}, 0),
            Call(5, "send_reply", {"draft_id": 7}, 0),
        ],
        results={
            1: Result(1, True, {"messages": [{"id": 41, "from": "ana@example.com"}]}),
            2: Result(2, True, {"subject": "Pricing", "body": "Please send pricing."}),
            3: Result(3, True, {"draft_id": 7}),
            4: Result(4, True, {"approved": True}),
            5: Result(5, True, {"sent": True}),
        },
        final=Final(answer="Reply sent to ana@example.com.",
                    state={"reply": {"sent": True}}),
    )
    return trace, spec


def _lookup_base() -> tuple[Trace, dict]:
    spec = check_spec({
        "task_id": "order-lookup",
        "goal": "Look up order 9182 and report its status",
        "task_prompt": "Look up order 9182 in the orders table and report its status.",
        "allowed_tools": ["db_lookup", "format_report"],
        "expected_tools": ["db_lookup", "format_report"],
        "tool_schemas": {
            "db_lookup": {"type": "object", "required": ["table", "id"],
                          "properties": {
                              "table": {"type": "string", "enum": ["users", "orders"]},
                              "id": {"type": "integer", "minimum": 1}},
                          "additionalProperties": False},
        },
        "reference_path": ["db_lookup", "format_report"],
        "policy": [{"forbid_tool": "db_delete"}],
        "final_checks": [{"answer_contains": "shipped"}],
        "budgets": {"max_steps": 4, "max_tokens": 1500},
    })
    trace = Trace(
        run_id="selftest-lookup", task_id="order-lookup",
        calls=[
            Call(1, "db_lookup", {"table": "orders", "id": 9182}, 0),
            Call(2, "format_report", {"style": "short"}, 0),
        ],
        results={
            1: Result(1, True, {"id": 9182, "status": "shipped",
                                "carrier": "NorthLine"}),
            2: Result(2, True, {"report": "Order 9182: shipped"}),
        },
        final=Final(answer="Order 9182 has shipped via NorthLine.",
                    state={"reported": True}),
    )
    return trace, spec


BASES = {"research-brief": _load_example_base,
         "inbox-triage": _inbox_base,
         "order-lookup": _lookup_base}


# ------------------------------------------------------------- controls
# Each control builds a legitimate trace that resembles a defect class
# and names the dimension that must NOT drop versus its base.

def _control_retry_after_error(base: Trace, spec: dict) -> Trace:
    """First attempt at a required tool errors; the agent retries the
    identical call and succeeds. Not waste, and fully recovered."""
    import copy
    mutant = copy.deepcopy(base)
    target = next(c for c in mutant.calls
                  if c.tool in set(spec.get("expected_tools") or []))
    original = mutant.results[target.step]
    mutant.results[target.step] = Result(
        step=target.step, ok=False, error="transient timeout (control)")
    next_step = max(c.step for c in mutant.calls) + 1
    mutant.calls.append(Call(step=next_step, tool=target.tool,
                             args=copy.deepcopy(target.args), line=0))
    retry = copy.deepcopy(original)
    retry.step = next_step
    mutant.results[next_step] = retry
    mutant.calls.sort(key=lambda c: c.step)
    return mutant


def _control_repeat_different_args(base: Trace, spec: dict) -> Trace:
    """Same tool called again with different arguments: new work."""
    import copy
    mutant = copy.deepcopy(base)
    target = mutant.calls[0]
    next_step = max(c.step for c in mutant.calls) + 1
    args = copy.deepcopy(target.args)
    for key, value in args.items():
        if isinstance(value, str):
            args[key] = value + " follow-up"
            break
        if isinstance(value, int):
            args[key] = value + 1
            break
    mutant.calls.append(Call(step=next_step, tool=target.tool, args=args, line=0))
    result = copy.deepcopy(mutant.results[target.step])
    result.step = next_step
    mutant.results[next_step] = result
    return mutant


def _control_prompt_grounded_number(base: Trace, spec: dict) -> Trace:
    """The final answer cites a number that appears only in the task
    prompt (the order id the user themselves gave). Grounded."""
    import copy
    mutant = copy.deepcopy(base)
    if mutant.final is not None and "9182" in spec.get("task_prompt", ""):
        mutant.final.answer += " Reference 9182 confirmed."
    return mutant


CONTROLS = [
    ("retry_after_error_is_recovery_not_waste", _control_retry_after_error,
     "research-brief", ("step_economy", "error_recovery")),
    ("repeat_with_different_args_is_new_work", _control_repeat_different_args,
     "research-brief", ("step_economy",)),
    ("prompt_supplied_number_is_grounded", _control_prompt_grounded_number,
     "order-lookup", ("groundedness",)),
]


def run_selftest() -> dict:
    bases = {name: build() for name, build in BASES.items()}
    report: dict = {"bases": {}, "plants": {}, "controls": []}
    for name, (trace, spec) in bases.items():
        scores = _score_all(trace, spec)
        report["bases"][name] = {
            dim: (round(s, 4) if s is not None else None)
            for dim, s in scores.items()}

    for defect, (plant, dimension) in inject.PLANTS.items():
        planted = caught = 0
        details = []
        for name, (trace, spec) in bases.items():
            mutant = plant(trace, spec)
            if mutant is None:
                details.append(f"{name}: not applicable")
                continue
            planted += 1
            base_score = _score_all(trace, spec)[dimension]
            mutant_score = _score_all(mutant, spec)[dimension]
            hit = (mutant_score is not None and base_score is not None
                   and mutant_score < base_score)
            caught += hit
            details.append(
                f"{name}: {dimension} {base_score} -> {mutant_score} "
                f"({'caught' if hit else 'MISSED'})")
        report["plants"][defect] = {
            "dimension": dimension, "planted": planted, "caught": caught,
            "rate": (caught / planted) if planted else None, "details": details}

    for label, build, base_name, watched in CONTROLS:
        trace, spec = bases[base_name]
        mutant = build(trace, spec)
        base_scores = _score_all(trace, spec)
        mutant_scores = _score_all(mutant, spec)
        ok = all(mutant_scores[d] == base_scores[d] for d in watched)
        report["controls"].append({
            "control": label, "base": base_name, "watched": list(watched),
            "passed": ok,
            "detail": "; ".join(
                f"{d} {base_scores[d]} -> {mutant_scores[d]}" for d in watched)})
    return report


def render_report(report: dict) -> str:
    lines = ["# runreckon self-test results",
             "",
             "Generated by `runreckon selftest --write`. Deterministic: "
             "validate.py re-runs the",
             "self-test and requires this file to reproduce byte for byte.",
             "",
             "## Fault-injection catch rates",
             "",
             "| Defect class | Scorer responsible | Planted | Caught | Rate |",
             "|---|---|---|---|---|"]
    for defect, data in report["plants"].items():
        rate = "n/a" if data["rate"] is None else f"{data['rate']:.3f}"
        lines.append(f"| {defect} | {data['dimension']} | {data['planted']} "
                     f"| {data['caught']} | {rate} |")
    lines += ["", "## Negative controls (legitimate traces that must not be flagged)",
              ""]
    for control in report["controls"]:
        mark = "PASS" if control["passed"] else "FAIL"
        lines.append(f"- [{mark}] {control['control']} "
                     f"(base {control['base']}): {control['detail']}")
    lines += ["", "## Detail", ""]
    for defect, data in report["plants"].items():
        for detail in data["details"]:
            lines.append(f"- {defect}: {detail}")
    lines.append("")
    return "\n".join(lines)
