from pathlib import Path

from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT, BUNDLE

# SPECPATH is the directory containing this file (``packaging``), while all
# paths below are relative to the repository root.
ROOT = Path(SPECPATH).resolve().parent
PYTHONPATH = [str(ROOT / "ai_navigator"), str(ROOT / "PiKit"), str(ROOT / "FunKit")]

# PyInstaller's PySide6 hook collects the QtWebEngineCore framework, but can
# omit the nested helper app when several applications are collected from one
# spec.  QtWebEngineCore needs this subprocess at runtime.
QTWEBENGINE_HELPER = (
    Path(__import__("PySide6").__file__).resolve().parent
    / "Qt" / "lib" / "QtWebEngineCore.framework" / "Helpers"
    / "QtWebEngineProcess.app"
)


def data_tree(name: str):
    source_root = ROOT / name
    return [
        (str(path), str(path.relative_to(ROOT).parent))
        for path in source_root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    ]


COMMON_HIDDEN_IMPORTS = [
    "tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox",
    "tkinter.simpledialog",
    "modules.pikit_port",
    "modules.pikit_port.opml_extras_plugin",
    "modules.pikit_port.aopml_engine",
    "modules.pikit_port.ai_interface",
]


def make_collect(name: str, script: Path, hiddenimports, datas, app_name: str | None = None):
    analysis = Analysis(
        [str(script)], pathex=PYTHONPATH, binaries=[], datas=datas,
        hiddenimports=hiddenimports, hookspath=[], hooksconfig={},
        runtime_hooks=[], excludes=[], noarchive=False,
    )
    pyz = PYZ(analysis.pure)
    exe = EXE(
        pyz, analysis.scripts, [], [], [],
        name=name, debug=False, bootloader_ignore_signals=False,
        # The navigator is a GUI app.  console=True causes PyInstaller to mark
        # the macOS bundle as background-only, so Finder appears to do nothing.
        strip=False, upx=False, console=not bool(app_name), exclude_binaries=True,
    )
    if app_name:
        return BUNDLE(
            exe, analysis.binaries, analysis.datas,
            name=app_name, icon=None, bundle_identifier="com.gross.ai-dream-communicator-deluxe",
        )
    return COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name=name)


navigator_collect = make_collect(
    "ai_navigator",
    ROOT / "ai_navigator" / "ai_navigator.py",
    ["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"],
    data_tree("ai_navigator") + data_tree("webmcp_relay") + [
        (str(QTWEBENGINE_HELPER),
         "PySide6/Qt/lib/QtWebEngineCore.framework/Helpers/QtWebEngineProcess.app"),
    ],
    app_name="ai_dream_communicator_deluxe.app",
)
pikit_collect = make_collect(
    "pikit", ROOT / "PiKit" / "main.py", COMMON_HIDDEN_IMPORTS,
    data_tree("PiKit"),
)
funkit_collect = make_collect(
    "funkit", ROOT / "FunKit" / "main.py", COMMON_HIDDEN_IMPORTS,
    data_tree("FunKit"),
)
