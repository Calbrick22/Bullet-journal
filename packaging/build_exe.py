"""Build the packaged app: a folder with Bullet Journal.exe and Python inside.

    python packaging/build_exe.py

Needs `pip install pyinstaller` plus requirements.txt. Produces
dist/Bullet Journal/ and dist/Bullet-Journal-windows.zip (named for the
platform it was built on; build on Windows for the .exe). GitHub Actions does
this on every push (.github/workflows/build-windows.yml).
"""

import importlib.util
import os
import platform
import shutil
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent
NAME = "Bullet Journal"
DIST = ROOT / "dist"


def main() -> None:
    sep = os.pathsep
    args = [
        str(ROOT / "run.py"),
        "--name", NAME,
        "--onedir",                 # a folder, not one self-extracting file: starts faster, fewer antivirus false alarms
        "--windowed",               # no console window; messages go to data/journal.log
        "--noconfirm", "--clean",
        "--distpath", str(DIST),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
        "--add-data", f"{ROOT / 'bujo' / 'templates'}{sep}bujo/templates",
        "--add-data", f"{ROOT / 'bujo' / 'static'}{sep}bujo/static",
        "--collect-data", "tzdata",          # Europe/London on Windows
        "--collect-submodules", "uvicorn",   # uvicorn picks its loop/protocol modules at run time
    ]
    for module in ("python_multipart", "multipart"):   # form posts; the name changed between versions
        if importlib.util.find_spec(module):
            args += ["--hidden-import", module]
    icon = ROOT / "packaging" / "journal.ico"
    if icon.exists():
        args += ["--icon", str(icon)]
    PyInstaller.__main__.run(args)

    app = DIST / NAME
    shutil.copy(ROOT / "config.example.toml", app / "config.example.toml")
    shutil.copy(ROOT / "packaging" / "READ ME FIRST.txt", app / "READ ME FIRST.txt")
    shutil.copy(ROOT / "docs" / "calendar.md", app / "Outlook calendar set-up.md")
    suffix = {"Windows": "windows", "Darwin": "mac"}.get(platform.system(), "linux")
    archive = shutil.make_archive(str(DIST / f"Bullet-Journal-{suffix}"), "zip", DIST, NAME)
    print(f"Built {app}\nZipped {archive}", file=sys.stderr)


if __name__ == "__main__":
    main()
