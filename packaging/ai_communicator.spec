from pathlib import Path

from PyInstaller.building.build_main import Analysis, PYZ, EXE, COLLECT

ROOT = Path(SPECPATH).parent
PYTHONPATH = [str(ROOT / "ai_navigator"), str(ROOT / "PiKit"), str(ROOT / "FunKit")]


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


def make_collect(name: str, script: Path, hiddenimports, datas):
    analysis = Analysis(
        [str(script)], pathex=PYTHONPATH, binaries=[], datas=datas,
        hiddenimports=hiddenimports, hookspath=[], hooksconfig={},
        runtime_hooks=[], excludes=[], noarchive=False,
    )
    pyz = PYZ(analysis.pure)
    exe = EXE(
        pyz, analysis.scripts, [], [], [],
        name=name, debug=False, bootloader_ignore_signals=False,
        strip=False, upx=False, console=True, exclude_binaries=True,
    )
    return COLLECT(
        exe, analysis.binaries, analysis.datas, strip=False, upx=False, name=name,
    )


navigator_collect = make_collect(
    "ai_navigator",
    ROOT / "ai_navigator" / "ai_navigator.py",
    ["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"],
    data_tree("webmcp_relay"),
)
pikit_collect = make_collect(
    "pikit", ROOT / "PiKit" / "main.py", COMMON_HIDDEN_IMPORTS,
    data_tree("PiKit"),
)
funkit_collect = make_collect(
    "funkit", ROOT / "FunKit" / "main.py", COMMON_HIDDEN_IMPORTS,
    data_tree("FunKit"),
)
