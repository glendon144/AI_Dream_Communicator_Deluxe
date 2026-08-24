from __future__ import annotations

import json
import sys
from pathlib import Path

FUNKIT_DIR = Path(__file__).resolve().parent.parent
if str(FUNKIT_DIR) not in sys.path:
    sys.path.insert(0, str(FUNKIT_DIR))

from core import FunKitCore
from modules.command_processor import CommandProcessor
from modules.document_store import DocumentStore


class FakeAI:
    def __init__(self, *args, **kwargs):
        pass


def _core(tmp_path) -> FunKitCore:
    root = tmp_path / "funkit"
    store = DocumentStore(str(root / "storage" / "documents.db"))
    processor = CommandProcessor(store, FakeAI())
    return FunKitCore(root=root, store=store, processor=processor, ai=FakeAI())


def _clear_adapter_stubs():
    """Drop sys.modules stubs left behind by test_memory_publish_adapter.py.

    pytest imports every test module during collection, and that module stubs
    sys.modules["dream"]/["dream_client"]/["openbrain_client"] at import time.
    Without cleanup, the core's adapter construction would resolve the stub
    ``dream`` module (whose DreamProcessor cannot be constructed) and report
    the adapter as unavailable.
    """
    for name in ("dream", "dream_client", "openbrain_client", "memory_publish_adapter"):
        sys.modules.pop(name, None)


def test_core_creates_storage_and_business_objects(tmp_path):
    core = _core(tmp_path)
    assert core.root == tmp_path / "funkit"
    assert core.storage_dir.is_dir()
    assert core.db_path == core.storage_dir / "documents.db"
    assert core.settings_file == core.root / "funkit_settings.json"
    assert core.settings == {}
    assert core.doc_store is not None
    assert core.processor is not None


def test_core_settings_load_and_save(tmp_path):
    settings_file = tmp_path / "funkit" / "funkit_settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(
        json.dumps({"opml_expand_depth": 5, "archive_memory_enabled": False}),
        encoding="utf-8",
    )
    core = _core(tmp_path)
    assert core.settings["opml_expand_depth"] == 5
    assert core.archive_memory_enabled is False
    core.settings["opml_expand_depth"] = 3
    core.save_settings()
    assert json.loads(settings_file.read_text(encoding="utf-8"))["opml_expand_depth"] == 3


def test_core_archive_after_export_returns_none_when_disabled(tmp_path):
    core = _core(tmp_path)
    core.archive_memory_enabled = False
    assert core.archive_after_export(title="T", content="x") is None


def test_core_archive_after_export_records_local_dream(tmp_path):
    # The adapter construction mirrors the Tk GUI: it imports
    # memory_publish_adapter (FunKit/modules) and falls back to
    # PiKit.modules.dream for the DreamProcessor.
    modules_dir = FUNKIT_DIR / "modules"
    if str(modules_dir) not in sys.path:
        sys.path.insert(0, str(modules_dir))
    repo_root = FUNKIT_DIR.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    _clear_adapter_stubs()

    core = _core(tmp_path)
    statuses: list[str] = []
    core.status_callback = statuses.append
    result = core.archive_after_export(
        title="Sample",
        content="Some archived content worth remembering.",
        doc_id=1,
        export_path=str(tmp_path / "out.txt"),
    )
    assert result is not None
    assert result["capsule"]["capsule_type"] == "dream"
    assert any("local dream memory" in s for s in statuses)
    # The local dream DB recorded the export event.
    assert core._memory_publish_adapter is not None


def test_core_archive_after_export_reports_failure(tmp_path):
    modules_dir = FUNKIT_DIR / "modules"
    if str(modules_dir) not in sys.path:
        sys.path.insert(0, str(modules_dir))
    repo_root = FUNKIT_DIR.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    _clear_adapter_stubs()

    core = _core(tmp_path)
    statuses: list[str] = []
    core.status_callback = statuses.append
    # Break the adapter so publish_latest raises.
    adapter = core.get_memory_publish_adapter()
    assert adapter is not None

    def _boom(*args, **kwargs):
        raise RuntimeError("publish exploded")

    adapter.publish_latest = _boom
    result = core.archive_after_export(title="T", content="body")
    assert result is None
    assert any("Archive memory publish failed" in s for s in statuses)


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
        {"version": 1, "kind": "dream_capture", "body": "  "},
    ):
        try:
            core.import_handoff_payload(bad)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad!r}")


# ---------------------------------------------------------------------------
# Tk GUI delegation (fake-self binding, no display required)
# ---------------------------------------------------------------------------


def _import_demo_gui():
    """Import DemoKitGUI with openai stubbed (gui_tkinter requires it via
    modules.image_generator); mirrors test_funkit_return_to_navigator."""
    import sys
    from unittest.mock import MagicMock

    if "openai" not in sys.modules or not hasattr(sys.modules["openai"], "OpenAI"):
        fake_openai = MagicMock()
        fake_openai.OpenAI = MagicMock
        sys.modules["openai"] = fake_openai
    from modules.gui_tkinter import DemoKitGUI

    return DemoKitGUI


def test_gui_settings_delegate_to_core(tmp_path):
    import pytest
    from unittest.mock import MagicMock

    try:
        DemoKitGUI = _import_demo_gui()
    except Exception:
        pytest.skip("FunKit GUI import unavailable in this env")
    core = _core(tmp_path)
    fake = MagicMock()
    fake.core = core
    assert DemoKitGUI._load_settings.__get__(fake, type(fake))() is core.settings
    core.save_settings = MagicMock()
    DemoKitGUI._save_settings.__get__(fake, type(fake))()
    core.save_settings.assert_called_once()


def test_gui_memory_adapter_delegates_to_core(tmp_path):
    import pytest
    from unittest.mock import MagicMock

    try:
        DemoKitGUI = _import_demo_gui()
    except Exception:
        pytest.skip("FunKit GUI import unavailable in this env")
    core = _core(tmp_path)
    core.get_memory_publish_adapter = MagicMock(return_value="ADAPTER")
    fake = MagicMock()
    fake.core = core
    assert (
        DemoKitGUI._get_memory_publish_adapter.__get__(fake, type(fake))()
        == "ADAPTER"
    )


def test_gui_archive_memory_delegates_to_core(tmp_path):
    import pytest
    from unittest.mock import MagicMock

    try:
        DemoKitGUI = _import_demo_gui()
    except Exception:
        pytest.skip("FunKit GUI import unavailable in this env")
    core = _core(tmp_path)
    core.archive_after_export = MagicMock(return_value=None)
    fake = MagicMock()
    fake.core = core
    fake.current_doc_id = 5
    fake.archive_publish_to_dream = True
    fake.archive_publish_to_openbrain = False
    fake.archive_memory_ttl_seconds = None

    DemoKitGUI._archive_memory_after_export.__get__(fake, type(fake))(
        title="T", body="hello", export_path="/tmp/out.txt"
    )
    core.archive_after_export.assert_called_once()
    kwargs = core.archive_after_export.call_args.kwargs
    assert kwargs["title"] == "T"
    assert kwargs["content"] == "hello"
    assert kwargs["doc_id"] == 5
    assert kwargs["export_path"] == "/tmp/out.txt"
    assert kwargs["publish_to_dream"] is True
    assert kwargs["publish_to_openbrain"] is False
    assert kwargs["ttl_seconds"] is None
