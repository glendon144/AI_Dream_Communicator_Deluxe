from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import QScrollBar, QPushButton, QTextEdit, QWidget

MODULE_DIR = Path(__file__).resolve().parent.parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))


def test_button_label_scales_down_when_width_is_tight(qtbot):
    import ai_navigator

    button = QPushButton("A deliberately long action label")
    qtbot.addWidget(button)
    button.resize(90, 32)
    original_size = button.font().pointSizeF()

    ai_navigator._fit_button_label(button)

    assert button.font().pointSizeF() < original_size
    assert button.font().pointSizeF() >= 7


def test_webmcp_payload_view_wraps_long_json_lines(qtbot, monkeypatch):
    import ai_navigator

    monkeypatch.setattr(ai_navigator, "WEBMCP_RELAY_SERVER", "/path/that/does/not/exist")
    browser = QWidget()
    pane = ai_navigator.WebMCPActionsPane(browser)
    qtbot.addWidget(browser)
    qtbot.addWidget(pane)
    pane.resize(500, 400)
    pane.show()
    qtbot.wait(10)

    assert pane.payload_view.lineWrapMode() == QTextEdit.WidgetWidth
    assert pane.payload_view.wordWrapMode() == QTextOption.WrapAnywhere
    assert isinstance(pane.resize_scrollbar, QScrollBar)
    assert pane.resize_scrollbar.orientation().name == "Vertical"
    assert pane.resize_scrollbar.height() >= pane.height() - 24


def test_webmcp_resize_scrollbar_emits_horizontal_drag_delta(qtbot):
    import ai_navigator

    bar = ai_navigator.WebMCPResizeScrollBar()
    qtbot.addWidget(bar)
    deltas = []
    bar.dragged.connect(deltas.append)
    bar._last_x = 40
    bar._last_x = 25
    bar.dragged.emit(-15)
    assert deltas == [-15]


def test_restore_layout_reverses_narrow_webmcp_browser_relocation():
    import ai_navigator

    class FakeSplitter:
        def __init__(self):
            self.moves = []

        def insertWidget(self, index, widget):
            self.moves.append((index, widget))

    class FakeWindow:
        pass

    window = FakeWindow()
    window._browser_relocated_for_narrow_webmcp = True
    window.outer_splitter = FakeSplitter()
    window.browser_pane = object()
    window.mid_splitter = object()
    ai_navigator.MainWindow._restore_browser_position(window)
    assert window.outer_splitter.moves == [
        (0, window.browser_pane),
        (1, window.mid_splitter),
    ]
    assert window._browser_relocated_for_narrow_webmcp is False


def test_narrow_webmcp_adds_synced_browser_mirror_and_restore_removes_it(qtbot, monkeypatch):
    import ai_navigator

    monkeypatch.setattr(ai_navigator, "WEBMCP_RELAY_SERVER", "/path/that/does/not/exist")
    window = ai_navigator.MainWindow()
    qtbot.addWidget(window)
    window.resize(1800, 900)
    window.show()
    qtbot.wait(50)

    window.webmcp_pane.show()
    window.mid_splitter.setSizes([700, 700, 0, 200])
    window._handle_mid_splitter_moved(0, 3)

    assert window.webmcp_pane.width() / max(window.mid_splitter.width(), 1) < 0.40
    assert window.browser_mirror_pane is not None
    assert window.outer_splitter.count() == 3
    assert window.outer_splitter.widget(0) is window.browser_pane
    assert window.outer_splitter.widget(2) is window.browser_mirror_pane
    assert window.webmcp_pane.payload_view.lineWrapMode() == QTextEdit.WidgetWidth

    mirror = window.browser_mirror_pane
    window._restore_default_layout()
    qtbot.wait(20)
    assert window.browser_mirror_pane is None
    assert mirror is not window.browser_pane
    assert window.outer_splitter.count() == 2
