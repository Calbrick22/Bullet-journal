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


def test_startup_script_for_the_packaged_exe(tmp_path):
    exe = tmp_path / "Bullet Journal.exe"
    s = startup.script(exe, tmp_path, frozen=True)
    assert f'start "" "{exe}"' in s and "run.py" not in s


def test_quit_stops_via_the_hook(tmp_path):
    from fastapi.testclient import TestClient
    from bujo.web import create_app
    stopped = []
    client = TestClient(create_app(tmp_path / "j.sqlite", quit=lambda: stopped.append(True)))
    r = client.post("/settings/quit")
    assert r.status_code == 200 and "has stopped" in r.text and stopped == [True]


def test_frozen_root_is_next_to_the_exe(tmp_path, monkeypatch):
    import importlib, sys
    from bujo import config
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Bullet Journal.exe"))
    try:
        importlib.reload(config)
        assert config.ROOT == tmp_path and config.Config().db_path == tmp_path / "data" / "journal.sqlite"
    finally:
        monkeypatch.undo()
        importlib.reload(config)
