from __future__ import annotations

import os
import webbrowser
from dataclasses import dataclass
from typing import Any

from logging_setup import configure_logging
from manifest import ManifestLoader, ManifestSnapshot
from policy import evaluate_action_policy, should_execute_browser, summarize_safety


BUILTIN_TOOLS = {
    "webmcp_manifest_status",
    "webmcp_list_actions",
    "webmcp_get_action",
    "webmcp_call_action",
}


@dataclass
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]


class WebMCPRelay:
    def __init__(self, manifest_url: str | None = None) -> None:
        self.logger = configure_logging()
        self.loader = ManifestLoader(manifest_url=manifest_url)
        self.browser_control_enabled = os.environ.get("WEBMCP_ALLOW_BROWSER_CONTROL", "0") == "1"
        self.snapshot = self.loader.fetch()
        self.actions = self.snapshot.document.get("actions", [])
        self.actions_by_name = {action["name"]: action for action in self.actions}

    def refresh_manifest(self) -> ManifestSnapshot:
        self.snapshot = self.loader.fetch()
        self.actions = self.snapshot.document.get("actions", [])
        self.actions_by_name = {action["name"]: action for action in self.actions}
        return self.snapshot

    def manifest_status(self) -> dict[str, Any]:
        doc = self.snapshot.document
        return {
            "ok": True,
            "manifest_url": self.snapshot.manifest_url,
            "fetched_at": self.snapshot.fetched_at,
            "site_name": doc.get("name"),
            "title": doc.get("title"),
            "action_count": len(doc.get("actions", [])),
            "safety": doc.get("safety", {}),
            "safety_summary": summarize_safety(doc.get("safety", {})),
        }

    def list_actions(self) -> dict[str, Any]:
        safety = self.snapshot.document.get("safety", {})
        items = []
        for action in self.actions:
            policy = evaluate_action_policy(action, safety)
            items.append(
                {
                    "name": action.get("name"),
                    "description": action.get("description"),
                    "method": action.get("method"),
                    "selector": action.get("selector"),
                    "risk_category": policy.get("category"),
                    "safety_note": policy.get("reason"),
                }
            )
        return {"ok": True, "actions": items}

    def get_action(self, action_name: str) -> dict[str, Any]:
        action = self.actions_by_name.get(action_name)
        if not action:
            return {"ok": False, "error": f"Unknown action: {action_name}"}
        return {
            "ok": True,
            "action": action,
            "homepage": self.snapshot.document.get("homepage"),
            "safety": self.snapshot.document.get("safety", {}),
        }

    def _validate_params(self, action: dict[str, Any], params: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        parameters = action.get("parameters", {})
        value_spec = parameters.get("value")
        if action.get("method") != "setValueAndChange":
            return True, {}

        if value_spec is None:
            return False, {"ok": False, "error": "Action is missing value parameter specification."}

        value = params.get("value")
        if value is None:
            return False, {
                "ok": False,
                "error": "Missing required parameter: value",
                "allowed_values": value_spec.get("enum", []),
            }

        allowed_values = value_spec.get("enum", [])
        if value not in allowed_values:
            self.logger.warning("Parameter validation failed for %s: %s", action.get("name"), value)
            return False, {
                "ok": False,
                "error": f"Invalid value for {action.get('name')}: {value}",
                "allowed_values": allowed_values,
            }

        return True, {}

    def _instruction_payload(self, action: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        safety = self.snapshot.document.get("safety", {})
        payload = {
            "ok": True,
            "action": action.get("name"),
            "description": action.get("description"),
            "method": action.get("method"),
            "selector": action.get("selector"),
            "homepage": self.snapshot.document.get("homepage"),
            "safety": "navigation must be user-visible" if safety.get("navigation") else summarize_safety(safety),
            "safety_summary": summarize_safety(safety),
            "policy_mode": "instruction_only" if not self.browser_control_enabled else "browser_control_optional",
        }
        if action.get("method") == "click":
            payload["suggested_browser_instruction"] = "Open homepage, find selector, perform user-visible click."
        elif action.get("method") == "setValueAndChange":
            payload["value"] = params.get("value")
            payload["suggested_browser_instruction"] = (
                "Open homepage, locate selector, set the provided value, and trigger a user-visible change event."
            )
        return payload

    def call_action(self, action_name: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        action = self.actions_by_name.get(action_name)
        if not action:
            self.logger.warning("Denied unknown action: %s", action_name)
            return {"ok": False, "error": f"Unknown action: {action_name}"}

        safety = self.snapshot.document.get("safety", {})
        policy = evaluate_action_policy(action, safety)
        if not policy["allowed"]:
            self.logger.warning("Denied action %s: %s", action_name, policy["reason"])
            return {"ok": False, "error": policy["reason"]}

        valid, error_payload = self._validate_params(action, params)
        if not valid:
            return error_payload

        self.logger.info("Tool call for action %s", action_name)
        payload = self._instruction_payload(action, params)

        executable, reason = should_execute_browser(action, self.browser_control_enabled)
        payload["execution_result"] = reason
        if executable:
            homepage = self.snapshot.document.get("homepage")
            webbrowser.open(homepage)
            payload["browser_opened"] = True
        else:
            payload["browser_opened"] = False

        return payload

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        arguments = arguments or {}
        self.logger.info("MCP tool invoked: %s", tool_name)
        if tool_name == "webmcp_manifest_status":
            return self.manifest_status()
        if tool_name == "webmcp_list_actions":
            return self.list_actions()
        if tool_name == "webmcp_get_action":
            return self.get_action(arguments.get("action_name", ""))
        if tool_name == "webmcp_call_action":
            return self.call_action(arguments.get("action_name", ""), arguments.get("parameters", {}))
        if tool_name in self.actions_by_name:
            return self.call_action(tool_name, arguments)
        return {"ok": False, "error": f"Unknown tool: {tool_name}"}

    def tools(self) -> list[ToolDefinition]:
        tools = [
            ToolDefinition(
                name="webmcp_manifest_status",
                description="Return current manifest metadata and safety policy.",
                input_schema={"type": "object", "properties": {}},
            ),
            ToolDefinition(
                name="webmcp_list_actions",
                description="List all WebMCP actions exposed by the current manifest.",
                input_schema={"type": "object", "properties": {}},
            ),
            ToolDefinition(
                name="webmcp_get_action",
                description="Return the full WebMCP action definition for a named action.",
                input_schema={
                    "type": "object",
                    "properties": {"action_name": {"type": "string"}},
                    "required": ["action_name"],
                },
            ),
            ToolDefinition(
                name="webmcp_call_action",
                description="Validate an action call and return a safe structured instruction payload.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "action_name": {"type": "string"},
                        "parameters": {"type": "object"},
                    },
                    "required": ["action_name"],
                },
            ),
        ]

        for action in self.actions:
            properties: dict[str, Any] = {}
            required: list[str] = []
            if action.get("method") == "setValueAndChange":
                value_spec = action.get("parameters", {}).get("value", {})
                properties["value"] = {
                    "type": value_spec.get("type", "string"),
                    "description": value_spec.get("description", "Value to set."),
                    "enum": value_spec.get("enum", []),
                }
                required.append("value")

            tools.append(
                ToolDefinition(
                    name=action["name"],
                    description=action.get("description", ""),
                    input_schema={
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                )
            )
        return tools
