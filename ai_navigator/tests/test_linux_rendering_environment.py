import os
import sys
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent.parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))


def test_linux_import_configures_both_qt_renderers():
    import ai_navigator

    if sys.platform.startswith("linux"):
        assert os.environ["QT_QUICK_BACKEND"] == "software"
        assert os.environ["QTWEBENGINE_DISABLE_GPU"] == "1"
        assert "--disable-gpu" in os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]
        assert "--disable-features=Vulkan" in os.environ["QTWEBENGINE_CHROMIUM_FLAGS"]
