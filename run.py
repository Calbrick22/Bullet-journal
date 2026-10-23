"""Start the journal: `py run.py`, then it opens in your browser.

    py run.py              your journal (data/journal.sqlite)
    py run.py --demo       a throwaway sample journal (data/demo.sqlite, rebuilt each time)
    py run.py --no-browser
"""

import argparse
import threading
import webbrowser

import uvicorn

from bujo import config, dates, demo
from bujo.db import connect
from bujo.web import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Bullet journal")
    parser.add_argument("--demo", action="store_true", help="use a fresh sample journal")
    parser.add_argument("--port", type=int, help="port (default from config.toml, else 8765)")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser")
    args = parser.parse_args()

    cfg = config.load()
    port = args.port or cfg.port
    today = (lambda: cfg.today) if cfg.today else dates.local_today
    db_path = cfg.db_path
    if args.demo:
        db_path = cfg.db_path.with_name("demo.sqlite")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.unlink(missing_ok=True)
        with connect(db_path) as conn:
            demo.seed(conn, today())
        conn.close()

    url = f"http://127.0.0.1:{port}/"
    print(f"Journal: {url}  ({db_path})  Ctrl+C to stop")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    # 127.0.0.1 only: never reachable from other machines.
    uvicorn.run(create_app(db_path, today), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
