"""Scorecard assembly: composite, verdict, rendering.

The composite is a weighted mean over the dimensions that were actually
scored; not-applicable dimensions are excluded and the weights
renormalised, and the scorecard names them. Policy is also a hard gate:
a run with a policy violation fails regardless of its composite, unless
the caller explicitly disables that gate.
"""

from __future__ import annotations

from .scorers import Dimension
from .spec import DEFAULT_WEIGHTS
from .trace import Trace

VERDICTS = [(0.90, "sound"), (0.75, "serviceable"), (0.50, "shaky"), (0.0, "unsound")]


def verdict_for(composite: float) -> str:
    for floor, label in VERDICTS:
        if composite >= floor:
            return label
    return "unsound"


class Scorecard:
    def __init__(self, trace: Trace, spec: dict, dimensions: list[Dimension],
                 judge: dict | None = None):
        self.trace = trace
        self.spec = spec
        self.dimensions = dimensions
        self.judge = judge
        weights = dict(DEFAULT_WEIGHTS)
        weights.update(spec.get("weights", {}))
        scored = [d for d in dimensions if d.score is not None]
        total_weight = sum(weights.get(d.name, 0.0) for d in scored)
        if total_weight > 0:
            self.composite = sum(
                d.score * weights.get(d.name, 0.0) for d in scored) / total_weight
        else:
            self.composite = 0.0
        self.verdict = verdict_for(self.composite)
        policy = next((d for d in dimensions if d.name == "policy"), None)
        self.policy_violations = (
            policy.facts.get("violations", 0) if policy and policy.score is not None else 0)

    def exit_code(self, min_score: float = 0.75, fail_on_policy: bool = True) -> int:
        if fail_on_policy and self.policy_violations:
            return 1
        return 0 if self.composite >= min_score else 1

    def to_dict(self) -> dict:
        return {
            "run_id": self.trace.run_id,
            "task_id": self.spec.get("task_id") or self.trace.task_id,
            "composite": round(self.composite, 4),
            "verdict": self.verdict,
            "policy_violations": self.policy_violations,
            "dimensions": [
                {"name": d.name,
                 "score": (round(d.score, 4) if d.score is not None else None),
                 "findings": d.findings,
                 "facts": d.facts}
                for d in self.dimensions
            ],
            "judge": self.judge,
            "totals": {"steps": len(self.trace.calls),
                       "tokens": self.trace.total_tokens,
                       "latency_ms": self.trace.total_latency_ms},
        }

    def render_text(self) -> str:
        data = self.to_dict()
        lines = []
        title = f"runreckon scorecard — task {data['task_id'] or '(unnamed)'}"
        if data["run_id"]:
            title += f", run {data['run_id']}"
        lines.append(title)
        lines.append("=" * len(title))
        for dim in data["dimensions"]:
            score = "  n/a" if dim["score"] is None else f"{dim['score'] * 100:5.1f}"
            lines.append(f"{dim['name']:<20} {score}")
            for finding in dim["findings"]:
                lines.append(f"    - {finding}")
        lines.append("-" * len(title))
        lines.append(f"{'COMPOSITE':<20} {self.composite * 100:5.1f}  — {self.verdict}")
        if self.policy_violations:
            lines.append(f"POLICY: {self.policy_violations} violation(s) — hard fail")
        totals = data["totals"]
        lines.append(
            f"totals: {totals['steps']} steps, {totals['tokens']} tokens, "
            f"{totals['latency_ms']:.0f} ms recorded latency")
        if self.judge:
            cal = self.judge["calibration"]
            lines.append(
                f"judge ({self.judge['judge']}): grounded="
                f"{self.judge['verdict']['grounded']} — {self.judge['verdict']['rationale']}; "
                f"calibration on {cal['items']} labelled items: agreement "
                f"{cal['agreement']:.3f}, kappa {cal['kappa']:.3f}, "
                f"precision {cal['precision']:.3f}, recall {cal['recall']:.3f} "
                "(reported alongside the deterministic score, never blended)")
        else:
            lines.append("judge: not configured — deterministic scoring only")
        return "\n".join(lines)
