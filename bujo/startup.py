"""Start the journal when you log in to Windows.

Puts a tiny "Bullet Journal.cmd" in your Startup folder (shell:startup). It
starts the app without a console window (pythonw), and the app opens your
browser as usual. Turning it off deletes the file. Nothing else is changed.
"""

import os
import sys
from pathlib import Path

from .config import ROOT

NAME = "Bullet Journal.cmd"


def startup_dir() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if sys.platform != "win32" or not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def available() -> bool:
    return startup_dir() is not None


def script_path() -> Path | None:
    d = startup_dir()
    return d / NAME if d else None


def is_enabled() -> bool:
    p = script_path()
    return bool(p and p.exists())


def script(python: Path = Path(sys.executable), root: Path = ROOT) -> str:
    windowless = python.with_name("pythonw.exe")
    exe = windowless if windowless.exists() else python
    return (
        "@echo off\r\n"
        "rem Starts the bullet journal at login. Turn off in the journal's Settings.\r\n"
        f'cd /d "{root}"\r\n'
        f'start "" "{exe}" run.py\r\n'
    )


def enable() -> Path:
    p = script_path()
    if p is None:
        raise OSError("Starting at login is only available on Windows")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(script(), encoding="utf-8")
    return p


def disable() -> None:
    p = script_path()
    if p and p.exists():
        p.unlink()
