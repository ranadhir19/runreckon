"""runreckon command line.

    runreckon score TRACE.jsonl --spec SPEC.json [--format text|json]
                        [--min-score 0.75] [--judge standin]
                        [--no-fail-on-policy]
    runreckon demo [--format text|json]
    runreckon selftest [--format text|json] [--write PATH]
    runreckon version

Exit codes: 0 = the run passes (composite >= --min-score and, unless
--no-fail-on-policy, no policy violation); 1 = the run fails;
2 = the trace or spec could not be read (format error).
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from . import __version__
from .scorecard import Scorecard
from .scorers import run_deterministic
from .semantic import judge_report, score_groundedness, standin_judge
from .spec import SpecError, load_spec
from .trace import TraceFormatError, load_trace

EXAMPLES_DIR = Path(__file__).parent / "examples"
EXAMPLE_CASES = ["clean-run", "sloppy-success", "policy-breach"]


def _load_judge(name: str):
    if name == "standin":
        return standin_judge, "standin (deterministic heuristic)"
    module_name, _, func_name = name.partition(":")
    if not func_name:
        raise SpecError(f"judge {name!r} must be 'standin' or 'module:function'")
    module = importlib.import_module(module_name)
    return getattr(module, func_name), name


def _score(trace, spec, judge_name: str | None) -> Scorecard:
    dimensions = run_deterministic(trace, spec)
    dimensions.append(score_groundedness(trace, spec))
    judge = None
    if judge_name:
        judge_fn, label = _load_judge(judge_name)
        judge = judge_report(trace, spec, judge_fn, label)
    return Scorecard(trace, spec, dimensions, judge=judge)


def cmd_score(args) -> int:
    try:
        trace = load_trace(args.trace)
        spec = load_spec(args.spec)
        card = _score(trace, spec, args.judge)
    except (TraceFormatError, SpecError, OSError) as exc:
        print(f"runreckon: cannot score: {exc}", file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(card.to_dict(), indent=2))
    else:
        print(card.render_text())
    return card.exit_code(min_score=args.min_score,
                          fail_on_policy=not args.no_fail_on_policy)


def cmd_demo(args) -> int:
    worst = 0
    for case in EXAMPLE_CASES:
        folder = EXAMPLES_DIR / case
        trace = load_trace(str(folder / "trace.jsonl"))
        spec = load_spec(str(folder / "spec.json"))
        card = _score(trace, spec, None)
        if args.format == "json":
            print(json.dumps({case: card.to_dict()}, indent=2))
        else:
            print(f"### example: {case}")
            print(card.render_text())
            print()
        worst = max(worst, card.exit_code())
    return worst


def cmd_selftest(args) -> int:
    from .selftest import render_report, run_selftest
    report = run_selftest()
    if args.write:
        Path(args.write).write_text(render_report(report), encoding="utf-8")
        print(f"self-test report written to {args.write}")
    elif args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(render_report(report))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="runreckon",
        description="Score how an agent executed a run, not just whether it finished.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_score = sub.add_parser("score", help="score one trace against a task spec")
    p_score.add_argument("trace", help="path to the JSONL trace")
    p_score.add_argument("--spec", required=True, help="path to the task spec JSON")
    p_score.add_argument("--format", choices=["text", "json"], default="text")
    p_score.add_argument("--min-score", type=float, default=0.75,
                         help="minimum composite (0-1) to pass (default 0.75)")
    p_score.add_argument("--judge", default=None,
                         help="'standin' or 'module:function' — off by default; "
                              "when enabled, its calibration is printed")
    p_score.add_argument("--no-fail-on-policy", action="store_true",
                         help="do not hard-fail on policy violations")
    p_score.set_defaults(func=cmd_score)

    p_demo = sub.add_parser("demo", help="score the three bundled example runs")
    p_demo.add_argument("--format", choices=["text", "json"], default="text")
    p_demo.set_defaults(func=cmd_demo)

    p_self = sub.add_parser(
        "selftest", help="fault-injection self-test: measure the scorer itself")
    p_self.add_argument("--format", choices=["text", "json"], default="text")
    p_self.add_argument("--write", default=None,
                        help="write the canonical markdown report to this path")
    p_self.set_defaults(func=cmd_selftest)

    p_ver = sub.add_parser("version", help="print the version")
    p_ver.set_defaults(func=lambda _args: print(__version__) or 0)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
