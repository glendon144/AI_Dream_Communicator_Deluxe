from __future__ import annotations

import sys
from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter

MODULE_DIR = Path(__file__).resolve().parent.parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

STORAGE_DIR = MODULE_DIR.parent / "storage"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def main_window(qtbot, monkeypatch):
    monkeypatch.setattr("ai_navigator.init_db_if_needed", lambda: None)
    monkeypatch.setattr(
        "ai_navigator.GMAIL_JANITOR_SCRIPT",
        MODULE_DIR / "gmail_janitor.py",
    )

    import ai_navigator

    window = ai_navigator.MainWindow()
    window.setMinimumSize(1600, 900)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(100)
    return window


def test_main_window_has_vertical_top_splitter(main_window):
    assert hasattr(main_window, "top_splitter")
    assert isinstance(main_window.top_splitter, QSplitter)
    assert main_window.top_splitter.orientation() == Qt.Vertical
    assert main_window.top_splitter.count() == 2
    assert main_window.top_splitter.widget(0) == main_window.menu_bar_row
    assert main_window.top_splitter.widget(1) == main_window.outer_splitter


def test_main_window_top_splitter_can_be_resized(main_window):
    initial_sizes = main_window.top_splitter.sizes()
    new_sizes = [120, initial_sizes[1] - 70]
    main_window.top_splitter.setSizes(new_sizes)
    updated_sizes = main_window.top_splitter.sizes()
    assert updated_sizes[0] > initial_sizes[0]


def test_browser_pane_has_vertical_top_toolbar_splitter(main_window):
    browser_pane = main_window.browser_pane
    assert hasattr(browser_pane, "top_toolbar_splitter")
    assert isinstance(browser_pane.top_toolbar_splitter, QSplitter)
    assert browser_pane.top_toolbar_splitter.orientation() == Qt.Vertical
    assert browser_pane.top_toolbar_splitter.count() == 2

    initial_sizes = browser_pane.top_toolbar_splitter.sizes()
    new_sizes = [150, max(100, initial_sizes[1] - 60)]
    browser_pane.top_toolbar_splitter.setSizes(new_sizes)
    updated_sizes = browser_pane.top_toolbar_splitter.sizes()
    assert updated_sizes[0] > initial_sizes[0]
