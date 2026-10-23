from datetime import datetime, timedelta, timezone
from pathlib import Path

from bujo import backup, journal as j, startup
from bujo.db import connect

UTC = timezone.utc


def test_daily_backup_once_a_day_and_keeps_two_weeks(tmp_path):
    db = tmp_path / "journal.sqlite"
    with connect(db) as c:
        j.add_entry(c, "task", "Precious", lst="backlog")
    c.close()
    t = datetime(2026, 10, 22, 8, 0, tzinfo=UTC)
    first = backup.daily(db, t)
    assert first and backup.daily(db, t + timedelta(hours=3)) is None
    restored = connect(first)
    assert [e.text for e in j.entries_in_list(restored, "backlog")] == ["Precious"]
    restored.close()
    for day in range(1, 20):
        backup.daily(db, t + timedelta(days=day))
    assert len(backup.list_backups(db)) == backup.KEEP


def test_no_backup_before_the_journal_exists(tmp_path):
    assert backup.daily(tmp_path / "missing.sqlite") is None


def test_startup_script_points_at_this_folder(tmp_path):
    py = tmp_path / "python.exe"
    py.write_text("")
    (tmp_path / "pythonw.exe").write_text("")
    s = startup.script(py, Path("C:/Users/me/bullet-journal"))
    assert 'cd /d "C:/Users/me/bullet-journal"' in s and "pythonw.exe" in s and s.endswith("run.py\r\n")


def test_startup_on_windows_only(tmp_path, monkeypatch):
    monkeypatch.setattr(startup.sys, "platform", "linux")
    assert not startup.available() and not startup.is_enabled()
    monkeypatch.setattr(startup.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert startup.available() and not startup.is_enabled()
    p = startup.enable()
    assert p.name == "Bullet Journal.cmd" and "Startup" in str(p) and startup.is_enabled()
    startup.disable()
    assert not startup.is_enabled()
