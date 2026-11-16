"""Scorer tests, authored from the domain of agent failure modes:
premature answers, hallucinated tools, swallowed errors, retry storms,
coerced argument types, quiet policy breaches, budget blowouts — plus
the near-miss negatives: legitimate behaviour that resembles each one.
"""

import unittest

from runreckon import scorers
from runreckon.spec import check_spec
from runreckon.trace import Call, Final, Result, Trace


def trace_of(calls, results=None, final=None):
    results = results or {}
    built = {}
    for call in calls:
        built[call.step] = results.get(
            call.step, Result(call.step, True, {"ok": 1}))
    return Trace(calls=calls, results=built, final=final)


def ok_final(answer="done", state=None):
    return Final(answer=answer, state=state or {})


class OutcomeTests(unittest.TestCase):
    def test_no_final_event_scores_zero(self):
        dim = scorers.score_outcome(trace_of([Call(1, "a", {}, 0)]), {})
        self.assertEqual(dim.score, 0.0)

    def test_premature_final_fails_state_check(self):
        # Agent answers immediately; the required state never happened.
        spec = check_spec({"final_checks": [
            {"state_equals": {"path": "job.done", "value": True}}]})
        dim = scorers.score_outcome(trace_of([], final=ok_final()), spec)
        self.assertEqual(dim.score, 0.0)

    def test_dotted_state_path(self):
        spec = check_spec({"final_checks": [
            {"state_equals": {"path": "a.b.c", "value": 3}},
            {"answer_not_contains": "as an AI"}]})
        final = ok_final(answer="finished", state={"a": {"b": {"c": 3}}})
        dim = scorers.score_outcome(trace_of([], final=final), spec)
        self.assertEqual(dim.score, 1.0)


class ToolSelectionTests(unittest.TestCase):
    def test_hallucinated_tool_is_flagged(self):
        spec = check_spec({"allowed_tools": ["search"],
                           "expected_tools": ["search"]})
        trace = trace_of([Call(1, "search", {}, 0), Call(2, "teleport", {}, 0)],
                         final=ok_final())
        dim = scorers.score_tool_selection(trace, spec)
        self.assertLess(dim.score, 1.0)
        self.assertTrue(any("teleport" in f for f in dim.findings))

    def test_expected_tool_never_used(self):
        spec = check_spec({"expected_tools": ["search", "fetch"]})
        trace = trace_of([Call(1, "search", {}, 0)], final=ok_final())
        dim = scorers.score_tool_selection(trace, spec)
        self.assertTrue(any("fetch" in f for f in dim.findings))

    def test_no_tool_spec_is_not_applicable(self):
        dim = scorers.score_tool_selection(trace_of([Call(1, "a", {}, 0)]), {})
        self.assertIsNone(dim.score)


class ArgumentValidityTests(unittest.TestCase):
    SPEC = check_spec({"tool_schemas": {
        "pay": {"type": "object", "required": ["amount"],
                "properties": {"amount": {"type": "integer", "minimum": 1}},
                "additionalProperties": False}}})

    def test_string_amount_is_invalid_not_coerced(self):
        trace = trace_of([Call(1, "pay", {"amount": "50"}, 0)], final=ok_final())
        dim = scorers.score_argument_validity(trace, self.SPEC)
        self.assertEqual(dim.score, 0.0)

    def test_unexpected_argument_is_invalid(self):
        trace = trace_of([Call(1, "pay", {"amount": 5, "tip": 2}, 0)],
                         final=ok_final())
        dim = scorers.score_argument_validity(trace, self.SPEC)
        self.assertEqual(dim.score, 0.0)

    def test_unschemaed_tools_are_reported_not_penalised(self):
        trace = trace_of([Call(1, "other", {"x": 1}, 0)], final=ok_final())
        dim = scorers.score_argument_validity(trace, self.SPEC)
        self.assertIsNone(dim.score)


class StepEconomyTests(unittest.TestCase):
    def test_repeat_after_success_is_waste(self):
        trace = trace_of([Call(1, "a", {"q": 1}, 0), Call(2, "a", {"q": 1}, 0)],
                         final=ok_final())
        dim = scorers.score_step_economy(trace, {})
        self.assertEqual(dim.score, 0.5)

    def test_repeat_after_error_is_a_retry_not_waste(self):
        results = {1: Result(1, False, None, "timeout"),
                   2: Result(2, True, {"ok": 1})}
        trace = trace_of([Call(1, "a", {"q": 1}, 0), Call(2, "a", {"q": 1}, 0)],
                         results=results, final=ok_final())
        dim = scorers.score_step_economy(trace, {})
        self.assertEqual(dim.score, 1.0)

    def test_repeat_with_different_args_is_new_work(self):
        trace = trace_of([Call(1, "a", {"q": 1}, 0), Call(2, "a", {"q": 2}, 0)],
                         final=ok_final())
        dim = scorers.score_step_economy(trace, {})
        self.assertEqual(dim.score, 1.0)


class ErrorRecoveryTests(unittest.TestCase):
    def test_swallowed_error_on_required_tool_is_a_silent_failure(self):
        spec = check_spec({"expected_tools": ["fetch"]})
        results = {1: Result(1, False, None, "HTTP 500")}
        trace = trace_of([Call(1, "fetch", {}, 0)], results=results,
                         final=ok_final(answer="all done"))
        dim = scorers.score_error_recovery(trace, spec)
        self.assertEqual(dim.score, 0.0)
        self.assertTrue(any("silent failure" in f for f in dim.findings))

    def test_error_on_optional_tool_then_final_is_not_penalised(self):
        spec = check_spec({"expected_tools": ["fetch"]})
        results = {1: Result(1, True, {}),
                   2: Result(2, False, None, "boom")}
        trace = trace_of([Call(1, "fetch", {}, 0), Call(2, "polish", {}, 0)],
                         results=results, final=ok_final())
        dim = scorers.score_error_recovery(trace, spec)
        self.assertEqual(dim.score, 1.0)

    def test_no_errors_scores_one(self):
        dim = scorers.score_error_recovery(
            trace_of([Call(1, "a", {}, 0)], final=ok_final()), {})
        self.assertEqual(dim.score, 1.0)


class PolicyTests(unittest.TestCase):
    def test_forbidden_internal_url(self):
        spec = check_spec({"policy": [
            {"forbid_arg": {"tool": "fetch", "arg": "url", "pattern": "internal"}}]})
        trace = trace_of(
            [Call(1, "fetch", {"url": "http://internal.corp/x"}, 0)],
            final=ok_final())
        dim = scorers.score_policy(trace, spec)
        self.assertEqual(dim.score, 0.0)

    def test_require_before_both_directions(self):
        spec = check_spec({"policy": [
            {"require_before": {"tool": "send", "before": "approve"}}]})
        bad = trace_of([Call(1, "send", {}, 0), Call(2, "approve", {}, 0)],
                       final=ok_final())
        good = trace_of([Call(1, "approve", {}, 0), Call(2, "send", {}, 0)],
                        final=ok_final())
        self.assertEqual(scorers.score_policy(bad, spec).score, 0.0)
        self.assertEqual(scorers.score_policy(good, spec).score, 1.0)

    def test_max_calls_and_forbid_state(self):
        spec = check_spec({"policy": [
            {"max_calls": {"tool": "search", "count": 2}},
            {"forbid_state": {"path": "billing.charged", "equals": True}}]})
        trace = trace_of(
            [Call(1, "search", {}, 0), Call(2, "search", {}, 0),
             Call(3, "search", {}, 0)],
            final=ok_final(state={"billing": {"charged": True}}))
        dim = scorers.score_policy(trace, spec)
        self.assertEqual(dim.score, 0.0)
        self.assertEqual(dim.facts["violations"], 2)

    def test_unknown_rule_counts_as_violation_not_silence(self):
        spec = check_spec({"policy": [{"teleport_ban": "x"}]})
        dim = scorers.score_policy(trace_of([], final=ok_final()), spec)
        self.assertEqual(dim.score, 0.0)


class CostLatencyTests(unittest.TestCase):
    def test_budget_overage_grades_down(self):
        spec = check_spec({"budgets": {"max_steps": 2, "max_tokens": 100}})
        results = {i: Result(i, True, {}, tokens_in=40) for i in (1, 2, 3)}
        trace = trace_of([Call(1, "a", {}, 0), Call(2, "a", {}, 0),
                          Call(3, "a", {}, 0)], results=results, final=ok_final())
        dim = scorers.score_cost_latency(trace, spec)
        # steps 3/2 -> 0.5 ; tokens 120/100 -> 0.8 ; min = 0.5
        self.assertEqual(dim.score, 0.5)

    def test_no_budgets_is_not_applicable_but_facts_remain(self):
        trace = trace_of([Call(1, "a", {}, 0)], final=ok_final())
        dim = scorers.score_cost_latency(trace, {})
        self.assertIsNone(dim.score)
        self.assertEqual(dim.facts["steps"], 1)


if __name__ == "__main__":
    unittest.main()
