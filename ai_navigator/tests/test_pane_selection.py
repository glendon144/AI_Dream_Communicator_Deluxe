from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

MODULE_DIR = Path(__file__).resolve().parent.parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

STORAGE_DIR = MODULE_DIR.parent / "storage"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)


def _click_button(qtbot, window, button):
    qtbot.mouseClick(button, Qt.LeftButton)
    qtbot.wait(100)


@pytest.fixture
def navigator(qtbot, monkeypatch):
    monkeypatch.setattr("ai_navigator.init_db_if_needed", lambda: None)
    monkeypatch.setattr(
        "ai_navigator.GMAIL_JANITOR_SCRIPT",
        MODULE_DIR / "gmail_janitor.py",
    )

    import ai_navigator

    window = ai_navigator.MainWindow()
    window.setMinimumSize(1600, 800)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitForWindowShown(window)
    qtbot.wait(100)
    return window


def test_browser_button_expands_browser(navigator, qtbot):
    _click_button(qtbot, navigator, navigator.browser_menu_button)
    outer_sizes = navigator.outer_splitter.sizes()
    assert outer_sizes[0] > 0
    assert outer_sizes[1] == 0


def test_archive_button_shows_archive_right_of_browser(navigator, qtbot):
    _click_button(qtbot, navigator, navigator.archive_menu_button)
    mid_sizes = navigator.mid_splitter.sizes()
    assert navigator.results_pane.isVisible()
    assert mid_sizes[0] > 0 or navigator.results_pane.width() > 0
    for i in (1, 2, 3):
        widget = navigator.mid_splitter.widget(i)
        assert mid_sizes[i] == 0 or widget.isHidden()


def test_memory_button_shows_memory_right_of_browser(navigator, qtbot):
    _click_button(qtbot, navigator, navigator.memory_menu_button)
    mid_sizes = navigator.mid_splitter.sizes()
    assert navigator.memory_pane.isVisible()
    assert mid_sizes[1] > 0 or navigator.memory_pane.width() > 0
    for i in (0, 2, 3):
        widget = navigator.mid_splitter.widget(i)
        assert mid_sizes[i] == 0 or widget.isHidden()


def test_gmail_button_shows_gmail_right_of_browser(navigator, qtbot):
    _click_button(qtbot, navigator, navigator.gmail_menu_button)
    mid_sizes = navigator.mid_splitter.sizes()
    assert navigator.gmail_pane.isVisible()
    assert mid_sizes[2] > 0 or navigator.gmail_pane.width() > 0
    for i in (0, 1, 3):
        widget = navigator.mid_splitter.widget(i)
        assert mid_sizes[i] == 0 or widget.isHidden()


def test_webmcp_button_shows_webmcp_right_of_browser(navigator, qtbot):
    _click_button(qtbot, navigator, navigator.webmcp_menu_button)
    mid_sizes = navigator.mid_splitter.sizes()
    assert navigator.webmcp_pane.isVisible()
    assert mid_sizes[3] > 0 or navigator.webmcp_pane.width() > 0
    for i in (0, 1, 2):
        widget = navigator.mid_splitter.widget(i)
        assert mid_sizes[i] == 0 or widget.isHidden()


def test_all_panes_button_shows_all_panes(navigator, qtbot):
    _click_button(qtbot, navigator, navigator.webmcp_menu_button)
    _click_button(qtbot, navigator, navigator.restore_menu_button)
    for pane in (
        navigator.results_pane,
        navigator.memory_pane,
        navigator.gmail_pane,
        navigator.webmcp_pane,
    ):
        assert pane.isVisible()


def test_sequential_clicks_swap_panes_correctly(navigator, qtbot):
    _click_button(qtbot, navigator, navigator.memory_menu_button)
    assert navigator.memory_pane.isVisible()
    assert (
        navigator.mid_splitter.sizes()[1] > 0
    )

    _click_button(qtbot, navigator, navigator.archive_menu_button)
    assert navigator.results_pane.isVisible()
    assert (
        navigator.mid_splitter.sizes()[0] > 0
    )

    _click_button(qtbot, navigator, navigator.webmcp_menu_button)
    assert navigator.webmcp_pane.isVisible()
    assert (
        navigator.mid_splitter.sizes()[3] > 0
    )


def test_browser_focus_then_pane_restores_correctly(navigator, qtbot):
    _click_button(qtbot, navigator, navigator.memory_menu_button)
    _click_button(qtbot, navigator, navigator.browser_menu_button)
    outer_sizes = navigator.outer_splitter.sizes()
    assert outer_sizes[1] == 0

    _click_button(qtbot, navigator, navigator.webmcp_menu_button)
    mid_sizes = navigator.mid_splitter.sizes()
    assert navigator.webmcp_pane.isVisible()
    assert mid_sizes[3] > 0
