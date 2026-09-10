from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt

MODULE_DIR = Path(__file__).resolve().parent.parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from ai_assistant_pane import AIAssistantPane, ConversationMessage


class FakeProvider:
    key = "fake"
    label = "Local Test Provider"

    def __init__(self, error: str | None = None):
        self.error = error
        self.calls = []

    def availability(self):
        return True, "Ready"

    def complete(self, messages, context_capsule):
        self.calls.append((messages, context_capsule))
        if self.error:
            raise RuntimeError(self.error)
        return "A provider response"


def test_context_is_explicit_and_conversation_survives_hide(qtbot):
    provider = FakeProvider()
    pane = AIAssistantPane([provider])
    qtbot.addWidget(pane)
    pane.show()

    assert pane.context_capsule is None
    qtbot.mouseClick(pane.update_context_button, Qt.LeftButton)
    assert pane.context_status.text() == "Reading current page locally…"

    pane.set_context("capped private capsule", "Example Page")
    pane.mark_context_stale()
    assert pane.context_status.text().startswith("Previous context")
    pane.input.setPlainText("What is this?")
    qtbot.mouseClick(pane.send_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: len(provider.calls) == 1)
    qtbot.waitUntil(lambda: len(pane.messages) == 2)

    sent_messages, sent_context = provider.calls[0]
    assert sent_context == "capped private capsule"
    assert sent_messages == [ConversationMessage("user", "What is this?")]
    pane.hide()
    pane.show()
    assert [message.content for message in pane.messages] == [
        "What is this?",
        "A provider response",
    ]


def test_provider_failure_is_reported_without_crashing(qtbot):
    pane = AIAssistantPane([FakeProvider(error="offline")])
    qtbot.addWidget(pane)
    pane.input.setPlainText("Hello")
    pane.send_message()
    qtbot.waitUntil(lambda: not pane._request_in_flight)
    assert "Provider error: offline" == pane.status_label.text()
    assert pane.send_button.isEnabled()


def test_provider_unavailable_does_not_start_request(qtbot):
    provider = FakeProvider()
    provider.availability = lambda: (False, "Missing explicit credential")
    pane = AIAssistantPane([provider])
    qtbot.addWidget(pane)
    pane.input.setPlainText("Hello")
    pane.send_message()
    assert provider.calls == []
    assert pane.status_label.text() == "Missing explicit credential"
