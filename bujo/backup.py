"""Backups of the journal file: a copy a day, kept for two weeks.

Uses SQLite's own backup, so a copy taken while the app is running is
consistent. Backups live in data/backups next to the journal.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

from . import dates

KEEP = 14


def backup_dir(db_path: Path) -> Path:
    return db_path.parent / "backups"


def list_backups(db_path: Path) -> list[Path]:
    d = backup_dir(db_path)
    return sorted(d.glob("journal-*.sqlite"), reverse=True) if d.exists() else []


def back_up(db_path: Path, now: datetime | None = None) -> Path:
    local = dates.to_local(now or dates.utc_now())
    target = backup_dir(db_path) / f"journal-{local:%Y-%m-%d-%H%M%S}.sqlite"
    target.parent.mkdir(parents=True, exist_ok=True)
    src, dst = sqlite3.connect(db_path), sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    for old in list_backups(db_path)[KEEP:]:
        old.unlink(missing_ok=True)
    return target


def daily(db_path: Path, now: datetime | None = None) -> Path | None:
    """Back up unless there's already a backup from today."""
    if not db_path.exists():
        return None
    today = f"journal-{dates.to_local(now or dates.utc_now()):%Y-%m-%d}"
    if any(p.name.startswith(today) for p in list_backups(db_path)):
        return None
    return back_up(db_path, now)
