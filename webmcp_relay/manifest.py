from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from logging_setup import configure_logging


DEFAULT_MANIFEST_URL = "http://jazz.clonesvr.com/.well-known/mcp.json"


@dataclass
class ManifestSnapshot:
    manifest_url: str
    fetched_at: str
    document: dict[str, Any]


class ManifestLoader:
    def __init__(self, manifest_url: str | None = None) -> None:
        self.logger = configure_logging()
        self.manifest_url = manifest_url or os.environ.get("WEBMCP_MANIFEST_URL", DEFAULT_MANIFEST_URL)

    def fetch(self) -> ManifestSnapshot:
        self.logger.info("Fetching manifest from %s", self.manifest_url)
        with urllib.request.urlopen(self.manifest_url, timeout=20) as response:
            payload = response.read().decode("utf-8")

        document = json.loads(payload)
        snapshot = ManifestSnapshot(
            manifest_url=self.manifest_url,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            document=document,
        )
        return snapshot
