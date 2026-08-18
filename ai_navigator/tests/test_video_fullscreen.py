from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWidgets import QApplication

MODULE_DIR = Path(__file__).resolve().parent.parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import ai_navigator


@pytest.fixture
def browser_pane(qtbot):
    pane = ai_navigator.BrowserPane()
    pane.resize(1000, 800)
    qtbot.addWidget(pane)
    pane.show()
    qtbot.wait(50)
    return pane


def test_web_engine_settings_fullscreen_support_enabled(browser_pane):
    view_settings = browser_pane.view.settings()
    page_settings = browser_pane.view.page().settings()
    assert view_settings.testAttribute(
        QWebEngineSettings.WebAttribute.FullScreenSupportEnabled
    ) is True
    assert page_settings.testAttribute(
        QWebEngineSettings.WebAttribute.FullScreenSupportEnabled
    ) is True


def test_video_fullscreen_button_toggles_and_zooms_browser_pane(browser_pane, qtbot):
    toolbar = browser_pane.top_toolbar_splitter.widget(0)
    assert toolbar.isVisible() is True
    assert browser_pane._video_fullscreen_active is False

    browser_pane._set_video_fullscreen(True)
    qtbot.wait(20)

    assert browser_pane._video_fullscreen_active is True
    assert toolbar.isVisible() is False
    assert browser_pane.top_toolbar_splitter.sizes()[0] == 0
    assert browser_pane.video_fullscreen_button.isChecked() is True
    assert browser_pane.video_fullscreen_button.text() == "Restore Browser"
    assert browser_pane.fullscreen_exit_overlay_button.isVisible() is True

    browser_pane._set_video_fullscreen(False)
    qtbot.wait(20)

    assert browser_pane._video_fullscreen_active is False
    assert toolbar.isVisible() is True
    assert browser_pane.top_toolbar_splitter.sizes()[0] > 0
    assert browser_pane.video_fullscreen_button.isChecked() is False
    assert browser_pane.video_fullscreen_button.text() == "Video Full Screen"
    assert browser_pane.fullscreen_exit_overlay_button.isVisible() is False


def test_fullscreen_escape_key_restores_browser_pane(browser_pane, qtbot):
    browser_pane._set_video_fullscreen(True)
    assert browser_pane._video_fullscreen_active is True

    browser_pane._handle_escape_key()
    qtbot.wait(20)

    assert browser_pane._video_fullscreen_active is False
    toolbar = browser_pane.top_toolbar_splitter.widget(0)
    assert toolbar.isVisible() is True
    assert browser_pane.fullscreen_exit_overlay_button.isVisible() is False


def test_web_fullscreen_request_handler(browser_pane, qtbot):
    request_on = MagicMock()
    request_on.toggleOn.return_value = True

    browser_pane._handle_web_fullscreen_request(request_on)
    request_on.accept.assert_called_once()
    assert browser_pane._video_fullscreen_active is True
    assert browser_pane.top_toolbar_splitter.widget(0).isVisible() is False

    request_off = MagicMock()
    request_off.toggleOn.return_value = False

    browser_pane._handle_web_fullscreen_request(request_off)
    request_off.accept.assert_called_once()
    assert browser_pane._video_fullscreen_active is False
    assert browser_pane.top_toolbar_splitter.widget(0).isVisible() is True


def test_video_control_visibility_state(browser_pane):
    browser_pane._set_video_control_visible(True)
    assert browser_pane.video_fullscreen_button.isVisible() is True

    browser_pane._set_video_control_visible(False)
    assert browser_pane.video_fullscreen_button.isVisible() is False
