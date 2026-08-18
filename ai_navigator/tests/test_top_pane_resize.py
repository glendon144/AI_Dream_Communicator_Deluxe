from __future__ import annotations

import sys
from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QBoxLayout, QSplitter, QWidget

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


def test_browser_splitter_allows_side_pane_to_cover_90_percent(main_window):
    splitter = main_window.outer_splitter
    usable_width = splitter.width() - splitter.handleWidth()
    minimum_browser_width = int(usable_width * 0.10)

    # This is the position produced by dragging the handle far to the left.
    splitter.moveSplitter(0, 1)
    sizes = splitter.sizes()

    assert sizes[0] >= minimum_browser_width
    assert sizes[1] <= int(usable_width * 0.90) + 1


def test_browser_splitter_does_not_limit_normal_expansion_to_90_percent(main_window):
    splitter = main_window.outer_splitter
    width = splitter.width()

    splitter.moveSplitter(int(width * 0.95), 1)

    assert splitter.sizes()[0] > int(width * 0.90)


def test_browser_splitter_drag_target_keeps_browser_at_ten_percent(qtbot):
    """Regression test the handle path without starting the WebEngine view."""
    import ai_navigator

    splitter = ai_navigator.BrowserPaneSplitter(Qt.Horizontal)
    browser = QWidget()
    side_panes = QWidget()
    splitter.addWidget(browser)
    splitter.addWidget(side_panes)
    splitter.resize(1000, 300)
    splitter.show()
    qtbot.addWidget(splitter)
    qtbot.wait(20)

    splitter.moveSplitter(0, 1)

    usable_width = splitter.width() - splitter.handleWidth()
    browser_width, side_width = splitter.sizes()
    assert browser_width >= int(usable_width * 0.10)
    assert side_width <= int(usable_width * 0.90) + 1


def test_all_horizontal_pane_dividers_resize_in_both_directions(qtbot):
    import ai_navigator

    splitter = ai_navigator.PaneSplitter(Qt.Horizontal)
    panes = [QWidget() for _ in range(3)]
    for pane in panes:
        splitter.addWidget(pane)
    splitter.resize(1000, 300)
    splitter.show()
    qtbot.addWidget(splitter)
    qtbot.wait(20)

    usable_width = splitter.width()
    splitter.moveSplitter(0, 1)
    assert splitter.sizes()[0] >= int(usable_width * 0.10) - 2

    splitter.moveSplitter(splitter.width(), 1)
    assert splitter.sizes()[0] <= int(usable_width * 0.90) + 2

    splitter.moveSplitter(0, 2)
    assert splitter.sizes()[0] + splitter.sizes()[1] >= int(usable_width * 0.10) - 6
    splitter.moveSplitter(splitter.width(), 2)
    assert splitter.sizes()[0] + splitter.sizes()[1] <= int(usable_width * 0.90) + 2


def test_archive_actions_stack_when_archive_pane_is_narrow(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr("ai_navigator.init_db_if_needed", lambda: None)
    import ai_navigator

    db_path = tmp_path / "archive.sqlite"
    ai_navigator.ensure_archive_table(db_path)
    pane = ai_navigator.ResultsPane(db_path)
    qtbot.addWidget(pane)
    pane.resize(300, 500)
    pane.show()
    qtbot.wait(20)
    assert pane.width() < 520
    assert pane._details_header_row.direction() == QBoxLayout.TopToBottom


def test_archive_actions_redraw_horizontally_and_remain_visible_when_wide(
    qtbot, tmp_path, monkeypatch
):
    monkeypatch.setattr("ai_navigator.init_db_if_needed", lambda: None)
    import ai_navigator

    db_path = tmp_path / "archive.sqlite"
    ai_navigator.ensure_archive_table(db_path)
    pane = ai_navigator.ResultsPane(db_path)
    qtbot.addWidget(pane)
    pane.resize(1000, 500)
    pane.show()
    qtbot.wait(20)

    assert pane._details_header_row.direction() == QBoxLayout.LeftToRight
    for button in (
        pane.pikit_button,
        pane.funkit_button,
        pane.recover_weave_button,
        pane.recover_chat_button,
        pane.recover_button,
    ):
        assert button.isVisible()
        assert button.width() > 0
