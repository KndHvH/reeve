# PyInstaller spec: one-folder build of Reeve (dist/Reeve/Reeve.exe).
#
#   uv run pyinstaller packaging/reeve.spec --noconfirm
#
# One folder instead of one file: it starts faster (nothing to unpack on each
# run) and antivirus software flags it far less often. The program's data
# (assets/, config/) is bundled next to the code; paths.ROOT points there
# when frozen. A windowed executable: no console, logs go to reeve.log.

from pathlib import Path

REPO = Path(SPECPATH).parent

a = Analysis(
    [str(REPO / "packaging" / "reeve_main.py")],
    pathex=[str(REPO / "src")],
    datas=[
        (str(REPO / "assets"), "assets"),
        (str(REPO / "config"), "config"),
    ],
    hiddenimports=["reeve.hub", "reeve.tray", "pystray._win32"],
    excludes=[
        # Not used at runtime; keeps the folder small.
        "pytest", "PyInstaller", "setuptools", "pip",
        "matplotlib", "scipy", "pandas", "IPython",
        "webview.platforms.gtk", "webview.platforms.qt", "webview.platforms.cocoa",
        "webview.platforms.android", "webview.platforms.cef",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Reeve",
    icon=str(REPO / "assets" / "app.ico"),
    console=False,
    version=str(REPO / "packaging" / "version_info.txt"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Reeve", upx=False)
