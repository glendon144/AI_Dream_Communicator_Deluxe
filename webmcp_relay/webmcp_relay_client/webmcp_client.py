from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any

import requests


class WebMCPClientError(RuntimeError):
    pass


@dataclass
class WebMCPClient:
    mode: str
    manifest_url: str
    relay_server: str

    @classmethod
    def from_env(cls) -> "WebMCPClient":
        return cls(
            mode=os.getenv("WEBMCP_CLIENT_MODE", "direct").strip().lower(),
            manifest_url=os.getenv(
                "WEBMCP_MANIFEST_URL",
                "http://jazz.clonesvr.com/.well-known/mcp.json",
            ),
            relay_server=os.getenv(
                "WEBMCP_RELAY_SERVER",
                "/home/gross/src/webmcp_relay/server.py",
            ),
        )

    def status(self) -> dict[str, Any]:
        if self.mode == "stdio":
            return self._stdio_tool_call("webmcp_manifest_status", {})
        manifest = self._fetch_manifest()
        return {
            "mode": self.mode,
            "manifest_url": self.manifest_url,
            "name": manifest.get("name"),
            "title": manifest.get("title"),
            "description": manifest.get("description"),
            "homepage": manifest.get("homepage"),
            "mcp_version": manifest.get("mcp_version"),
            "action_count": len(manifest.get("actions", [])),
            "safety": manifest.get("safety", {}),
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }

    def list_actions(self) -> list[dict[str, Any]]:
        if self.mode == "stdio":
            result = self._stdio_tool_call("webmcp_list_actions", {})
            actions = result.get("actions")
            if isinstance(actions, list):
                return actions
            if isinstance(result, list):
                return result
            return []

        manifest = self._fetch_manifest()
        actions = []
        for action in manifest.get("actions", []):
            actions.append({
                "name": action.get("name"),
                "description": action.get("description", ""),
                "method": action.get("method"),
                "selector": action.get("selector"),
                "parameters": action.get("parameters", {}),
                "risk": self._risk_for_action(action),
            })
        return actions

    def get_action(self, name: str) -> dict[str, Any] | None:
        if self.mode == "stdio":
            result = self._stdio_tool_call("webmcp_get_action", {"name": name})
            return result.get("action", result)

        for action in self._fetch_manifest().get("actions", []):
            if action.get("name") == name:
                return action
        return None

    def call_action(self, name: str, parameters: dict[str, Any]) -> dict[str, Any]:
        if self.mode == "stdio":
            return self._stdio_tool_call("webmcp_call_action", {
                "name": name,
                "parameters": parameters,
            })

        manifest = self._fetch_manifest()
        homepage = manifest.get("homepage")
        safety = manifest.get("safety", {})
        action = None
        for candidate in manifest.get("actions", []):
            if candidate.get("name") == name:
                action = candidate
                break

        if action is None:
            return {"ok": False, "error": f"Unknown action: {name}"}

        method = action.get("method")
        if method not in {"click", "setValueAndChange"}:
            return {
                "ok": False,
                "error": f"Unsupported or denied WebMCP method: {method}",
                "action": name,
            }

        if method == "setValueAndChange":
            value = parameters.get("value")
            enum_values = (
                action.get("parameters", {})
                .get("value", {})
                .get("enum", [])
            )
            if value not in enum_values:
                return {
                    "ok": False,
                    "error": "Invalid value for setValueAndChange action.",
                    "action": name,
                    "provided_value": value,
                    "allowed_values": enum_values,
                }

        return {
            "ok": True,
            "mode": "direct",
            "action": action.get("name"),
            "description": action.get("description", ""),
            "method": method,
            "selector": action.get("selector"),
            "homepage": homepage,
            "parameters": parameters,
            "risk": self._risk_for_action(action),
            "safety": {
                "execution": safety.get("execution", "none"),
                "clipboard": safety.get("clipboard", "user_initiated_only"),
                "navigation": safety.get("navigation", "user_visible_only"),
                "notes": safety.get("notes", ""),
            },
            "instruction": self._instruction_for_action(action, parameters, homepage),
        }

    def _fetch_manifest(self) -> dict[str, Any]:
        try:
            response = requests.get(self.manifest_url, timeout=20)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise WebMCPClientError(f"Could not fetch manifest: {exc}") from exc

        try:
            manifest = response.json()
        except ValueError as exc:
            raise WebMCPClientError("Manifest did not return valid JSON.") from exc

        if not isinstance(manifest, dict):
            raise WebMCPClientError("Manifest JSON is not an object.")
        if "actions" not in manifest or not isinstance(manifest["actions"], list):
            raise WebMCPClientError("Manifest does not contain an actions[] list.")
        return manifest

    def _stdio_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not os.path.exists(self.relay_server):
            raise WebMCPClientError(f"Relay server not found: {self.relay_server}")

        messages = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "webmcp_relay_client",
                        "version": "0.1.0",
                    },
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments,
                },
            },
        ]

        input_text = "\n".join(json.dumps(m) for m in messages) + "\n"

        try:
            proc = subprocess.run(
                [sys.executable, self.relay_server],
                input=input_text,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15,
                cwd=os.path.dirname(self.relay_server) or None,
            )
        except subprocess.TimeoutExpired as exc:
            raise WebMCPClientError("Relay server timed out.") from exc

        if proc.returncode != 0:
            raise WebMCPClientError(
                f"Relay server exited with {proc.returncode}: {proc.stderr[-1000:]}"
            )

        responses = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                responses.append(json.loads(line))
            except ValueError:
                continue

        if not responses:
            raise WebMCPClientError(
                "Relay produced no parseable JSON-RPC response. "
                "It may use Content-Length MCP framing instead of newline JSON."
            )

        final = next((r for r in responses if r.get("id") == 2), responses[-1])

        if "error" in final:
            raise WebMCPClientError(json.dumps(final["error"], indent=2))

        result = final.get("result", {})
        content = result.get("content") if isinstance(result, dict) else None
        if isinstance(content, list) and content:
            text = content[0].get("text") if isinstance(content[0], dict) else None
            if text:
                try:
                    return json.loads(text)
                except ValueError:
                    return {"ok": True, "text": text, "raw_result": result}

        return result if isinstance(result, dict) else {"ok": True, "result": result}

    def _risk_for_action(self, action: dict[str, Any]) -> str:
        name = str(action.get("name", ""))
        method = action.get("method")
        if "copy" in name:
            return "clipboard_command_requires_user_initiation"
        if method == "setValueAndChange":
            return "user_visible_navigation_parameterized"
        if method == "click":
            return "user_visible_click_instruction"
        return "unknown_method_denied"

    def _instruction_for_action(
        self,
        action: dict[str, Any],
        parameters: dict[str, Any],
        homepage: str | None,
    ) -> str:
        method = action.get("method")
        selector = action.get("selector")
        name = action.get("name")

        if method == "click":
            if "copy" in str(name):
                return (
                    f"Open {homepage}, locate selector {selector}, and only copy the command "
                    "after an explicit user gesture. Do not execute the copied command."
                )
            return (
                f"Open {homepage}, locate selector {selector}, and perform a user-visible click."
            )

        if method == "setValueAndChange":
            value = parameters.get("value")
            return (
                f"Open {homepage}, locate selector {selector}, set its value to {value!r}, "
                "and trigger the visible change event."
            )

        return "Denied: unknown or unsupported method."
