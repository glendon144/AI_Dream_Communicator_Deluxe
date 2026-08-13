from __future__ import annotations

import json
import sys
from pathlib import Path

PIKIT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PIKIT_DIR))

from dream_capture_inbox import process_inbox_once


class FakeProcessor:
    def __init__(self):
        self.payloads = []

    def import_shared_document(self, payload):
        self.payloads.append(payload)
        return 73


class FakeStatus:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value


class FakeApp:
    def __init__(self):
        self.refreshed = 0
        self.opened = []
        self.status = FakeStatus()

    def _refresh_index(self):
        self.refreshed += 1

    def _open_doc_id(self, doc_id):
        self.opened.append(doc_id)


def test_process_inbox_imports_refreshes_and_opens_document(tmp_path):
    inbox = tmp_path / "handoffs"
    inbox.mkdir()
    queued = inbox / "dream-capture-4-123.json"
    queued.write_text(
        json.dumps(
            {
                "version": 1,
                "kind": "dream_capture",
                "title": "Dream Capture — Example",
                "body": "Selected source material",
            }
        ),
        encoding="utf-8",
    )
    processor = FakeProcessor()
    app = FakeApp()

    assert process_inbox_once(inbox, processor, app) == [73]
    assert processor.payloads == [
        {
            "title": "Dream Capture — Example",
            "body_encoding": "text",
            "body": "Selected source material",
        }
    ]
    assert app.refreshed == 1
    assert app.opened == [73]
    assert "document 73" in app.status.value
    assert not list(inbox.iterdir())
