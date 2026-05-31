"""
Small FunKit integration example for local archival flow.

This keeps DreamProcessor local and provisional, then optionally publishes the
derived capsule outward through the adapter layer.
"""

from __future__ import annotations

from memory_publish_adapter import (
    DreamServerPublisher,
    FunKitDreamAdapter,
    OpenBrainPublisher,
)

try:
    from dream import DreamProcessor
except ImportError:
    from PiKit.modules.dream import DreamProcessor

from dream_client import DreamClient
from openbrain_client import OpenBrainClient


def build_funkit_adapter(
    *,
    dreams_db_path: str,
    dream_base_url: str | None = None,
    openbrain_base_url: str | None = None,
    openbrain_access_token: str | None = None,
) -> FunKitDreamAdapter:
    processor = DreamProcessor(dreams_db_path=dreams_db_path)

    dream_publisher = None
    if dream_base_url:
        dream_publisher = DreamServerPublisher(DreamClient(base_url=dream_base_url))

    openbrain_publisher = None
    if openbrain_base_url and openbrain_access_token:
        openbrain_publisher = OpenBrainPublisher(
            OpenBrainClient(
                base_url=openbrain_base_url,
                access_token=openbrain_access_token,
            )
        )

    return FunKitDreamAdapter(
        processor=processor,
        dream_publisher=dream_publisher,
        openbrain_publisher=openbrain_publisher,
    )


def archive_example() -> dict[str, object]:
    """
    Example flow for a FunKit Archive action.
    """
    adapter = build_funkit_adapter(
        dreams_db_path="/tmp/funkit-dreams.sqlite3",
        dream_base_url="http://127.0.0.1:8000",
    )
    adapter.note_archive_event(
        "Archived OPML cluster about local memory publication and Dream capsule export.",
        metadata={"ui_action": "archive"},
    )
    return adapter.publish_latest(
        title="FunKit archive action",
        publish_to_dream=True,
        publish_to_openbrain=False,
        ttl_seconds=3600,
    )
