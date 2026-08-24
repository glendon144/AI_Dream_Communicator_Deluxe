from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
MODULE_DIR = Path(__file__).resolve().parent.parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import qt_panes
from FunKit.core import FunKitCore
from PiKit.core import PiKitCore


class FakeAI:
    def __init__(self, *args, **kwargs):
        self.last_finish_reason = None

    def get_config(self):
        return {"provider": "fake"}

    def query(self, prompt, **kwargs):
        return "canned AI reply"


def _pikit_core(tmp_path) -> PiKitCore:
    return PiKitCore(root=tmp_path / "pikit", ai_interface=FakeAI())


def _funkit_core(tmp_path) -> FunKitCore:
    from FunKit.modules.command_processor import CommandProcessor
    from FunKit.modules.document_store import DocumentStore

    root = tmp_path / "funkit"
    store = DocumentStore(str(root / "storage" / "documents.db"))
    processor = CommandProcessor(store, FakeAI())
    return FunKitCore(root=root, store=store, processor=processor, ai=FakeAI())


# ---------------------------------------------------------------------------
# Coexistence of the two product packages
# ---------------------------------------------------------------------------


def test_pikit_and_funkit_cores_coexist_in_one_interpreter(tmp_path):
    import FunKit.modules.command_processor as fcp
    import PiKit.modules.command_processor as pcp

    # The module-collision fix: both products load as distinct package modules.
    assert pcp is not fcp
    assert pcp.__name__ == "PiKit.modules.command_processor"
    assert fcp.__name__ == "FunKit.modules.command_processor"

    pikit_core = _pikit_core(tmp_path)
    funkit_core = _funkit_core(tmp_path)
    assert pikit_core.processor is not None
    assert funkit_core.processor is not None
    # Each product constructs its own business classes (no cross-contamination).
    assert type(pikit_core.doc_store) is not type(funkit_core.doc_store)


# ---------------------------------------------------------------------------
# PiKit pane
# ---------------------------------------------------------------------------


def test_pikit_pane_lists_and_displays_documents(qtbot, tmp_path):
    core = _pikit_core(tmp_path)
    core.doc_store.add_document("Alpha", "Body of alpha.")
    core.doc_store.add_document("Beta", "Body of beta.")
    pane = qt_panes.PiKitPane(tmp_path / "pikit", core=core)
    qtbot.addWidget(pane)

    assert pane.doc_list.count() == 2
    # Index is ordered newest-first (id DESC): Beta (id 2) is row 0.
    pane.doc_list.setCurrentRow(0)
    assert "Body of beta." in pane.viewer.toPlainText()
    assert "Viewing: Beta" in pane.status_label.text()

    pane.doc_list.setCurrentRow(1)
    assert "Body of alpha." in pane.viewer.toPlainText()
    assert "Viewing: Alpha" in pane.status_label.text()


def test_pikit_pane_command_delegates_ask(qtbot, tmp_path):
    from unittest.mock import MagicMock

    core = _pikit_core(tmp_path)
    # The ASK runs on a worker thread with a worker-owned store + processor;
    # delegation is verified at the AI boundary (the core's shared AI client).
    core.ai.query = MagicMock(return_value="AI reply text")
    pane = qt_panes.PiKitPane(tmp_path / "pikit", core=core)
    qtbot.addWidget(pane)

    pane.command_line.setText("What is the meaning?")
    pane.command_line.returnPressed.emit()

    qtbot.waitUntil(
        lambda: "AI reply text" in pane.viewer.toPlainText(), timeout=5000
    )
    core.ai.query.assert_called()
    assert "ASK complete." in pane.status_label.text()


def test_pikit_pane_dream_toggle_and_now(qtbot, tmp_path):
    core = _pikit_core(tmp_path)
    pane = qt_panes.PiKitPane(tmp_path / "pikit", core=core)
    qtbot.addWidget(pane)

    assert pane.dream_button.text() == "Dream: OFF"
    pane.dream_button.click()
    assert core.dream_enabled is True
    assert pane.dream_button.text() == "Dream: ON"
    assert "Dream mode authorized" in pane.status_label.text()

    pane.dream_now_button.click()
    assert "Dream Capsule" in pane.viewer.toPlainText()
    assert "Dream pass completed." in pane.status_label.text()

    pane.dream_button.click()
    assert core.dream_enabled is False
    assert pane.dream_button.text() == "Dream: OFF"


def test_pikit_pane_embedded_handoff_through_shared_inbox(qtbot, tmp_path):
    core = _pikit_core(tmp_path)
    pane = qt_panes.PiKitPane(tmp_path / "pikit", core=core)
    qtbot.addWidget(pane)

    pane.accept_handoff(packet="packet body text", title="Cap", source_capture_id=9)
    # The packet is queued through the shared file inbox (atomic claim).
    queued = list(core.inbox_dir.glob("dream-capture-*.json"))
    assert len(queued) == 1

    qtbot.waitUntil(
        lambda: len(core.doc_store.get_document_index()) >= 1, timeout=5000
    )
    docs = core.doc_store.get_document_index()
    assert docs[0]["title"] == "Dream Capture — Cap"
    doc = core.doc_store.get_document(docs[0]["id"])
    assert doc["body"] == "packet body text"
    # Claimed file consumed; the viewer revealed the imported document.
    assert not list(core.inbox_dir.glob("dream-capture-*.json"))
    assert pane.viewer.toPlainText() == "packet body text"


# ---------------------------------------------------------------------------
# FunKit pane
# ---------------------------------------------------------------------------


def test_funkit_pane_lists_and_displays_documents(qtbot, tmp_path):
    core = _funkit_core(tmp_path)
    core.doc_store.add_document("Gamma", "Body of gamma.")
    pane = qt_panes.FunKitPane(tmp_path / "funkit", core=core)
    qtbot.addWidget(pane)

    assert pane.doc_list.count() == 1
    pane.doc_list.setCurrentRow(0)
    assert "Body of gamma." in pane.viewer.toPlainText()
    assert "Viewing: Gamma" in pane.status_label.text()


def test_funkit_pane_command_delegates_ask(qtbot, tmp_path):
    from unittest.mock import MagicMock

    core = _funkit_core(tmp_path)
    core.ai.query = MagicMock(return_value="Funkit reply")
    core.ai.last_finish_reason = None
    pane = qt_panes.FunKitPane(tmp_path / "funkit", core=core)
    qtbot.addWidget(pane)

    pane.command_line.setText("Summarize this.")
    pane.command_line.returnPressed.emit()

    qtbot.waitUntil(
        lambda: "Funkit reply" in pane.viewer.toPlainText(), timeout=5000
    )
    core.ai.query.assert_called()
    assert "ASK complete." in pane.status_label.text()


def test_funkit_pane_handoff_imports_in_process(qtbot, tmp_path):
    core = _funkit_core(tmp_path)
    pane = qt_panes.FunKitPane(tmp_path / "funkit", core=core)
    qtbot.addWidget(pane)

    pane.accept_handoff(packet="funkit packet body", title="FCap", source_capture_id=3)
    docs = core.doc_store.get_document_index()
    assert len(docs) == 1
    doc = core.doc_store.get_document(docs[0]["id"])
    assert doc["title"] == "FCap"
    assert doc["body"] == "funkit packet body"
    assert "Imported Dream Capture as document" in pane.status_label.text()
    assert pane.viewer.toPlainText() == "funkit packet body"


# ---------------------------------------------------------------------------
# Progressive enhancement / fallback
# ---------------------------------------------------------------------------


def test_fallback_to_standalone_launcher_when_embedded_pane_fails(monkeypatch):
    import ai_navigator

    bad = types.ModuleType("qt_panes")

    class BoomPane:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("deliberate embedded-pane failure")

    bad.PiKitPane = BoomPane
    bad.FunKitPane = BoomPane
    monkeypatch.setitem(sys.modules, "qt_panes", bad)

    widget = ai_navigator._build_product_widget("PiKit", ai_navigator.PIKIT_ROOT, "pikit")
    assert isinstance(widget, ai_navigator.ProductLauncherPane)

    widget2 = ai_navigator._build_product_widget("FunKit", ai_navigator.FUNKIT_ROOT, "funkit")
    assert isinstance(widget2, ai_navigator.ProductLauncherPane)


def test_suite_shell_hosts_embedded_panes(qtbot, monkeypatch):
    monkeypatch.setattr("ai_navigator.init_db_if_needed", lambda: None)
    monkeypatch.setattr(
        "ai_navigator.GMAIL_JANITOR_SCRIPT",
        MODULE_DIR / "gmail_janitor.py",
    )

    import ai_navigator

    shell = ai_navigator.SuiteShell()
    qtbot.addWidget(shell)
    qtbot.wait(100)

    assert isinstance(shell.product_stack.widget(1), qt_panes.PiKitPane)
    assert isinstance(shell.product_stack.widget(2), qt_panes.FunKitPane)
    # Each embedded pane still exposes the standalone launcher.
    assert isinstance(
        shell.product_stack.widget(1).standalone_launcher,
        ai_navigator.ProductLauncherPane,
    )
    assert isinstance(
        shell.product_stack.widget(2).standalone_launcher,
        ai_navigator.ProductLauncherPane,
    )


def test_embedded_pikit_handoff_from_shell(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr("ai_navigator.init_db_if_needed", lambda: None)
    monkeypatch.setattr(
        "ai_navigator.GMAIL_JANITOR_SCRIPT",
        MODULE_DIR / "gmail_janitor.py",
    )

    import ai_navigator

    shell = ai_navigator.SuiteShell()
    qtbot.addWidget(shell)
    pane = shell.product_stack.widget(1)
    assert isinstance(pane, qt_panes.PiKitPane)

    # Swap in a temp-path core so the shell-level handoff does not touch the
    # real PiKit storage; the packet/core path under test is unchanged.
    tmp_core = _pikit_core(tmp_path)
    pane.core = tmp_core
    pane.core.status_callback = pane.statusMessage.emit

    # Same signal the shell receives from MainWindow.productHandoffRequested.
    shell._handle_product_handoff("PiKit", "shell packet body", "ShellCap", 42)
    assert shell.product_stack.currentIndex() == 1
    qtbot.waitUntil(
        lambda: len(tmp_core.doc_store.get_document_index()) >= 1, timeout=5000
    )
    docs = tmp_core.doc_store.get_document_index()
    assert docs[0]["title"] == "Dream Capture — ShellCap"
    assert tmp_core.doc_store.get_document(docs[0]["id"])["body"] == "shell packet body"
    assert pane.viewer.toPlainText() == "shell packet body"


def test_funkit_pane_routes_dollar_commands_through_core(qtbot, tmp_path):
    core = _funkit_core(tmp_path)
    pane = qt_panes.FunKitPane(tmp_path / "funkit", core=core)
    qtbot.addWidget(pane)

    # "$ NEW" creates a document through the core and reveals it.
    pane.command_line.setText("$ NEW Command Doc")
    pane.command_line.returnPressed.emit()
    docs = core.doc_store.get_document_index()
    assert any(d["title"] == "Command Doc" for d in docs)
    assert "Viewing: Command Doc" in pane.status_label.text()

    # "$ LIST" output is materialized as a document (Tk store_output parity).
    pane.command_line.setText("$ LIST")
    pane.command_line.returnPressed.emit()
    docs = core.doc_store.get_document_index()
    assert any(d["title"] == "$ LIST" for d in docs)


def test_pikit_pane_save_as_text_writes_file(qtbot, tmp_path, monkeypatch):
    core = _pikit_core(tmp_path)
    core.doc_store.add_document("Alpha", "body to save")
    pane = qt_panes.PiKitPane(tmp_path / "pikit", core=core)
    qtbot.addWidget(pane)
    pane.doc_list.setCurrentRow(0)

    out = tmp_path / "alpha.txt"
    monkeypatch.setattr(
        qt_panes.QFileDialog, "getSaveFileName",
        lambda *a, **k: (str(out), "Text files (*.txt)"),
    )
    pane._save_as_text()
    assert out.read_text(encoding="utf-8").strip() == "body to save"
    assert "Saved text" in pane.status_label.text()


def test_funkit_pane_export_document_writes_file(qtbot, tmp_path, monkeypatch):
    core = _funkit_core(tmp_path)
    core.doc_store.add_document("Beta", "raw export body")
    pane = qt_panes.FunKitPane(tmp_path / "funkit", core=core)
    qtbot.addWidget(pane)
    pane.doc_list.setCurrentRow(0)

    out = tmp_path / "beta.bin"
    monkeypatch.setattr(
        qt_panes.QFileDialog, "getSaveFileName",
        lambda *a, **k: (str(out), "All files (*)"),
    )
    pane._export_document()
    assert out.read_text(encoding="utf-8") == "raw export body"
    assert "Exported" in pane.status_label.text()


def test_pikit_pane_renders_opml_outline(qtbot, tmp_path):
    core = _pikit_core(tmp_path)
    xml = (
        '<?xml version="1.0"?><opml version="2.0"><head><title>T</title></head>'
        "<body><outline text=\"Root\"><outline text=\"Child\"/></outline></body></opml>"
    )
    core.doc_store.add_document("Tree", xml)
    pane = qt_panes.PiKitPane(tmp_path / "pikit", core=core)
    qtbot.addWidget(pane)
    pane.doc_list.setCurrentRow(0)

    assert pane.content_stack.currentWidget() is pane.outline_tree
    assert pane.outline_tree.topLevelItemCount() == 1
    assert pane.outline_tree.topLevelItem(0).text(0) == "Root"
    assert pane.outline_tree.topLevelItem(0).childCount() == 1
    assert pane.outline_tree.topLevelItem(0).child(0).text(0) == "Child"


def test_pikit_pane_convert_current_to_opml(qtbot, tmp_path):
    core = _pikit_core(tmp_path)
    core.doc_store.add_document("Alpha", "convert me")
    pane = qt_panes.PiKitPane(tmp_path / "pikit", core=core)
    qtbot.addWidget(pane)
    pane.doc_list.setCurrentRow(0)

    pane._opml_convert_current()
    docs = core.doc_store.get_document_index()
    assert any("(OPML)" in str(d["title"]) for d in docs)
    assert "Converted 1 document." in pane.status_label.text()
    # The converted doc is revealed as an OPML outline.
    assert pane.content_stack.currentWidget() is pane.outline_tree


def test_pikit_pane_batch_convert_to_opml(qtbot, tmp_path):
    core = _pikit_core(tmp_path)
    core.doc_store.add_document("A", "text a")
    core.doc_store.add_document("B", "text b")
    pane = qt_panes.PiKitPane(tmp_path / "pikit", core=core)
    qtbot.addWidget(pane)

    pane._opml_batch_convert()
    docs = core.doc_store.get_document_index()
    assert sum(1 for d in docs if "(OPML)" in str(d["title"])) == 2
    assert "Converted 2 document(s)." in pane.status_label.text()


def test_funkit_pane_provider_combo_and_rag(qtbot, tmp_path):
    core = _funkit_core(tmp_path)
    providers = core.list_providers()
    assert providers
    pane = qt_panes.FunKitPane(tmp_path / "funkit", core=core)
    qtbot.addWidget(pane)

    assert pane.provider_combo.count() == len(providers)
    assert pane.rag_checkbox.isChecked() is False
    pane.rag_checkbox.setChecked(True)
    assert core.is_rag_enabled() is True
    pane.rag_checkbox.setChecked(False)
    assert core.is_rag_enabled() is False

    # Selecting a provider persists it through the core.
    idx = pane.provider_combo.findData(providers[0][0])
    pane.provider_combo.setCurrentIndex(idx)
    assert core.get_selected_provider() == providers[0][0]


def test_funkit_pane_memory_dialog_roundtrip(qtbot, tmp_path):
    core = _funkit_core(tmp_path)
    pane = qt_panes.FunKitPane(tmp_path / "funkit", core=core)
    qtbot.addWidget(pane)

    dialog = qt_panes.MemoryDialog(core, parent=pane)
    qtbot.addWidget(dialog)
    dialog.persona_edit.setText("concise analyst")
    dialog.style_edit.setText("short paragraphs")
    dialog.rules_edit.setPlainText("one rule\nsecond rule")
    dialog._save()

    mem = core.get_memory("global")
    assert mem["persona"] == "concise analyst"
    assert mem["rules"] == ["one rule", "second rule"]


def test_funkit_pane_embedded_memory_adapter_builds(qtbot, tmp_path):
    # Embedded mode must resolve memory_publish_adapter + dream imports (the
    # Stage 2 dual-import fix) so Dream/archive publishing can work.
    import FunKit.core as funkit_core_module

    core = _funkit_core(tmp_path)
    adapter = core.get_memory_publish_adapter()
    assert adapter is not None, "embedded memory adapter should build"
    assert funkit_core_module is not None


def test_funkit_pane_dream_now_shows_capsule(qtbot, tmp_path):
    core = _funkit_core(tmp_path)
    pane = qt_panes.FunKitPane(tmp_path / "funkit", core=core)
    qtbot.addWidget(pane)
    pane._run_dream_now()
    assert "Dream Capsule" in pane.viewer.toPlainText()
    assert "Dream pass completed." in pane.status_label.text()


def test_pikit_pane_renders_binary_image(qtbot, tmp_path):
    import base64

    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )
    core = _pikit_core(tmp_path)
    core.doc_store.add_document("Pic", png)
    pane = qt_panes.PiKitPane(tmp_path / "pikit", core=core)
    qtbot.addWidget(pane)
    pane.doc_list.setCurrentRow(0)

    assert pane.content_stack.currentWidget() is pane.image_label
    assert pane.image_label.pixmap() is not None
    assert not pane.image_label.pixmap().isNull()
    assert "Viewing image" in pane.status_label.text()


def test_funkit_pane_renders_data_uri_image(qtbot, tmp_path):
    import base64

    png = base64.b64encode(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
        )
    ).decode("ascii")
    data_uri = f"data:image/png;base64,{png}"
    core = _funkit_core(tmp_path)
    core.doc_store.add_document("UriPic", data_uri)
    pane = qt_panes.FunKitPane(tmp_path / "funkit", core=core)
    qtbot.addWidget(pane)
    pane.doc_list.setCurrentRow(0)

    assert pane.content_stack.currentWidget() is pane.image_label
    assert not pane.image_label.pixmap().isNull()


def test_pikit_pane_transfer_prompt_rejection(qtbot, tmp_path, monkeypatch):
    import queue as _queue

    core = _pikit_core(tmp_path)
    pane = qt_panes.PiKitPane(tmp_path / "pikit", core=core)
    qtbot.addWidget(pane)

    response_queue: _queue.Queue = _queue.Queue(maxsize=1)
    invite = {"sender_name": "tester", "doc_title": "Doc", "share_url": "http://x"}
    monkeypatch.setattr(
        qt_panes.QMessageBox, "question",
        lambda *a, **k: qt_panes.QMessageBox.No,
    )
    pane._handle_transfer_prompt(invite, response_queue)
    assert response_queue.get()["status"] == "rejected"


def test_pikit_pane_transfer_prompt_accept_imports(qtbot, tmp_path, monkeypatch):
    import queue as _queue
    from unittest.mock import MagicMock

    core = _pikit_core(tmp_path)
    pane = qt_panes.PiKitPane(tmp_path / "pikit", core=core)
    qtbot.addWidget(pane)

    new_doc_id = core.doc_store.add_document("Incoming", "body")
    core.accept_incoming_document = MagicMock(return_value=new_doc_id)
    response_queue: _queue.Queue = _queue.Queue(maxsize=1)
    invite = {"sender_name": "tester", "doc_title": "Doc", "share_url": "http://x"}
    monkeypatch.setattr(
        qt_panes.QMessageBox, "question",
        lambda *a, **k: qt_panes.QMessageBox.Yes,
    )
    pane._handle_transfer_prompt(invite, response_queue)
    response = response_queue.get()
    assert response["status"] == "accepted"
    assert response["imported_doc_id"] == new_doc_id
    core.accept_incoming_document.assert_called_once_with(invite)
    assert pane.current_doc_id == new_doc_id
