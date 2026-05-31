from __future__ import annotations

import itertools
from typing import Any

import requests


class OpenBrainError(RuntimeError):
    pass


class OpenBrainClient:
    def __init__(self, base_url: str, access_token: str, timeout: int = 30) -> None:
        self.base_url = base_url
        self.access_token = access_token
        self.timeout = timeout
        self._ids = itertools.count(1)

    def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.access_token:
            raise OpenBrainError("OPENBRAIN_ACCESS_TOKEN is not configured")

        response = requests.post(
            self.base_url,
            headers={
                "authorization": f"Bearer {self.access_token}",
                "content-type": "application/json",
                "accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": next(self._ids),
                "method": method,
                "params": params,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()

        payload = self._decode_payload(response)
        if "error" in payload:
            message = payload["error"].get("message", "Unknown OpenBrain error")
            raise OpenBrainError(message)
        return payload["result"]

    @staticmethod
    def _decode_payload(response: requests.Response) -> dict[str, Any]:
        content_type = response.headers.get("content-type", "")
        text = response.text.strip()

        if "text/event-stream" not in content_type:
            return response.json()

        event_data: list[str] = []
        capturing = False
        for line in text.splitlines():
            if line.startswith("data: "):
                event_data.append(line[6:])
                capturing = True
                continue

            if capturing:
                if line.startswith("event: ") or line.startswith(":"):
                    continue
                event_data.append(line)

        if event_data:
            return requests.models.complexjson.loads("\\n".join(event_data))

        raise OpenBrainError("MCP server returned an empty event stream response")

    @staticmethod
    def _content_text(result: dict[str, Any]) -> str:
        parts = result.get("content", [])
        texts = [part.get("text", "") for part in parts if part.get("type") == "text"]
        return "\n\n".join(texts).strip()

    def thought_stats(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._call("tools/call", {"name": "thought_stats", "arguments": args})

    def list_thoughts(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._call("tools/call", {"name": "list_thoughts", "arguments": args})

    def search_thoughts(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._call("tools/call", {"name": "search_thoughts", "arguments": args})

    def capture_thought(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._call("tools/call", {"name": "capture_thought", "arguments": args})

    def thought_stats_text(self) -> str:
        return self._content_text(self.thought_stats({}))

    def list_thoughts_text(self, args: dict[str, Any]) -> str:
        return self._content_text(self.list_thoughts(args))

    def search_thoughts_text(self, args: dict[str, Any]) -> str:
        return self._content_text(self.search_thoughts(args))
