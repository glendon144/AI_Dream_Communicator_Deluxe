from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel

MODULE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(MODULE_DIR))

from grab_screenshut import (  # noqa: E402
    append_screenshot_note,
    copy_capsule_with_image,
    grab_screenshot,
)


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_capture_is_saved_and_added_to_clipboard(tmp_path, qt_app):
    widget = QLabel("Rendered browser content")
    widget.resize(640, 360)
    widget.show()
    qt_app.processEvents()

    artifact = grab_screenshot(widget, tmp_path, max_width=320)

    assert artifact.path.exists()
    assert artifact.path.suffix == ".png"
    assert artifact.width == 320
    assert artifact.height == 180

    capsule = append_screenshot_note("Context capsule", artifact)
    assert str(artifact.path) in capsule
    assert "image data on the clipboard" in capsule

    assert copy_capsule_with_image(capsule, artifact)
    mime = qt_app.clipboard().mimeData()
    assert mime.text() == capsule
    assert mime.hasImage()
    assert mime.hasFormat("image/png")
