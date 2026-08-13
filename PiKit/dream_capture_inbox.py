"""PiKit-side inbox for AI Communicator Dream Capture handoffs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def process_handoff_file(path: Path, processor: Any, app: Any) -> int:
    """Import one queued capture through PiKit and reveal the new document."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("kind") != "dream_capture" or payload.get("version") != 1:
        raise ValueError(f"Unsupported PiKit handoff: {path.name}")
    title = str(payload.get("title") or "Dream Capture").strip()
    body = str(payload.get("body") or "")
    if not body.strip():
        raise ValueError(f"Dream Capture has no document body: {path.name}")

    new_id = int(
        processor.import_shared_document(
            {"title": title, "body_encoding": "text", "body": body}
        )
    )
    app._refresh_index()
    app._open_doc_id(new_id)
    if hasattr(app, "status"):
        app.status.set(f"Imported Dream Capture as document {new_id}.")
    return new_id


def process_inbox_once(inbox_dir: Path, processor: Any, app: Any) -> list[int]:
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
    """Process startup captures immediately, then watch for live handoffs."""
    def poll() -> None:
        process_inbox_once(inbox_dir, processor, app)
        app.after(interval_ms, poll)

    app.after_idle(poll)
