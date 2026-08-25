from __future__ import annotations

import json
import subprocess
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


# ---------------------------------------------------------------------------
# $ command handling (run_command parity with the Tk built-in command set)
# ---------------------------------------------------------------------------


def test_run_command_help_lists_commands(tmp_path):
    core = _core(tmp_path)
    result = core.run_command("$ HELP")
    assert result.handled is True
    assert result.output_title == "$ HELP"
    assert "NEW <title>" in result.output
    assert "SUMMARIZE <id>" in result.output


def test_run_command_new_creates_document(tmp_path):
    core = _core(tmp_path)
    result = core.run_command("$ NEW Hello World")
    assert result.handled is True
    assert result.reveal_doc_id is not None
    doc = core.doc_store.get_document(result.reveal_doc_id)
    assert doc["title"] == "Hello World"
    assert doc["body"] == ""


def test_run_command_list_outputs_index(tmp_path):
    core = _core(tmp_path)
    core.doc_store.add_document("Alpha", "body")
    result = core.run_command("$ LIST")
    assert result.handled is True
    assert "Alpha" in result.output


def test_run_command_view_reveals_or_reports_missing(tmp_path):
    core = _core(tmp_path)
    doc_id = core.doc_store.add_document("Alpha", "body")
    assert core.run_command(f"$ VIEW {doc_id}").reveal_doc_id == doc_id
    missing = core.run_command("$ VIEW 9999")
    assert missing.handled is True
    assert "not found" in missing.output


def test_run_command_edit_requires_input_then_appends(tmp_path):
    core = _core(tmp_path)
    doc_id = core.doc_store.add_document("Alpha", "start")
    first = core.run_command(f"$ EDIT {doc_id}")
    assert first.needs_input is True
    assert first.input_doc_id == doc_id
    second = core.run_command(f"$ EDIT {doc_id}", extra_text="more")
    assert second.reveal_doc_id == doc_id
    # Matches the Tk app's separator behavior: body + "\n" + extra.
    assert core.doc_store.get_document(doc_id)["body"] == "start\nmore"


def test_run_command_delete_removes_document(tmp_path):
    core = _core(tmp_path)
    doc_id = core.doc_store.add_document("Alpha", "body")
    result = core.run_command(f"$ DELETE {doc_id}")
    assert result.handled is True
    assert core.doc_store.get_document(doc_id) is None


def test_run_command_save_writes_file(tmp_path):
    core = _core(tmp_path)
    doc_id = core.doc_store.add_document("Alpha", "file body")
    out = tmp_path / "out.txt"
    result = core.run_command(f"$ SAVE {doc_id} {out}")
    assert result.handled is True
    assert out.read_text(encoding="utf-8") == "file body"


def test_run_command_load_imports_file(tmp_path):
    core = _core(tmp_path)
    src = tmp_path / "import.txt"
    src.write_text("imported content", encoding="utf-8")
    result = core.run_command(f"$ LOAD {src}")
    assert result.handled is True
    doc = core.doc_store.get_document(result.reveal_doc_id)
    assert doc["title"] == "import.txt"
    assert doc["body"] == "imported content"


def test_run_command_ask_delegates_to_processor(tmp_path):
    from unittest.mock import MagicMock

    core = _core(tmp_path)
    core.processor.ask_question = MagicMock(return_value="the reply")
    result = core.run_command("$ ASK What is this?")
    assert result.handled is True
    assert result.output == "the reply"
    core.processor.ask_question.assert_called_once_with("What is this?")


def test_run_command_summarize_delegates_to_processor(tmp_path):
    from unittest.mock import MagicMock

    core = _core(tmp_path)
    doc_id = core.doc_store.add_document("Alpha", "long body to summarize")
    core.processor.ask_question = MagicMock(return_value="summary")
    result = core.run_command(f"$ SUMMARIZE {doc_id}")
    assert result.handled is True
    assert result.output == "summary"
    assert "long body to summarize" in core.processor.ask_question.call_args.args[0]


def test_run_command_unmatched_returns_not_handled(tmp_path):
    core = _core(tmp_path)
    result = core.run_command("$ FROBNICATE")
    assert result.handled is False
    assert "no handler matched" in result.output


# ---------------------------------------------------------------------------
# Export / save-as-text
# ---------------------------------------------------------------------------


def test_core_document_to_plain_text_plain(tmp_path):
    core = _core(tmp_path)
    doc_id = core.doc_store.add_document("Alpha", "Hello world body")
    title, text = core.document_to_plain_text(doc_id)
    assert title == "Alpha"
    assert text == "Hello world body"


def test_core_document_to_plain_text_flattens_opml(tmp_path):
    core = _core(tmp_path)
    xml = (
        '<?xml version="1.0"?><opml version="2.0"><head><title>T</title></head>'
        "<body><outline text=\"Root\"><outline text=\"Child\"/></outline></body></opml>"
    )
    doc_id = core.doc_store.add_document("Tree", xml)
    _title, text = core.document_to_plain_text(doc_id)
    assert "Root" in text
    assert "Child" in text


def test_core_export_document_to_path(tmp_path):
    core = _core(tmp_path)
    doc_id = core.doc_store.add_document("Alpha", "export body")
    out = tmp_path / "export.txt"
    core.export_document_to_path(doc_id, out)
    assert out.read_text(encoding="utf-8") == "export body"


# ---------------------------------------------------------------------------
# Provider controls + RAG + settings persistence
# ---------------------------------------------------------------------------


def test_core_list_providers_and_selected(tmp_path):
    core = _core(tmp_path)
    providers = core.list_providers()
    assert isinstance(providers, list)
    keys = {k for k, _ in providers}
    assert "openai" in keys or "baseten" in keys or "local_llama" in keys
    assert core.get_selected_provider() in keys or core.get_selected_provider() == "openai"


def test_core_set_provider_persists_selection(tmp_path):
    core = _core(tmp_path)
    # Pick a provider that exists in the (temp) registry.
    providers = core.list_providers()
    assert providers
    key = providers[0][0]
    assert core.set_provider(key) is True
    assert core.settings.get("selected_provider") == key
    # Persisted to the core's explicit storage dir (not the CWD).
    app_state = tmp_path / "funkit" / "storage" / "app_state.json"
    import json as _json

    assert _json.loads(app_state.read_text(encoding="utf-8"))["selected_provider"] == key
    assert core.get_selected_provider() == key


def test_core_set_provider_unknown_returns_false(tmp_path):
    core = _core(tmp_path)
    assert core.set_provider("no_such_provider") is False


def test_core_rag_toggle_falls_back_to_attr(tmp_path):
    core = _core(tmp_path)
    assert core.is_rag_enabled() is False
    core.set_rag_enabled(True)
    assert core.is_rag_enabled() is True
    assert getattr(core.processor, "rag_enabled", None) is True


# ---------------------------------------------------------------------------
# Dream / memory controls
# ---------------------------------------------------------------------------


def test_core_archive_toggles_persist_to_settings(tmp_path):
    core = _core(tmp_path)
    core.set_archive_memory_enabled(False)
    assert core.archive_memory_enabled is False
    core.set_archive_publish_to_dream(True)
    assert core.archive_publish_to_dream is True
    core.set_archive_publish_to_openbrain(True)
    assert core.archive_publish_to_openbrain is True
    saved = json.loads((tmp_path / "funkit" / "funkit_settings.json").read_text(encoding="utf-8"))
    assert saved["archive_memory_enabled"] is False
    assert saved["archive_publish_to_dream"] is True
    assert saved["archive_publish_to_openbrain"] is True


def test_core_memory_get_set_roundtrip(tmp_path):
    core = _core(tmp_path)
    assert core.get_memory("global") == {}
    core.set_memory({"persona": "succinct", "rules": ["no filler"]}, "global")
    mem = core.get_memory("global")
    assert mem["persona"] == "succinct"
    assert "no filler" in mem["rules"]


def test_core_run_dream_pass_via_adapter(tmp_path):
    modules_dir = FUNKIT_DIR / "modules"
    if str(modules_dir) not in sys.path:
        sys.path.insert(0, str(modules_dir))
    repo_root = FUNKIT_DIR.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    _clear_adapter_stubs()

    core = _core(tmp_path)
    capsule = core.run_dream_pass()
    assert isinstance(capsule, str)
    assert "Dream Capsule" in capsule


def test_core_run_dream_pass_raises_when_disabled(tmp_path):
    core = _core(tmp_path)
    core.archive_memory_enabled = False
    try:
        core.run_dream_pass()
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError when archive memory disabled")


# ---------------------------------------------------------------------------
# Async ASK (worker thread, worker-owned SQLite connections)
# ---------------------------------------------------------------------------


def test_core_ask_question_async_returns_reply(tmp_path):
    import threading
    from unittest.mock import MagicMock

    core = _core(tmp_path)
    core.ai.query = MagicMock(return_value="async reply")
    core.ai.last_finish_reason = None
    done = threading.Event()
    outcome: dict = {}

    def on_done(reply, error):
        outcome["reply"] = reply
        outcome["error"] = error
        done.set()

    core.ask_question_async("hello", on_done)
    assert done.wait(timeout=10) is True
    assert outcome["reply"] == "async reply"
    assert outcome["error"] is None
    core.ai.query.assert_called()
    core.doc_store.add_document("After", "still works")
    assert len(core.doc_store.get_document_index()) == 1


# ---------------------------------------------------------------------------
# Launch/import regression: `python main.py` loads core as a top-level
# module, so the old `from .modules...` fallback raised "attempted relative
# import with no known parent package" whenever the first import failed.
# ---------------------------------------------------------------------------


def _run_python_script(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(FUNKIT_DIR),
    )


def test_core_imports_in_script_mode():
    """`python FunKit/main.py` loads core as a top-level module; the
    product root must be importable so the modules.* imports resolve."""
    result = _run_python_script(
        "import core\n"
        "assert core.FunKitCore is not None\n"
        "print('CORE_OK')\n"
    )
    assert result.returncode == 0, result.stderr
    assert "CORE_OK" in result.stdout


def test_core_import_failure_never_uses_relative_fallback():
    """Shadowing the top-level `modules` package forces the import to fail
    while core is still a top-level module; the failure must surface as the
    real error, not 'attempted relative import with no known parent
    package'."""
    result = _run_python_script(
        "import sys, types\n"
        "sys.modules['modules'] = types.ModuleType('modules')\n"
        "try:\n"
        "    import core\n"
        "except ImportError as exc:\n"
        "    message = str(exc)\n"
        "    assert 'no known parent package' not in message, message\n"
        "    print('CLEAR_IMPORT_ERROR')\n"
        "else:\n"
        "    print('CORE_IMPORTED')\n"
    )
    assert result.returncode == 0, result.stderr
    assert "CLEAR_IMPORT_ERROR" in result.stdout
    assert "no known parent package" not in result.stdout
