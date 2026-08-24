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
        pass

    def get_config(self):
        return {"provider": "fake"}


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
    core = _pikit_core(tmp_path)
    core.processor.ask_question = MagicMock(return_value="AI reply text")
    pane = qt_panes.PiKitPane(tmp_path / "pikit", core=core)
    qtbot.addWidget(pane)

    pane.command_line.setText("What is the meaning?")
    pane.command_line.returnPressed.emit()

    core.processor.ask_question.assert_called_once_with("What is the meaning?")
    assert "AI reply text" in pane.viewer.toPlainText()
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
    core = _funkit_core(tmp_path)
    core.processor.ask_question = MagicMock(return_value="Funkit reply")
    pane = qt_panes.FunKitPane(tmp_path / "funkit", core=core)
    qtbot.addWidget(pane)

    pane.command_line.setText("Summarize this.")
    pane.command_line.returnPressed.emit()

    core.processor.ask_question.assert_called_once_with("Summarize this.")
    assert "Funkit reply" in pane.viewer.toPlainText()


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
