import unittest

from runreckon.semantic import (calibrate, extract_claims, judge_report,
                                score_groundedness, standin_judge)
from runreckon.spec import check_spec
from runreckon.trace import Call, Final, Result, Trace


def grounded_trace(answer, outputs, prompt=""):
    results = {i + 1: Result(i + 1, True, out) for i, out in enumerate(outputs)}
    calls = [Call(i + 1, "tool", {}, 0) for i in range(len(outputs))]
    return Trace(calls=calls, results=results,
                 final=Final(answer=answer, state={})), \
        check_spec({"task_prompt": prompt})


class GroundednessTests(unittest.TestCase):
    def test_invented_number_is_caught(self):
        trace, spec = grounded_trace(
            "Volume rose to 9.99 million units.", [{"volume": "1.32 million"}])
        dim = score_groundedness(trace, spec)
        self.assertEqual(dim.score, 0.0)
        self.assertTrue(any("9.99" in f for f in dim.findings))

    def test_number_from_tool_result_is_supported(self):
        trace, spec = grounded_trace(
            "Volume was 1.32 million units.", [{"volume": "1.32 million"}])
        self.assertEqual(score_groundedness(trace, spec).score, 1.0)

    def test_number_from_the_task_prompt_is_supported(self):
        # The user supplied the figure; citing it back is not invention.
        trace, spec = grounded_trace(
            "Order 9182 confirmed.", [{"status": "shipped"}],
            prompt="Look up order 9182 please.")
        self.assertEqual(score_groundedness(trace, spec).score, 1.0)

    def test_thousands_separators_normalise(self):
        trace, spec = grounded_trace(
            "Total was 1,250 items.", [{"total": 1250}])
        self.assertEqual(score_groundedness(trace, spec).score, 1.0)

    def test_invented_url_is_caught(self):
        trace, spec = grounded_trace(
            "Details at https://example.com/report.", [{"x": 1}])
        dim = score_groundedness(trace, spec)
        self.assertEqual(dim.score, 0.0)

    def test_email_at_sentence_end_is_not_a_false_claim(self):
        # Regression: the sentence-final period must not poison the claim.
        trace, spec = grounded_trace(
            "Reply sent to ana@example.com.", [{"from": "ana@example.com"}])
        self.assertEqual(score_groundedness(trace, spec).score, 1.0)

    def test_no_checkable_claims_is_not_applicable(self):
        trace, spec = grounded_trace("All done, thanks.", [{"x": 1}])
        self.assertIsNone(score_groundedness(trace, spec).score)


class JudgeTests(unittest.TestCase):
    def test_standin_calibration_is_measured(self):
        cal = calibrate(standin_judge)
        self.assertEqual(cal["items"], 12)
        # Measured 2026-11-15: agreement 0.833, kappa 0.667, with one
        # paraphrase miss and one negation false-pass. The bounds below
        # pin the mechanism, not perfection.
        self.assertGreaterEqual(cal["agreement"], 0.75)
        self.assertGreaterEqual(cal["kappa"], 0.5)
        self.assertEqual(cal["confusion"]["fp"], 1)
        self.assertEqual(cal["confusion"]["fn"], 1)

    def test_judge_report_carries_calibration(self):
        trace, spec = grounded_trace("Volume was 1.32 million.",
                                     [{"volume": "1.32 million"}])
        report = judge_report(trace, spec, standin_judge, "standin")
        self.assertIn("calibration", report)
        self.assertTrue(report["verdict"]["grounded"])

    def test_extract_claims_kinds(self):
        claims = extract_claims(
            'See https://x.io/a or mail a@b.co; "quoted text" and 42.5 percent')
        self.assertIn("42.5", claims["numbers"])
        self.assertEqual(claims["urls"], ["https://x.io/a"])
        self.assertEqual(claims["emails"], ["a@b.co"])
        self.assertEqual(claims["quoted"], ["quoted text"])


if __name__ == "__main__":
    unittest.main()
