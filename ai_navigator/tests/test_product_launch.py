from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

MODULE_DIR = Path(__file__).resolve().parent.parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

STORAGE_DIR = MODULE_DIR.parent / "storage"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)


def _click_sidebar_button(qtbot, shell, index: int):
    button = shell.product_buttons[index]
    qtbot.mouseClick(button, Qt.LeftButton)
    qtbot.wait(100)


@pytest.fixture
def suite_shell(qtbot, monkeypatch):
    monkeypatch.setattr("ai_navigator.init_db_if_needed", lambda: None)
    monkeypatch.setattr(
        "ai_navigator.GMAIL_JANITOR_SCRIPT",
        MODULE_DIR / "gmail_janitor.py",
    )

    import ai_navigator

    shell = ai_navigator.SuiteShell()
    shell.setMinimumSize(1600, 900)
    qtbot.addWidget(shell)
    shell.show()
    qtbot.waitForWindowShown(shell)
    qtbot.wait(100)
    return shell


@pytest.fixture
def pikit_pane(suite_shell):
    return suite_shell.product_stack.widget(1)


@pytest.fixture
def pikit_pane_active(pikit_pane, suite_shell, qtbot):
    _click_sidebar_button(qtbot, suite_shell, 1)
    return pikit_pane


@pytest.fixture
def funkit_pane(suite_shell):
    return suite_shell.product_stack.widget(2)


@pytest.fixture
def funkit_pane_active(funkit_pane, suite_shell, qtbot):
    _click_sidebar_button(qtbot, suite_shell, 2)
    return funkit_pane


def test_suite_shell_creates_three_products(suite_shell):
    assert suite_shell.product_stack.count() == 3


def test_sidebar_buttons_have_correct_labels(suite_shell):
    labels = [b.text() for b in suite_shell.product_buttons]
    assert labels == ["AI Navigator", "PiKit", "FunKit"]


def test_ai_navigator_is_main_window(suite_shell):
    import ai_navigator

    assert isinstance(
        suite_shell.product_stack.widget(0), ai_navigator.MainWindow
    )


def test_pikit_is_product_launcher_pane(pikit_pane):
    import ai_navigator

    assert isinstance(pikit_pane, ai_navigator.ProductLauncherPane)


def test_funkit_is_product_launcher_pane(funkit_pane):
    import ai_navigator

    assert isinstance(funkit_pane, ai_navigator.ProductLauncherPane)


def test_pikit_root_path_exists(pikit_pane):
    assert pikit_pane.root_path.exists()
    assert (pikit_pane.root_path / "main.py").exists()


def test_funkit_root_path_exists(funkit_pane):
    assert funkit_pane.root_path.exists()
    assert (funkit_pane.root_path / "main.py").exists()


def test_product_switching_shows_correct_pane(suite_shell, qtbot):
    _click_sidebar_button(qtbot, suite_shell, 0)
    assert suite_shell.product_stack.currentIndex() == 0

    _click_sidebar_button(qtbot, suite_shell, 1)
    assert suite_shell.product_stack.currentIndex() == 1

    _click_sidebar_button(qtbot, suite_shell, 2)
    assert suite_shell.product_stack.currentIndex() == 2


def test_sidebar_button_check_state_tracks_selection(suite_shell, qtbot):
    _click_sidebar_button(qtbot, suite_shell, 1)
    assert suite_shell.product_buttons[1].isChecked()
    assert not suite_shell.product_buttons[0].isChecked()
    assert not suite_shell.product_buttons[2].isChecked()

    _click_sidebar_button(qtbot, suite_shell, 2)
    assert suite_shell.product_buttons[2].isChecked()
    assert not suite_shell.product_buttons[1].isChecked()


def test_pikit_launch_button_exists(pikit_pane_active):
    assert pikit_pane_active.launch_button.text() == "Launch PiKit"


def test_funkit_launch_button_exists(funkit_pane_active):
    assert funkit_pane_active.launch_button.text() == "Launch FunKit"


def test_pikit_python_executable_resolves_to_shared_venv(pikit_pane):
    python_exe = pikit_pane._python_executable()
    expected_unresolved = Path.home() / ".venvs" / "ai_communicator" / "bin" / "python"
    assert python_exe == expected_unresolved


def test_funkit_python_executable_resolves_to_shared_venv(funkit_pane):
    python_exe = funkit_pane._python_executable()
    expected_unresolved = Path.home() / ".venvs" / "ai_communicator" / "bin" / "python"
    assert python_exe == expected_unresolved


def test_pikit_launch_product_sets_correct_process_arguments(
    pikit_pane, monkeypatch
):
    pikit_pane._ensure_runtime_dependencies = MagicMock(return_value=True)
    pikit_pane._ensure_launch_environment = MagicMock(
        return_value=MagicMock()
    )

    python_exe = pikit_pane._python_executable()
    entrypoint = pikit_pane.root_path / "main.py"

    with patch("ai_navigator.QProcess") as mock_qprocess:
        mock_process = MagicMock()
        mock_process.state.return_value = MagicMock()
        mock_qprocess.return_value = mock_process

        pikit_pane.launch_product()

        mock_qprocess.assert_called_once_with(pikit_pane)
        mock_process.setWorkingDirectory.assert_called_once_with(
            str(pikit_pane.root_path)
        )
        mock_process.setProgram.assert_called_once_with(str(python_exe))
        mock_process.setArguments.assert_called_once_with(
            [str(entrypoint)]
        )
        mock_process.start.assert_called_once()


def test_funkit_launch_product_sets_correct_process_arguments(
    funkit_pane, monkeypatch
):
    funkit_pane._ensure_runtime_dependencies = MagicMock(return_value=True)
    funkit_pane._ensure_launch_environment = MagicMock(
        return_value=MagicMock()
    )

    python_exe = funkit_pane._python_executable()
    entrypoint = funkit_pane.root_path / "main.py"

    with patch("ai_navigator.QProcess") as mock_qprocess:
        mock_process = MagicMock()
        mock_process.state.return_value = MagicMock()
        mock_qprocess.return_value = mock_process

        funkit_pane.launch_product()

        mock_qprocess.assert_called_once_with(funkit_pane)
        mock_process.setWorkingDirectory.assert_called_once_with(
            str(funkit_pane.root_path)
        )
        mock_process.setProgram.assert_called_once_with(str(python_exe))
        mock_process.setArguments.assert_called_once_with(
            [str(entrypoint)]
        )
        mock_process.start.assert_called_once()


def test_pikit_dependency_check_openai_is_importable(pikit_pane):
    python_exe = pikit_pane._python_executable()
    result = subprocess.run(
        [
            str(python_exe),
            "-c",
            "import openai; import flask; import pandas; import serial; import PIL",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Missing deps: {result.stderr}"


def test_vertical_menu_launches_pikit_pane_and_triggers_process(suite_shell, qtbot):
    pikit_pane = suite_shell.product_stack.widget(1)
    pikit_pane._ensure_runtime_dependencies = MagicMock(return_value=True)
    pikit_pane._ensure_launch_environment = MagicMock(return_value=MagicMock())

    with patch("ai_navigator.QProcess") as mock_qprocess:
        mock_process = MagicMock()
        mock_process.state.return_value = MagicMock()
        mock_qprocess.return_value = mock_process

        _click_sidebar_button(qtbot, suite_shell, 1)
        pikit_pane.launch_button.click()

        assert suite_shell.product_stack.currentIndex() == 1
        mock_process.start.assert_called_once()


def test_vertical_menu_launches_funkit_pane_and_triggers_process(suite_shell, qtbot):
    funkit_pane = suite_shell.product_stack.widget(2)
    funkit_pane._ensure_runtime_dependencies = MagicMock(return_value=True)
    funkit_pane._ensure_launch_environment = MagicMock(return_value=MagicMock())

    with patch("ai_navigator.QProcess") as mock_qprocess:
        mock_process = MagicMock()
        mock_process.state.return_value = MagicMock()
        mock_qprocess.return_value = mock_process

        _click_sidebar_button(qtbot, suite_shell, 2)
        funkit_pane.launch_button.click()

        assert suite_shell.product_stack.currentIndex() == 2
        mock_process.start.assert_called_once()


def test_env_key_prompt_dialog_sets_missing_key(monkeypatch):
    import os
    import ai_navigator

    monkeypatch.delenv("TEST_PROMPT_KEY", raising=False)
    with patch("ai_navigator.EnvKeyPromptDialog") as mock_dialog_cls:
        mock_dialog_instance = MagicMock()
        mock_dialog_instance.exec.return_value = ai_navigator.QDialog.Accepted
        mock_dialog_instance.key_value.return_value = "secret_key_12345"
        mock_dialog_cls.return_value = mock_dialog_instance

        pane = ai_navigator.ProductLauncherPane(
            "TestProduct",
            "Test description",
            ai_navigator.SUITE_DIR / "PiKit",
            "pikit",
        )
        pane._required_env_keys = lambda: ["TEST_PROMPT_KEY"]

        env = pane._ensure_launch_environment()
        assert env is not None
        assert env.value("TEST_PROMPT_KEY") == "secret_key_12345"
        assert os.environ.get("TEST_PROMPT_KEY") == "secret_key_12345"

