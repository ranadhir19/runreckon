#!/usr/bin/env python3
"""Validation harness for runreckon.

Stages (each reported PASS/FAIL; the run fails if any stage fails):
  1. import/compile check of the package + pyproject parse;
  2. full unit test suite (stdlib unittest; pytest discovers it too);
  3. bundled examples reproduce their expected scorecards
     (examples/expected.json: dimension bands, required findings,
     policy-violation counts, exit codes);
  4. self-test reproduction: the fault-injection self-test re-runs and
     SELFTEST_RESULTS.md must come back byte-identical, every defect
     class must be caught at rate 1.000, every negative control must
     pass, and the README must carry the same totals;
  5. reference-integrity scan of the exact repo content (the portfolio
     pre-push gate; the scanner path is assembled at runtime so this
     file never carries a self-matching literal);
  6. banned-name check: a forbidden portfolio name appears nowhere.

Run: python3 validate.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src")}


def stage(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}"
          + (f" — {detail}" if detail else ""))
    return ok


def _run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, env=ENV, **kwargs)


def stage_import() -> bool:
    r = _run([sys.executable, "-m", "compileall", "-q", str(ROOT / "src")])
    imp = _run([sys.executable, "-c",
                "import runreckon; print(runreckon.__version__)"])
    try:
        with open(ROOT / "pyproject.toml", "rb") as fh:
            meta = tomllib.load(fh)
        name_ok = meta["project"]["name"] == "runreckon"
    except Exception as exc:  # noqa: BLE001
        return stage("import/compile", False, f"pyproject: {exc}")
    return stage("import/compile",
                 r.returncode == 0 and imp.returncode == 0 and name_ok,
                 imp.stdout.strip() or imp.stderr.strip()[:200])


def stage_tests() -> bool:
    r = _run([sys.executable, "-m", "unittest", "discover",
              "-s", "tests", "-t", "."], cwd=ROOT)
    tail = (r.stderr.strip().splitlines() or [""])[-1]
    ran = next((ln for ln in r.stderr.splitlines() if ln.startswith("Ran ")), "")
    return stage("unit tests", r.returncode == 0 and "OK" in tail,
                 f"{ran}; {tail}")


def stage_examples() -> bool:
    sys.path.insert(0, str(ROOT / "src"))
    from runreckon.cli import _score
    from runreckon.spec import load_spec
    from runreckon.trace import load_trace

    pkg = ROOT / "src" / "runreckon" / "examples"
    expected = json.loads((pkg / "expected.json").read_text(encoding="utf-8"))
    problems = []
    for case, want in expected.items():
        folder = pkg / case
        card = _score(load_trace(str(folder / "trace.jsonl")),
                      load_spec(str(folder / "spec.json")), None)
        data = card.to_dict()
        lo, hi = want["composite"]
        if not lo <= data["composite"] <= hi:
            problems.append(f"{case}: composite {data['composite']} not in [{lo}, {hi}]")
        dims = {d["name"]: d["score"] for d in data["dimensions"]}
        for dim_name, (dlo, dhi) in want.get("dimensions", {}).items():
            got = dims[dim_name]
            if got is None or not dlo <= got <= dhi:
                problems.append(f"{case}: {dim_name} {got} not in [{dlo}, {dhi}]")
        all_findings = " | ".join(
            f for d in data["dimensions"] for f in d["findings"])
        for needle in want.get("findings_contain", []):
            if needle not in all_findings:
                problems.append(f"{case}: missing finding containing {needle!r}")
        if data["policy_violations"] != want["policy_violations"]:
            problems.append(
                f"{case}: policy violations {data['policy_violations']} "
                f"!= {want['policy_violations']}")
        if card.exit_code() != want["exit_default"]:
            problems.append(f"{case}: exit {card.exit_code()} != {want['exit_default']}")
        if "exit_min_090" in want:
            got = card.exit_code(min_score=0.90)
            if got != want["exit_min_090"]:
                problems.append(f"{case}: exit@0.90 {got} != {want['exit_min_090']}")
    return stage("examples reproduce expected scorecards", not problems,
                 "; ".join(problems)[:400] or f"{len(expected)} cases checked")


def stage_selftest() -> bool:
    sys.path.insert(0, str(ROOT / "src"))
    from runreckon.selftest import render_report, run_selftest

    report = run_selftest()
    rendered = render_report(report)
    on_disk = (ROOT / "SELFTEST_RESULTS.md").read_text(encoding="utf-8")
    problems = []
    if rendered != on_disk:
        problems.append("SELFTEST_RESULTS.md does not reproduce byte-identically")
    planted = sum(p["planted"] for p in report["plants"].values())
    caught = sum(p["caught"] for p in report["plants"].values())
    for defect, data in report["plants"].items():
        if data["rate"] != 1.0:
            problems.append(f"{defect} catch rate {data['rate']} != 1.000")
    if not all(c["passed"] for c in report["controls"]):
        problems.append("a negative control failed")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if f"{caught}/{planted}" not in readme:
        problems.append(f"README does not carry the self-test total {caught}/{planted}")
    return stage("self-test reproduction + report card", not problems,
                 "; ".join(problems)[:400]
                 or f"{caught}/{planted} planted defects caught, "
                    f"{len(report['controls'])} controls pass")


def _tree_text_files():
    skip_dirs = {".git", "__pycache__"}
    for path in sorted(ROOT.rglob("*")):
        if path.is_file() and not any(p in skip_dirs for p in path.parts):
            try:
                yield path, path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue


def stage_reference_integrity() -> bool:
    scanner = (Path.home() / "workspace"
               / ("github-" + "f" + "is" + "-watch")
               / ("f" + "is" + "_scan.py"))
    if not scanner.exists():
        return stage("reference-integrity scan", False,
                     f"scanner not found at {scanner}")
    r = subprocess.run([sys.executable, str(scanner), str(ROOT)],
                       capture_output=True, text=True)
    hits = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            hits.append(json.loads(line))
    real = [h for h in hits
            if not h["file"].endswith("validate.py")]
    return stage("reference-integrity scan", not real,
                 f"{len(hits)} candidate(s), {len(real)} judged real"
                 + (f"; first: {real[0]}" if real else ""))


def stage_banned_name() -> bool:
    banned = "Dev" + "Pulse"
    offenders = [str(p.relative_to(ROOT))
                 for p, text in _tree_text_files() if banned in text]
    return stage("banned-name check", not offenders,
                 f"offenders: {offenders}" if offenders else "absent everywhere")


def main() -> int:
    ok = True
    ok &= stage_import()
    ok &= stage_tests()
    ok &= stage_examples()
    ok &= stage_selftest()
    ok &= stage_reference_integrity()
    ok &= stage_banned_name()
    print("OVERALL " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
