from __future__ import annotations

from typing import Any

import requests
from requests import RequestException


class DreamError(RuntimeError):
    pass


class DreamClient:
    def __init__(self, base_url: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = requests.get(
                f"{self.base_url}{path}",
                params=params or {},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except RequestException as exc:
            raise DreamError(f"{self.base_url}{path}: {exc}") from exc

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = requests.post(
                f"{self.base_url}{path}",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except RequestException as exc:
            raise DreamError(f"{self.base_url}{path}: {exc}") from exc

    def server_status(self) -> dict[str, Any]:
        return self._get("/")

    def list_recent_capsules(self, limit: int = 10) -> dict[str, Any]:
        return self._get("/list_recent_capsules", {"limit": limit})

    def search_capsules(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._post("/search_capsules", args)

    def recover_context(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._post("/recover_context", args)

    def store_capsule(
        self,
        *,
        content: str,
        source_agent: str = "flask-client",
        capsule_type: str = "distill",
        source_system: str = "flask-ui",
        confidence: float = 0.7,
        scope: str = "private",
        trust_level: str = "local",
        retention: str = "normal",
    ) -> dict[str, Any]:
        summary = (
            content.strip().splitlines()[0][:160]
            if content.strip()
            else "Untitled capsule"
        )
        key_facts = [line.strip() for line in content.splitlines() if line.strip()]
        if not key_facts and content.strip():
            key_facts = [content.strip()]

        payload = {
            "capsule_type": capsule_type,
            "summary": summary,
            "body": {
                "source_system": source_system,
                "source_references": [],
                "key_facts": key_facts,
                "themes": [],
                "entities": [],
                "relationships": [],
                "open_questions": [],
                "contradictions": [],
                "recovery_hints": [],
                "emotional_tone": None,
                "stylistic_profile": None,
                "domain_metadata": {"raw_text": content},
            },
            "confidence": confidence,
            "retention": retention,
            "scope": scope,
            "trust_level": trust_level,
            "review_status": "unreviewed",
            "source_agent": source_agent,
            "source_type": "flask-form",
            "source_ref": None,
            "lineage": {},
            "metadata": {},
        }
        return self.store_capsule_payload(payload)

    def store_capsule_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Post a fully structured capsule payload directly to the Dream server.

        This keeps `store_capsule()` as the text-first convenience method while
        allowing callers to pass through richer capsule schemas, including
        optional fields such as `ttl_seconds`.
        """
        return self._post("/store_capsule", payload)

    @staticmethod
    def _pretty(obj: dict[str, Any]) -> str:
        import json

        return json.dumps(obj, indent=2, ensure_ascii=False)

    def server_status_text(self) -> str:
        return self._pretty(self.server_status())

    def list_recent_capsules_text(self, limit: int = 10) -> str:
        return self._pretty(self.list_recent_capsules(limit))

    def search_capsules_text(self, args: dict[str, Any]) -> str:
        return self._pretty(self.search_capsules(args))

    def recover_context_text(self, args: dict[str, Any]) -> str:
        return self._pretty(self.recover_context(args))
