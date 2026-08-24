"""PiKit-side inbox for AI Communicator Dream Capture handoffs.

Packet protocol (version 1), written by ``ai_navigator/capture_store.py``:

    {
        "version": 1,
        "kind": "dream_capture",
        "title": "...",
        "body": "...",
        "source_capture_id": ...,
        "queued_at": "...",
    }

Claim atomicity: a packet is claimed by renaming ``dream-capture-*.json`` to
``<name>.processing``.  ``Path.replace`` is an atomic rename on POSIX, so if
two consumers (an embedded pane and a standalone process, for example) race
for the same packet, exactly one rename succeeds and the loser observes
``FileNotFoundError`` and skips it.  The claim glob only matches ``*.json``,
so ``.processing`` / ``.failed`` files are never re-imported.  A packet can
therefore never be imported twice.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def import_handoff_payload(payload: dict[str, Any], processor: Any, source: str = "packet") -> int:
    """Validate a handoff packet and import it through the processor.

    This is the shared, core-owned document-import entry point used by the Tk
    app today and by any future embedded consumer.  ``source`` names the
    origin (normally the inbox file name) for error messages.
    """
    if payload.get("kind") != "dream_capture" or payload.get("version") != 1:
        raise ValueError(f"Unsupported PiKit handoff: {source}")
    title = str(payload.get("title") or "Dream Capture").strip()
    body = str(payload.get("body") or "")
    if not body.strip():
        raise ValueError(f"Dream Capture has no document body: {source}")

    new_id = int(
        processor.import_shared_document(
            {"title": title, "body_encoding": "text", "body": body}
        )
    )
    return new_id


def _notify_view(app: Any, new_id: int) -> None:
    """Best-effort view notifications after an import (duck-typed).

    ``app`` may be a Tk window (``_refresh_index``/``_open_doc_id`` methods,
    ``status`` StringVar) or a core-owned adapter object with the same hooks.
    """
    if hasattr(app, "_refresh_index"):
        app._refresh_index()
    if hasattr(app, "_open_doc_id"):
        app._open_doc_id(new_id)
    status = getattr(app, "status", None)
    if status is not None:
        message = f"Imported Dream Capture as document {new_id}."
        if hasattr(status, "set"):
            status.set(message)
        elif callable(status):
            status(message)


def process_handoff_file(path: Path, processor: Any, app: Any = None) -> int:
    """Import one queued capture through PiKit and reveal the new document.

    ``app`` is optional; when omitted the import still happens and the caller
    is responsible for refreshing/revealing the new document.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    new_id = import_handoff_payload(payload, processor, source=path.name)
    if app is not None:
        _notify_view(app, new_id)
    return new_id


def process_inbox_once(inbox_dir: Path, processor: Any, app: Any = None) -> list[int]:
    """Claim and process every waiting handoff, preserving failures for review."""
    inbox_dir.mkdir(parents=True, exist_ok=True)
    imported: list[int] = []
    for queued_path in sorted(inbox_dir.glob("dream-capture-*.json")):
        processing_path = queued_path.with_suffix(".processing")
        try:
            queued_path.replace(processing_path)
            imported.append(process_handoff_file(processing_path, processor, app))
            processing_path.unlink(missing_ok=True)
        except FileNotFoundError:
            continue
        except Exception as exc:
            failed_path = processing_path.with_suffix(".failed")
            if processing_path.exists():
                processing_path.replace(failed_path)
            print(f"Dream Capture import failed ({queued_path.name}): {exc}")
    return imported


def start_inbox_polling(
    app: Any, processor: Any, inbox_dir: Path, interval_ms: int = 750
) -> None:
    """Process startup captures immediately, then watch for live handoffs.

    Tk-specific scheduler wrapper.  Core consumers should call
    ``consume_inbox_once()`` themselves and schedule it with their own event
    loop; this helper is retained for compatibility with existing callers.
    """
    def poll() -> None:
        process_inbox_once(inbox_dir, processor, app)
        app.after(interval_ms, poll)

    app.after_idle(poll)
