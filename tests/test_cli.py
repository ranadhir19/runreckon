import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from runreckon import cli

EXAMPLES = Path(cli.EXAMPLES_DIR)


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def test_score_clean_example_exits_zero(self):
        code, out, _ = run_cli([
            "score", str(EXAMPLES / "clean-run" / "trace.jsonl"),
            "--spec", str(EXAMPLES / "clean-run" / "spec.json")])
        self.assertEqual(code, 0)
        self.assertIn("COMPOSITE", out)
        self.assertIn("sound", out)

    def test_score_policy_breach_exits_one(self):
        code, out, _ = run_cli([
            "score", str(EXAMPLES / "policy-breach" / "trace.jsonl"),
            "--spec", str(EXAMPLES / "policy-breach" / "spec.json")])
        self.assertEqual(code, 1)
        self.assertIn("POLICY", out)

    def test_score_sloppy_passes_default_but_fails_a_strict_gate(self):
        argv = ["score", str(EXAMPLES / "sloppy-success" / "trace.jsonl"),
                "--spec", str(EXAMPLES / "sloppy-success" / "spec.json")]
        code, _, _ = run_cli(argv)
        self.assertEqual(code, 0)
        code, _, _ = run_cli(argv + ["--min-score", "0.90"])
        self.assertEqual(code, 1)

    def test_score_json_format(self):
        code, out, _ = run_cli([
            "score", str(EXAMPLES / "clean-run" / "trace.jsonl"),
            "--spec", str(EXAMPLES / "clean-run" / "spec.json"),
            "--format", "json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["composite"], 1.0)
        self.assertEqual(data["verdict"], "sound")
        self.assertEqual(len(data["dimensions"]), 8)

    def test_malformed_trace_exits_two(self):
        bad = EXAMPLES / "clean-run" / "spec.json"  # a spec is not a trace
        code, _, err = run_cli([
            "score", str(bad), "--spec",
            str(EXAMPLES / "clean-run" / "spec.json")])
        self.assertEqual(code, 2)
        self.assertIn("cannot score", err)

    def test_missing_file_exits_two(self):
        code, _, _ = run_cli([
            "score", "/nonexistent/trace.jsonl", "--spec",
            str(EXAMPLES / "clean-run" / "spec.json")])
        self.assertEqual(code, 2)

    def test_demo_runs_and_reports_all_cases(self):
        code, out, _ = run_cli(["demo"])
        self.assertEqual(code, 1)  # the policy-breach case must fail
        for case in ("clean-run", "sloppy-success", "policy-breach"):
            self.assertIn(case, out)

    def test_selftest_json_shape(self):
        code, out, _ = run_cli(["selftest", "--format", "json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        for defect in ("wrong_tool", "invalid_args", "ungrounded_claim",
                       "policy_breach", "loop_waste", "silent_failure"):
            self.assertEqual(data["plants"][defect]["rate"], 1.0, defect)
        self.assertTrue(all(c["passed"] for c in data["controls"]))

    def test_version(self):
        code, out, _ = run_cli(["version"])
        self.assertEqual(code, 0)
        self.assertIn("0.1.0", out)


if __name__ == "__main__":
    unittest.main()
