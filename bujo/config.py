r"""Local settings, read from config.toml next to run.py (git-ignored).

Every setting has a default, so the file is optional:

    db_path = "data/journal.sqlite"
    port = 8765
    calendar_path = 'C:\Users\you\OneDrive - Org\Apps\BulletJournal\calendar.json'
    # today = "2026-10-22"   # pretend it's this date (testing only)
"""

import os
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    db_path: Path = ROOT / "data" / "journal.sqlite"
    port: int = 8765
    calendar_path: Path | None = None   # the Power Automate export, synced by OneDrive
    today: date | None = None


def load(path: Path = ROOT / "config.toml") -> Config:
    raw = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    db = Path(raw.get("db_path", Config.db_path))
    today = os.environ.get("BUJO_TODAY") or raw.get("today")
    return Config(
        db_path=db if db.is_absolute() else ROOT / db,
        port=int(raw.get("port", Config.port)),
        calendar_path=Path(raw["calendar_path"]).expanduser() if raw.get("calendar_path") else None,
        today=date.fromisoformat(str(today)) if today else None,
    )
