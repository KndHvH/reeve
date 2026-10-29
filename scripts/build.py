"""Builds the Windows app and its installer.

    uv run python scripts/build.py            # dist/Reeve/ and, with Inno Setup, the installer
    uv run python scripts/build.py --no-installer

1. Writes packaging/version_info.txt (the version shown in the file's
   properties) from reeve.__version__, the single source of the version.
2. PyInstaller, one-folder build: dist/Reeve/Reeve.exe.
3. Inno Setup (ISCC.exe, found on PATH or in its default folders), if
   installed: dist/Reeve-<version>-setup.exe.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from reeve import __version__  # noqa: E402

VERSION_INFO = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={tup}, prodvers={tup}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Reeve'),
      StringStruct('FileDescription', 'Reeve, macro assistant for Age of Empires IV'),
      StringStruct('FileVersion', '{ver}'),
      StringStruct('InternalName', 'Reeve'),
      StringStruct('OriginalFilename', 'Reeve.exe'),
      StringStruct('ProductName', 'Reeve'),
      StringStruct('ProductVersion', '{ver}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def iscc() -> str | None:
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if base and (p := Path(base) / "Inno Setup 6" / "ISCC.exe").exists():
            return str(p)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-installer", action="store_true")
    args = ap.parse_args()

    parts = [int(x) for x in __version__.split(".")] + [0] * 4
    tup = tuple(parts[:4])
    (REPO / "packaging" / "version_info.txt").write_text(VERSION_INFO.format(tup=tup, ver=__version__),
                                                          encoding="utf-8")
    subprocess.run([sys.executable, "-m", "PyInstaller", str(REPO / "packaging" / "reeve.spec"),
                    "--noconfirm", "--distpath", str(REPO / "dist"), "--workpath", str(REPO / "build")],
                   check=True, cwd=REPO)
    app = REPO / "dist" / "Reeve"
    size = sum(f.stat().st_size for f in app.rglob("*") if f.is_file()) / 1024 / 1024
    print(f"app: {app} ({size:.0f} MB)")

    if args.no_installer:
        return 0
    compiler = iscc()
    if compiler is None:
        print("Inno Setup not found (ISCC.exe): skipping the installer. Get it from https://jrsoftware.org/isdl.php")
        return 0
    subprocess.run([compiler, f"/DAppVersion={__version__}", str(REPO / "packaging" / "reeve.iss")],
                   check=True, cwd=REPO)
    print(f"installer: {REPO / 'dist' / f'Reeve-{__version__}-setup.exe'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
