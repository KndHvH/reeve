"""Builds the Windows app and its installer.

    uv run python scripts/build.py                     # dist/<version>/Reeve/ and the installer
    uv run python scripts/build.py --no-installer
    uv run python scripts/build.py --release           # also publish a GitHub release (gh)
    uv run python scripts/build.py --as-version 0.2.1.99   # test build numbered below, to try updates

1. Writes packaging/version_info.txt (the file's properties) from
   reeve.__version__, the single source of the version, and
   packaging/build_info.json with the version the app shows: plain for
   --release, otherwise e.g. 0.2.2-dev.7+b0c37b9 (see reeve.version).
2. PyInstaller, one-folder build: dist/<version shown>/Reeve/Reeve.exe. Each
   build gets its own folder, so a copy left running never blocks the next.
3. Inno Setup (ISCC.exe, found on PATH or in its default folders), if
   installed: dist/Reeve-<version>-setup.exe.
4. With --release: GitHub release v<version> (tagging the pushed main) with
   the installer attached and docs/releases/v<version>.md as its notes.
"""

from __future__ import annotations

import argparse
import json
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
    ap.add_argument("--release", action="store_true", help="publish the installer as a GitHub release")
    ap.add_argument("--as-version", metavar="X.Y.Z.N",
                    help="number the build as this (lower) version, to test updating from it")
    args = ap.parse_args()

    # The version the app shows: the plain number only for a release, built from
    # a clean tree; otherwise where the build comes from (reeve.version).
    from reeve.version import _git, from_git

    if args.release and _git("status", "--porcelain"):
        print("a release is built from a clean working tree: commit or stash first")
        return 1
    if args.release and args.as_version:
        print("--as-version is for test builds, not releases")
        return 1
    # number: what update checks compare; shown: what the user sees.
    number = args.as_version or __version__
    shown = __version__ if args.release else f"{number}-test" if args.as_version else from_git()
    (REPO / "packaging" / "build_info.json").write_text(json.dumps({"version": shown, "number": number}),
                                                         encoding="utf-8")
    print(f"version shown: {shown}")

    parts = [int(x) for x in number.split(".")] + [0] * 4
    tup = tuple(parts[:4])
    (REPO / "packaging" / "version_info.txt").write_text(VERSION_INFO.format(tup=tup, ver=number),
                                                          encoding="utf-8")
    out = REPO / "dist" / shown
    subprocess.run([sys.executable, "-m", "PyInstaller", str(REPO / "packaging" / "reeve.spec"),
                    "--noconfirm", "--distpath", str(out), "--workpath", str(REPO / "build")],
                   check=True, cwd=REPO)
    app = out / "Reeve"
    size = sum(f.stat().st_size for f in app.rglob("*") if f.is_file()) / 1024 / 1024
    print(f"app: {app} ({size:.0f} MB)")

    if args.no_installer:
        return 0
    compiler = iscc()
    if compiler is None:
        print("Inno Setup not found (ISCC.exe): skipping the installer. Get it from https://jrsoftware.org/isdl.php")
        return 0
    subprocess.run([compiler, f"/DAppVersion={shown}", f"/DFileVersion={number}", f"/DSourceDir={app}",
                    str(REPO / "packaging" / "reeve.iss")], check=True, cwd=REPO)
    installer = REPO / "dist" / f"Reeve-{shown}-setup.exe"
    print(f"installer: {installer}")

    if args.release:
        notes = REPO / "docs" / "releases" / f"v{__version__}.md"
        if not notes.exists():
            print(f"write the release notes first: {notes}")
            return 1
        subprocess.run(["gh", "release", "create", f"v{__version__}", str(installer),
                        "--title", f"Reeve {__version__}", "--notes-file", str(notes)], check=True, cwd=REPO)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
