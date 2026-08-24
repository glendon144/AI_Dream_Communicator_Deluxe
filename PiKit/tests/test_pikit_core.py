from __future__ import annotations

import json
import sys
from pathlib import Path

PIKIT_DIR = Path(__file__).resolve().parent.parent
if str(PIKIT_DIR) not in sys.path:
    sys.path.insert(0, str(PIKIT_DIR))

from core import PiKitCore


class FakeAI:
    """Minimal stand-in for modules.ai_interface.AIInterface."""

    def __init__(self, *args, **kwargs):
        pass

    def get_config(self) -> dict:
        return {"provider": "fake"}


def _core(tmp_path) -> PiKitCore:
    return PiKitCore(root=tmp_path / "pikit", ai_interface=FakeAI())


def _queue_packet(core: PiKitCore, name: str, title: str, body: str) -> Path:
    core.inbox_dir.mkdir(parents=True, exist_ok=True)
    path = core.inbox_dir / name
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "kind": "dream_capture",
                "title": title,
                "body": body,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_core_creates_storage_and_business_objects(tmp_path):
    core = _core(tmp_path)
    assert core.root == tmp_path / "pikit"
    assert core.storage_dir.is_dir()
    assert core.db_path == core.storage_dir / "documents.db"
    assert core.dreams_db_path == core.storage_dir / "dreams.db"
    assert core.inbox_dir == core.storage_dir / "handoffs"
    assert core.doc_store is not None
    assert core.processor is not None
    assert core.dream_processor is not None
    assert core.dream_enabled is False
    # Dream processor started but not authorized until enabled
    assert core.dream_processor.is_authorized() is False
    # Dream handler wired to the command processor (no GUI involvement)
    assert core.processor.dream_handler is not None


def test_core_dream_toggle_and_pass(tmp_path):
    core = _core(tmp_path)
    core.set_dream_enabled(True)
    assert core.dream_enabled is True
    assert core.dream_processor.is_authorized() is True
    capsule = core.run_dream_pass()
    assert isinstance(capsule, str)
    assert "Dream Capsule" in capsule
    core.set_dream_enabled(False)
    assert core.dream_processor.is_authorized() is False


def test_core_import_handoff_payload_creates_document(tmp_path):
    core = _core(tmp_path)
    new_id = core.import_handoff_payload(
        {
            "version": 1,
            "kind": "dream_capture",
            "title": "Dream Capture — Example",
            "body": "Selected source material",
        }
    )
    doc = core.doc_store.get_document(new_id)
    assert doc["title"] == "Dream Capture — Example"
    assert "Selected source material" in doc["body"]


def test_core_import_handoff_payload_rejects_unknown_packet(tmp_path):
    core = _core(tmp_path)
    for bad in (
        {"version": 1, "kind": "other", "body": "x"},
        {"version": 99, "kind": "dream_capture", "body": "x"},
        {"version": 1, "kind": "dream_capture", "body": "   "},
    ):
        try:
            core.import_handoff_payload(bad)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad!r}")


def test_core_consume_inbox_once_imports_and_notifies(tmp_path):
    core = _core(tmp_path)
    _queue_packet(core, "dream-capture-1-1.json", "Dream Capture — One", "Body One")
    _queue_packet(core, "dream-capture-2-2.json", "Dream Capture — Two", "Body Two")

    imported: list[int] = []
    statuses: list[str] = []
    core.status_callback = statuses.append

    ids = core.consume_inbox_once(on_imported=imported.append)
    assert len(ids) == 2
    assert imported == ids  # the view was told about every import
    assert "Imported Dream Capture as document" in " ".join(statuses)
    # Claimed files are gone; the second pass is a no-op (no double import).
    assert not list(core.inbox_dir.glob("dream-capture-*.json"))
    assert core.consume_inbox_once(on_imported=imported.append) == []
    assert len(imported) == 2
    assert len(core.doc_store.get_document_index()) == 2


def test_core_consume_inbox_once_ignores_claim_and_failed_files(tmp_path):
    core = _core(tmp_path)
    core.inbox_dir.mkdir(parents=True, exist_ok=True)
    (core.inbox_dir / "dream-capture-9-1.processing").write_text("{}", encoding="utf-8")
    (core.inbox_dir / "dream-capture-9-1.failed").write_text("{}", encoding="utf-8")
    assert core.consume_inbox_once() == []


def test_core_consume_inbox_once_moves_failed_imports_to_failed(tmp_path):
    core = _core(tmp_path)
    _queue_packet(core, "dream-capture-1-1.json", "Bad", "x")
    # Corrupt the packet so import raises after claiming.
    (core.inbox_dir / "dream-capture-1-1.json").write_text(
        json.dumps({"version": 99, "kind": "dream_capture", "body": "x"}),
        encoding="utf-8",
    )
    assert core.consume_inbox_once() == []
    assert (core.inbox_dir / "dream-capture-1-1.failed").exists()


def test_core_dream_event_attribution_uses_current_doc_id(tmp_path):
    core = _core(tmp_path)
    core.set_current_doc_id(7)
    core.record_dream_event("ask_question", "Why?")
    # DreamProcessor buffers events in an in-memory queue; flush it to the DB.
    core.dream_processor._flush_event_queue_to_db()
    rows = core.dream_processor.db.fetch_unprocessed_events(limit=10)
    assert any(row["source_doc_id"] == 7 for row in rows)


def test_core_processor_dream_events_reach_dream_db(tmp_path):
    core = _core(tmp_path)
    # Emit through the command processor exactly as the Tk GUI's wiring did.
    core.processor._emit_dream_event(
        "ask_request", "prompt", current_doc_id=3
    )
    core.dream_processor._flush_event_queue_to_db()
    rows = core.dream_processor.db.fetch_unprocessed_events(limit=10)
    assert any(row["event_type"] == "ask_request" for row in rows)


def test_core_shutdown_stops_dream_processor(tmp_path):
    core = _core(tmp_path)
    core.shutdown()
    assert core.dream_processor._running is False


# ---------------------------------------------------------------------------
# Tk GUI delegation (fake-self binding, no display required)
# ---------------------------------------------------------------------------


def _fake_gui(core):
    from unittest.mock import MagicMock

    fake = MagicMock()
    fake.core = core
    fake.dream_processor = core.dream_processor
    fake.dream_enabled = core.dream_enabled
    fake.status = MagicMock()
    fake._set_dream_button_label = MagicMock()
    return fake


def test_gui_toggle_dream_delegates_to_core(tmp_path):
    from modules.gui_tkinter import DemoKitGUI

    core = _core(tmp_path)
    fake = _fake_gui(core)
    DemoKitGUI._toggle_dream.__get__(fake, type(fake))()
    assert core.dream_enabled is True
    assert core.dream_processor.is_authorized() is True
    assert fake.status.set.called


def test_gui_run_dream_now_uses_core_pass(tmp_path):
    from unittest.mock import patch

    from modules.gui_tkinter import DemoKitGUI

    core = _core(tmp_path)
    fake = _fake_gui(core)
    with patch("modules.gui_tkinter.messagebox.showinfo") as showinfo:
        DemoKitGUI._run_dream_now.__get__(fake, type(fake))()
    args = showinfo.call_args.args
    assert args[0] == "Dream Capsule"
    assert "Dream Capsule" in str(args[1])


def test_gui_on_close_shuts_down_core(tmp_path):
    from unittest.mock import MagicMock

    from modules.gui_tkinter import DemoKitGUI

    core = _core(tmp_path)
    fake = _fake_gui(core)
    fake._transfer_stop = MagicMock()
    fake._transfer_server = None
    fake.destroy = MagicMock()
    DemoKitGUI._on_close.__get__(fake, type(fake))()
    assert core.dream_processor._running is False
    fake.destroy.assert_called_once()
