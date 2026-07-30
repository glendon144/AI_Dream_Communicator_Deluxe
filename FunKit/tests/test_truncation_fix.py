from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import requests

MODULES_DIR = Path(__file__).resolve().parent.parent / "modules"
if str(MODULES_DIR) not in sys.path:
    sys.path.insert(0, str(MODULES_DIR))


# -- max_tokens defaults -------------------------------------------------------

def test_max_tokens_defaults_are_reasonable():
    from modules.command_processor import SHORT_MAX_TOKENS, LONG_MAX_TOKENS
    assert SHORT_MAX_TOKENS >= 1024, (
        f"SHORT_MAX_TOKENS={SHORT_MAX_TOKENS} is too low; should be >= 1024"
    )
    assert LONG_MAX_TOKENS >= 2048, (
        f"LONG_MAX_TOKENS={LONG_MAX_TOKENS} is too low; should be >= 2048"
    )
    assert LONG_MAX_TOKENS > SHORT_MAX_TOKENS


# -- finish_reason capture in local_ai_interface -------------------------------

class MockResponse:
    def __init__(self, content: str, finish_reason: str = "stop", status_code: int = 200):
        self.status_code = status_code
        self._json = {
            "choices": [
                {
                    "message": {"content": content, "role": "assistant"},
                    "finish_reason": finish_reason,
                }
            ]
        }
        self._text = json.dumps(self._json)

    def json(self):
        return self._json

    @property
    def text(self):
        return self._text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


@pytest.fixture
def local_ai():
    from modules.local_ai_interface import AIInterface
    return AIInterface(base_url="http://test.local/v1", api_key="test-key", model="test-model")


def test_extract_text_captures_finish_reason_stop(local_ai):
    resp = MockResponse("Complete answer.", finish_reason="stop")
    text = local_ai._extract_text(resp)
    assert text == "Complete answer."
    assert local_ai.last_finish_reason == "stop"


def test_extract_text_captures_finish_reason_length(local_ai):
    resp = MockResponse("Started answer but then", finish_reason="length")
    text = local_ai._extract_text(resp)
    assert text == "Started answer but then"
    assert local_ai.last_finish_reason == "length"


def test_extract_text_clears_previous_finish_reason(local_ai):
    local_ai._last_finish_reason = "stop"
    resp = MockResponse("", finish_reason="stop")
    local_ai._extract_text(resp)
    assert local_ai.last_finish_reason == "stop"


def test_extract_text_completion_fallback_captures_finish_reason(local_ai):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"text": "completion text", "finish_reason": "length"}]
    }
    resp.text = '{"choices": [{"text": "completion text", "finish_reason": "length"}]}'

    with patch.object(local_ai, "_extract_text", wraps=local_ai._extract_text) as wrapped:
        pass

    text = local_ai._extract_text(resp)
    assert text == "completion text"
    assert local_ai.last_finish_reason == "length"


def test_chat_sets_last_finish_reason(local_ai):
    resp = MockResponse("Hello!", finish_reason="stop")
    with patch.object(local_ai, "_session") as mock_session:
        mock_session.post.return_value = resp
        result = local_ai.chat("Say hi")
    assert result == "Hello!"
    assert local_ai.last_finish_reason == "stop"


# -- ai_adapter.last_finish_reason property ------------------------------------

@pytest.fixture
def adapter():
    from modules.ai_adapter import AIInterface
    return AIInterface(provider="openai")


def test_adapter_last_finish_reason_delegates_to_client(adapter):
    mock_client = MagicMock()
    type(mock_client).last_finish_reason = PropertyMock(return_value="stop")
    adapter._client = mock_client
    assert adapter.last_finish_reason == "stop"


def test_adapter_last_finish_reason_none_when_no_client(adapter):
    adapter._client = None
    assert adapter.last_finish_reason is None


def test_adapter_last_finish_reason_none(adapter):
    mock_client = MagicMock()
    type(mock_client).last_finish_reason = PropertyMock(return_value=None)
    adapter._client = mock_client
    assert adapter.last_finish_reason is None


# -- sanitize_ai_reply with finish_reason="length" -----------------------------

from modules.text_sanitizer import sanitize_ai_reply


def test_sanitize_preserves_complete_reply():
    reply = "This is a complete answer with proper ending."
    result = sanitize_ai_reply(reply, finish_reason="stop")
    assert result == reply


def test_sanitize_preserves_incomplete_reply_when_finish_reason_is_length():
    reply = "The German economy in the 2020s faced several structural challenges"
    result = sanitize_ai_reply(reply, finish_reason="length")
    assert result == reply


def test_sanitize_truncates_incomplete_reply_when_no_finish_reason():
    reply = (
        "The German economy in the 2020s faced several interconnected structural "
        "challenges that policymakers struggled to address effectively. "
        "These included energy price shocks from the Ukraine war, demographic "
        "pressures from an aging workforce, and the fiscal constraints of "
        "the debt brake which limited government investment capacity"
    )
    result = sanitize_ai_reply(reply, finish_reason=None)
    assert len(result) < len(reply)
    assert result.endswith("effectively.\n")


def test_sanitize_truncates_incomplete_reply_when_no_finish_reason_and_minlen_met():
    reply = "Short."
    result = sanitize_ai_reply(reply, finish_reason=None)
    assert result == reply


def test_sanitize_does_not_truncate_code_blocks():
    reply = "```python\nprint('hello')\n```"
    result = sanitize_ai_reply(reply, finish_reason="length")
    assert result == reply


def test_sanitize_respects_disabled_env_var(monkeypatch):
    monkeypatch.setenv("PIKIT_TRUNCATE_INCOMPLETE", "0")
    reply = "This is an incomplete"
    result = sanitize_ai_reply(reply, finish_reason="length")
    assert result == reply


# -- command_processor passes finish_reason to sanitize ------------------------

def test_run_ai_query_passes_finish_reason(monkeypatch):
    from modules.command_processor import CommandProcessor
    from modules.document_store import DocumentStore

    mock_ai = MagicMock()
    mock_ai.query.return_value = "Partial response that trails off"
    type(mock_ai).last_finish_reason = PropertyMock(return_value="length")

    doc_store = DocumentStore(":memory:")
    proc = CommandProcessor(doc_store, ai_interface=mock_ai)

    with patch("modules.command_processor.sanitize_ai_reply") as mock_san:
        mock_san.return_value = "cleaned"
        result = proc._run_ai_query("test prompt", 100)

    mock_san.assert_called_once_with(
        "Partial response that trails off",
        finish_reason="length",
    )
    assert result == "cleaned"


def test_ask_question_passes_finish_reason(monkeypatch):
    from modules.command_processor import CommandProcessor
    from modules.document_store import DocumentStore

    mock_ai = MagicMock()
    mock_ai.query.return_value = "Another partial response"
    type(mock_ai).last_finish_reason = PropertyMock(return_value="length")

    doc_store = DocumentStore(":memory:")
    proc = CommandProcessor(doc_store, ai_interface=mock_ai)

    with patch("modules.command_processor.sanitize_ai_reply") as mock_san:
        mock_san.return_value = "cleaned"
        result = proc.ask_question("test question")

    mock_san.assert_called_once_with(
        "Another partial response",
        finish_reason="length",
    )
