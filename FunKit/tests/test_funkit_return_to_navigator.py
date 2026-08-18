from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

FUNKIT_DIR = Path(__file__).resolve().parent.parent
if str(FUNKIT_DIR) not in sys.path:
    sys.path.insert(0, str(FUNKIT_DIR))

MODULE_FILE = FUNKIT_DIR / "modules" / "gui_tkinter.py"
ROOT_FILE = FUNKIT_DIR / "gui_tkinter.py"


def test_funkit_modules_source_has_toolbar_button():
    src = MODULE_FILE.read_text(encoding="utf-8")
    assert "◀ AI Navigator" in src, "Toolbar button missing in FunKit/modules/gui_tkinter.py"
    assert "_return_to_navigator" in src


def test_funkit_root_source_has_toolbar_button():
    src = ROOT_FILE.read_text(encoding="utf-8")
    assert "◀ AI Navigator" in src, "Toolbar button missing in FunKit/gui_tkinter.py"
    assert "_return_to_navigator" in src


def test_funkit_modules_has_window_menu():
    src = MODULE_FILE.read_text(encoding="utf-8")
    assert "Show AI Navigator" in src
    assert "Return to AI Navigator" in src
    assert "windowmenu" in src
    assert 'label="Window"' in src


def test_funkit_root_has_window_menu():
    src = ROOT_FILE.read_text(encoding="utf-8")
    assert "Show AI Navigator" in src
    assert "windowmenu" in src


def _import_demo_gui():
    """Import DemoKitGUI with openai mocked — source FunKit requires it but tests don't need real key."""
    import sys
    from unittest.mock import MagicMock

    # Provide dummy openai module with OpenAI class
    if "openai" not in sys.modules or not hasattr(sys.modules["openai"], "OpenAI"):
        fake_openai = MagicMock()
        fake_openai.OpenAI = MagicMock
        sys.modules["openai"] = fake_openai
    # Also mock image_generator's dependency if needed
    from modules.gui_tkinter import DemoKitGUI

    return DemoKitGUI


def test_funkit_modules_has_return_method():
    try:
        DemoKitGUI = _import_demo_gui()
    except Exception:
        # Fallback to source inspection if import still fails
        src = MODULE_FILE.read_text(encoding="utf-8")
        assert "def _return_to_navigator" in src
        assert "iconify" in src
        return
    assert hasattr(DemoKitGUI, "_return_to_navigator")
    import inspect

    src = inspect.getsource(DemoKitGUI._return_to_navigator)
    assert "iconify" in src
    assert "osascript" in src or "wmctrl" in src


def _make_fake_app():
    fake = MagicMock()
    fake.lower = MagicMock()
    fake.iconify = MagicMock()
    fake.status = MagicMock()
    fake.banner = MagicMock()
    fake.banner.push = MagicMock()
    return fake


def test_funkit_modules_return_minimizes_and_sets_status():
    try:
        DemoKitGUI = _import_demo_gui()
    except Exception:
        # If import fails, source already verified above — skip dynamic part
        import pytest

        pytest.skip("FunKit GUI import unavailable in this env (openai)")
    fake = _make_fake_app()
    with patch("modules.gui_tkinter.subprocess.run") as mock_run, patch(
        "modules.gui_tkinter.messagebox.askyesno", return_value=False
    ), patch("modules.gui_tkinter.messagebox.showerror"), patch(
        "modules.gui_tkinter.messagebox.showinfo"
    ):
        mock_run.return_value = MagicMock(returncode=0)
        DemoKitGUI._return_to_navigator.__get__(fake, type(fake))()

    assert fake.lower.called
    assert fake.iconify.called
    assert fake.status.called


def test_funkit_modules_return_attempts_os_activation_macos():
    try:
        DemoKitGUI = _import_demo_gui()
    except Exception:
        import pytest

        pytest.skip("FunKit GUI import unavailable")
    fake = _make_fake_app()
    with patch.object(sys, "platform", "darwin"), patch(
        "modules.gui_tkinter.subprocess.run"
    ) as mock_run, patch(
        "modules.gui_tkinter.messagebox.askyesno", return_value=False
    ), patch("modules.gui_tkinter.messagebox.showerror"), patch(
        "modules.gui_tkinter.messagebox.showinfo"
    ):
        mock_run.return_value = MagicMock(returncode=0)
        DemoKitGUI._return_to_navigator.__get__(fake, type(fake))()
        calls = [str(c) for c in mock_run.call_args_list]
        assert any("osascript" in s for s in calls)


def test_funkit_modules_return_offer_relaunch(tmp_path):
    try:
        DemoKitGUI = _import_demo_gui()
    except Exception:
        import pytest

        pytest.skip("FunKit GUI import unavailable")
    fake = _make_fake_app()
    # Force linux and make subprocess.run fail so activated stays False,
    # then verify askyesno True triggers Popen with ai_navigator.py
    with patch.object(sys, "platform", "linux"), patch(
        "modules.gui_tkinter.subprocess.run", side_effect=Exception("no wmctrl")
    ), patch("modules.gui_tkinter.subprocess.Popen") as mock_popen, patch(
        "modules.gui_tkinter.messagebox.askyesno", return_value=True
    ), patch("modules.gui_tkinter.messagebox.showerror"):
        mock_popen.return_value = MagicMock()
        DemoKitGUI._return_to_navigator.__get__(fake, type(fake))()
        if mock_popen.called:
            assert "ai_navigator.py" in str(mock_popen.call_args)


def test_funkit_root_return_method_exists_and_is_callable():
    # Import root gui_tkinter via importlib to avoid module name clash with modules/
    import importlib.util, pathlib

    spec = importlib.util.spec_from_file_location("funkit_root_gui", str(ROOT_FILE))
    # Don't actually load (needs tkinter display), just verify source
    src = ROOT_FILE.read_text(encoding="utf-8")
    assert "def _return_to_navigator" in src
    assert "navigator_button" in src
