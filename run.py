"""Start the journal: `py run.py`, then it opens in your browser.

    py run.py              your journal (data/journal.sqlite)
    py run.py --demo       a throwaway sample journal (data/demo.sqlite, rebuilt each time)
    py run.py --no-browser
"""

import argparse
import sys
import threading
import urllib.request
import webbrowser
from datetime import datetime, time, timezone

import uvicorn

from bujo import backup, calendar, config, dates, demo
from bujo.db import connect
from bujo.web import create_app


def already_running(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "healthz", timeout=1) as r:
            return r.read() == b"bullet-journal"
    except OSError:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Bullet journal")
    parser.add_argument("--demo", action="store_true", help="use a fresh sample journal")
    parser.add_argument("--port", type=int, help="port (default from config.toml, else 8765)")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser")
    args = parser.parse_args()

    cfg = config.load()
    port = args.port or cfg.port
    today = (lambda: cfg.today) if cfg.today else dates.local_today
    # A pinned date (for trying things out) gets a matching clock: 09:00 that day.
    now = (lambda: datetime.combine(cfg.today, time(9, 0), dates.LOCAL_TZ).astimezone(timezone.utc)) \
        if cfg.today else dates.utc_now
    db_path = cfg.db_path
    calendar_path = cfg.calendar_path
    if args.demo:
        db_path = cfg.db_path.with_name("demo.sqlite")
        calendar_path = cfg.db_path.with_name("demo-calendar.json")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.unlink(missing_ok=True)
        demo.write_calendar(calendar_path, today())
        with connect(db_path) as conn:
            demo.seed(conn, today())
        conn.close()
    source = calendar.PowerAutomateJson(calendar_path) if calendar_path else None

    url = f"http://127.0.0.1:{port}/"
    if already_running(url):
        # Started at login and then double-clicked: just open the one that's running.
        print(f"The journal is already running: {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return
    if sys.stdout is None:
        # Started without a console (pythonw, at login): keep messages in a log file.
        db_path.parent.mkdir(parents=True, exist_ok=True)
        log = open(db_path.parent / "journal.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
    if not args.demo:
        backup.daily(db_path)
    print(f"Journal: {url}  ({db_path})  Ctrl+C to stop")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    # 127.0.0.1 only: never reachable from other machines.
    uvicorn.run(create_app(db_path, today, source, now), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
