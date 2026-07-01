from __future__ import annotations

from typing import Any


def summarize_safety(safety: dict[str, Any]) -> str:
    parts: list[str] = []
    if safety.get("execution"):
        parts.append(f"execution={safety['execution']}")
    if safety.get("clipboard"):
        parts.append(f"clipboard={safety['clipboard']}")
    if safety.get("navigation"):
        parts.append(f"navigation={safety['navigation']}")
    if safety.get("notes"):
        parts.append(str(safety["notes"]))
    return "; ".join(parts)


def classify_action(action: dict[str, Any]) -> str:
    name = action.get("name", "")
    if name.startswith("copy_"):
        return "clipboard"
    if name.startswith("open_") or name.startswith("visit_") or name.startswith("view_"):
        return "navigation"
    if action.get("method") == "setValueAndChange":
        return "navigation"
    return "other"


def evaluate_action_policy(action: dict[str, Any], safety: dict[str, Any]) -> dict[str, Any]:
    method = action.get("method")
    category = classify_action(action)

    if method not in {"click", "setValueAndChange"}:
        return {
            "allowed": False,
            "reason": f"Unknown or unsupported method: {method}",
            "category": category,
        }

    if category == "clipboard":
        return {
            "allowed": True,
            "category": category,
            "reason": "Clipboard actions require user initiation and are never executed by the relay.",
        }

    if category == "navigation":
        return {
            "allowed": True,
            "category": category,
            "reason": "Navigation actions are user-visible only and default to instruction-only responses.",
        }

    return {
        "allowed": False,
        "reason": "Unknown actions are denied by policy.",
        "category": category,
    }


def should_execute_browser(action: dict[str, Any], browser_control_enabled: bool) -> tuple[bool, str]:
    if not browser_control_enabled:
        return False, "Browser control disabled by WEBMCP_ALLOW_BROWSER_CONTROL=0."

    category = classify_action(action)
    if category != "navigation":
        return False, "Only safe navigation actions are eligible for optional browser opening."

    if action.get("method") != "click":
        return False, "Only click-based navigation actions are eligible for optional browser opening."

    return True, "Safe navigation action eligible for optional browser opening."
