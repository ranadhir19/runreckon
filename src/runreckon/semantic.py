"""Semantic scoring: groundedness of the final answer.

Two layers, kept separate on the scorecard because they are different
kinds of evidence:

1. **Deterministic support check** (always on). The checkable claims in
   the final answer — numbers, URLs, email addresses, quoted strings —
   must appear in the evidence the agent actually had: the tool results,
   the final state, the task prompt, or the spec goal. A number the
   agent invented is caught exactly, not estimated.

2. **Judge layer** (off by default). A pluggable judge callable may
   assess the answer against the evidence, but a judge is only trusted
   as far as it has been measured: whenever a judge is enabled, its
   agreement, Cohen's kappa, and per-class precision and recall on the
   bundled labelled calibration set are computed and printed on the
   scorecard next to its verdict. Agreement alone can hide a judge
   that is strong on one class and weak on the other; the split
   cannot. The judge's verdict is reported alongside the deterministic
   score, never blended into it — blending would hide disagreement
   between the two.
"""

from __future__ import annotations

import json
import re

from .scorers import Dimension
from .trace import Trace

_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d+")
_URL_RE = re.compile(r"https?://[^\s)\"']+")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_QUOTED_RE = re.compile(r'"([^"]{3,})"')


def _normalise_number(token: str) -> str:
    value = float(token.replace(",", ""))
    if value == int(value):
        return str(int(value))
    return repr(value)


def extract_claims(text: str) -> dict[str, list[str]]:
    claims = {"numbers": [], "urls": [], "emails": [], "quoted": []}
    for match in _NUMBER_RE.finditer(text or ""):
        claims["numbers"].append(_normalise_number(match.group(0)))
    claims["urls"] = [u.rstrip(".,") for u in _URL_RE.findall(text or "")]
    claims["emails"] = [e.rstrip(".") for e in _EMAIL_RE.findall(text or "")]
    claims["quoted"] = _QUOTED_RE.findall(text or "")
    return claims


def _evidence_text(trace: Trace, spec: dict) -> str:
    parts = [spec.get("task_prompt", ""), spec.get("goal", "")]
    for result in trace.results.values():
        if result.output is not None:
            parts.append(json.dumps(result.output, default=str))
    if trace.final:
        parts.append(json.dumps(trace.final.state, default=str))
    return "\n".join(parts)


def score_groundedness(trace: Trace, spec: dict) -> Dimension:
    dim = Dimension("groundedness", None)
    if trace.final is None:
        dim.score = 0.0
        dim.findings.append("no final answer to ground")
        return dim
    claims = extract_claims(trace.final.answer)
    total = sum(len(v) for v in claims.values())
    if total == 0:
        dim.facts["note"] = "final answer contains no checkable claims"
        return dim
    evidence = _evidence_text(trace, spec)
    evidence_numbers = {
        _normalise_number(m.group(0)) for m in _NUMBER_RE.finditer(evidence)}
    evidence_lower = evidence.lower()
    supported = 0
    for number in claims["numbers"]:
        if number in evidence_numbers:
            supported += 1
        else:
            dim.findings.append(
                f"ungrounded claim: number '{number}' appears in the final "
                "answer but in no tool result, state, or task prompt")
    for kind in ("urls", "emails", "quoted"):
        for item in claims[kind]:
            if item.lower() in evidence_lower:
                supported += 1
            else:
                dim.findings.append(
                    f"ungrounded claim: {kind[:-1]} '{item}' appears in the "
                    "final answer but in no tool result, state, or task prompt")
    dim.score = supported / total
    dim.facts["claims_checked"] = total
    dim.facts["claims_supported"] = supported
    return dim


# ---------------------------------------------------------------- judge layer

_STOPWORDS = set(
    "the a an and or of to in is are was were it its this that with for on "
    "as at by from be has have had not but".split())


def standin_judge(answer: str, evidence: str) -> dict:
    """A deterministic stand-in judge, shipped so the judge mechanism —
    including its calibration — can be exercised offline with no model.
    Rule: every number in the answer must appear in the evidence, and at
    least 30% of the answer's content words must appear there too. It is
    a heuristic and is labelled a stand-in wherever its verdict appears;
    its measured calibration (printed on every scorecard that enables
    it) exposes its limits — it misses heavy paraphrase and can be
    fooled by negation. Replace it with a real model judge via the same
    callable signature: judge(answer, evidence) -> {"grounded": bool,
    "rationale": str}."""
    answer_numbers = {_normalise_number(m.group(0))
                      for m in _NUMBER_RE.finditer(answer or "")}
    evidence_numbers = {_normalise_number(m.group(0))
                        for m in _NUMBER_RE.finditer(evidence or "")}
    unsupported = answer_numbers - evidence_numbers
    if unsupported:
        return {"grounded": False,
                "rationale": f"unsupported number(s) {sorted(unsupported)} "
                             "(stand-in heuristic)"}
    words = {w for w in re.findall(r"[a-z]{4,}", (answer or "").lower())
             if w not in _STOPWORDS}
    if not words:
        return {"grounded": True, "rationale": "no content words to assess"}
    evidence_words = set(re.findall(r"[a-z]{4,}", (evidence or "").lower()))
    overlap = len(words & evidence_words) / len(words)
    return {"grounded": overlap >= 0.3,
            "rationale": f"content-word overlap {overlap:.2f} (stand-in heuristic)"}


CALIBRATION_SET = [
    {"answer": "The port handled 1.32 million TEU in 2024.",
     "evidence": "search result: JAXPORT moved 1.32 million TEU during 2024",
     "gold": True},
    {"answer": "The port handled 2.10 million TEU in 2024.",
     "evidence": "search result: JAXPORT moved 1.32 million TEU during 2024",
     "gold": False},
    {"answer": "The meeting is scheduled for Tuesday at 10:00 in room 4.",
     "evidence": "calendar event: Tuesday 10:00, room 4, project meeting",
     "gold": True},
    {"answer": "The meeting is scheduled for Friday at 15:30 in room 9.",
     "evidence": "calendar event: Tuesday 10:00, room 4, project meeting",
     "gold": False},
    {"answer": "Revenue grew 12 percent after the pricing change.",
     "evidence": "report: revenue grew 12% year over year following the new pricing",
     "gold": True},
    {"answer": "Revenue grew 48 percent after the pricing change.",
     "evidence": "report: revenue grew 12% year over year following the new pricing",
     "gold": False},
    {"answer": "The file report.pdf was saved to the archive folder.",
     "evidence": "tool result: saved report.pdf to archive/",
     "gold": True},
    {"answer": "The file report.pdf was emailed to the whole company.",
     "evidence": "tool result: saved report.pdf to archive/",
     "gold": False},
    {"answer": "Three tickets remain open, all assigned to the support queue.",
     "evidence": "query result: 3 open tickets, queue = support",
     "gold": True},
    {"answer": "No tickets remain open; the queue is completely clear.",
     "evidence": "query result: 3 open tickets, queue = support",
     "gold": False},
    {"answer": "The server responded in 240 milliseconds with status 200.",
     "evidence": "probe output: status 200, latency 240 ms",
     "gold": True},
    {"answer": "The server responded in 240 milliseconds with status 503.",
     "evidence": "probe output: status 200, latency 240 ms",
     "gold": False},
]


def calibrate(judge) -> dict:
    """Measure a judge against the labelled calibration set."""
    agree = 0
    tp = fp = tn = fn = 0
    for item in CALIBRATION_SET:
        verdict = bool(judge(item["answer"], item["evidence"])["grounded"])
        if verdict == item["gold"]:
            agree += 1
        if verdict and item["gold"]:
            tp += 1
        elif verdict and not item["gold"]:
            fp += 1
        elif not verdict and not item["gold"]:
            tn += 1
        else:
            fn += 1
    n = len(CALIBRATION_SET)
    agreement = agree / n
    p_judge = (tp + fp) / n
    p_gold = (tp + fn) / n
    p_chance = p_judge * p_gold + (1 - p_judge) * (1 - p_gold)
    kappa = (agreement - p_chance) / (1 - p_chance) if p_chance < 1 else 1.0
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    return {"items": n, "agreement": round(agreement, 3),
            "kappa": round(kappa, 3),
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn}}


def judge_report(trace: Trace, spec: dict, judge, judge_name: str) -> dict:
    """Run an enabled judge on this run and calibrate it. The verdict is
    reported alongside the deterministic groundedness score, never
    blended into it."""
    evidence = _evidence_text(trace, spec)
    verdict = judge(trace.final.answer if trace.final else "", evidence)
    return {"judge": judge_name,
            "verdict": verdict,
            "calibration": calibrate(judge)}
