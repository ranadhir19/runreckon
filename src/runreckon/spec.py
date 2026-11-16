"""Task specs: what a good run of a task was supposed to look like.

A spec is a JSON object. Every field is optional except that a spec with
no fields at all scores nothing; each scorer declares the fields it needs
and reports itself not-applicable when they are absent.

    {
      "task_id": "research-brief",
      "goal": "Research the port's 2024 container volume and save a brief",
      "task_prompt": "the exact prompt the agent saw (a grounding source)",
      "allowed_tools": ["web_search", "fetch_page", "save_brief"],
      "expected_tools": ["web_search", "fetch_page", "save_brief"],
      "tool_schemas": {"web_search": {"type": "object", ...}},
      "reference_path": ["web_search", "fetch_page", "save_brief"],
      "policy": [
        {"forbid_tool": "send_email"},
        {"forbid_arg": {"tool": "fetch_page", "arg": "url",
                        "pattern": "internal"}},
        {"require_before": {"tool": "send_reply", "before": "request_approval"}},
        {"max_calls": {"tool": "web_search", "count": 5}},
        {"forbid_state": {"path": "billing.charged", "equals": true}}
      ],
      "final_checks": [
        {"state_equals": {"path": "brief.saved", "value": true}},
        {"answer_contains": "TEU"},
        {"answer_not_contains": "as an AI"}
      ],
      "budgets": {"max_steps": 8, "max_tokens": 6000,
                  "max_latency_ms": 60000, "max_cost_usd": 0.10},
      "pricing": {"input_per_1k_usd": 0.003, "output_per_1k_usd": 0.015},
      "weights": {"outcome": 0.25, "policy": 0.20}
    }
"""

from __future__ import annotations

import json

DEFAULT_WEIGHTS = {
    "outcome": 0.20,
    "policy": 0.15,
    "argument_validity": 0.15,
    "tool_selection": 0.13,
    "step_economy": 0.13,
    "error_recovery": 0.08,
    "groundedness": 0.08,
    "cost_latency": 0.08,
}


class SpecError(Exception):
    """Raised when a task spec cannot be loaded or is structurally wrong."""


def load_spec(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            spec = json.load(fh)
    except json.JSONDecodeError as exc:
        raise SpecError(f"{path}: invalid JSON ({exc.msg})") from exc
    return check_spec(spec)


def check_spec(spec) -> dict:
    if not isinstance(spec, dict):
        raise SpecError("spec must be a JSON object")
    for key in ("allowed_tools", "expected_tools", "reference_path"):
        if key in spec and not (
                isinstance(spec[key], list)
                and all(isinstance(t, str) for t in spec[key])):
            raise SpecError(f"spec field '{key}' must be a list of tool names")
    if "tool_schemas" in spec and not isinstance(spec["tool_schemas"], dict):
        raise SpecError("spec field 'tool_schemas' must be an object")
    if "policy" in spec and not isinstance(spec["policy"], list):
        raise SpecError("spec field 'policy' must be a list of rules")
    if "final_checks" in spec and not isinstance(spec["final_checks"], list):
        raise SpecError("spec field 'final_checks' must be a list")
    if "budgets" in spec and not isinstance(spec["budgets"], dict):
        raise SpecError("spec field 'budgets' must be an object")
    weights = spec.get("weights", {})
    if not isinstance(weights, dict) or not all(
            isinstance(v, (int, float)) and v >= 0 for v in weights.values()):
        raise SpecError("spec field 'weights' must map dimension names to numbers >= 0")
    return spec


def dig(state: dict, path: str):
    """Resolve a dotted path ('brief.saved') inside a state object."""
    node = state
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None, False
        node = node[part]
    return node, True
