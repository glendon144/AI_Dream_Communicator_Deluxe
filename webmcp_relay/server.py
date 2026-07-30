from __future__ import annotations

import json
import sys
import traceback
from typing import Any

from logging_setup import configure_logging
from relay_core import WebMCPRelay


class MCPServer:
    def __init__(self) -> None:
        self.logger = configure_logging()
        self.relay = WebMCPRelay()

    def _result(self, request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _error(self, request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def _handle_initialize(self, request_id: Any) -> dict[str, Any]:
        return self._result(
            request_id,
            {
                "protocolVersion": "2024-11-05",
                "serverInfo": {
                    "name": "webmcp_relay",
                    "version": "0.2.0",
                },
                "capabilities": {"tools": {}},
            },
        )

    def _handle_tools_list(self, request_id: Any) -> dict[str, Any]:
        tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            }
            for tool in self.relay.tools()
        ]
        return self._result(request_id, {"tools": tools})

    def _handle_tools_call(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name", "")
        arguments = params.get("arguments", {})
        payload = self.relay.call_tool(name, arguments)
        return self._result(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(payload, indent=2, sort_keys=True),
                    }
                ],
                "structuredContent": payload,
                "isError": not payload.get("ok", False),
            },
        )

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if method == "initialize":
            return self._handle_initialize(request_id)
        if method == "notifications/initialized":
            return None
        if method == "tools/list":
            return self._handle_tools_list(request_id)
        if method == "tools/call":
            return self._handle_tools_call(request_id, params)
        return self._error(request_id, -32601, f"Method not found: {method}")

    def serve(self) -> int:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
                response = self.handle(request)
            except Exception as exc:  # pragma: no cover - top-level guard
                self.logger.error("Unhandled server error: %s\n%s", exc, traceback.format_exc())
                response = self._error(None, -32000, str(exc))

            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

        return 0


if __name__ == "__main__":
    raise SystemExit(MCPServer().serve())
