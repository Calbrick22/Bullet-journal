"""The web app: server-rendered pages and plain form posts.

Every page load runs carry-over first (it's idempotent), so a new working day
is picked up whenever the app is opened or refreshed. Every write is a form
POST that redirects back, so the app works without JavaScript; static/js/app.js
upgrades those posts to in-place updates.
"""

from collections.abc import Callable
from contextlib import closing
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import dates, journal as j, views
from .db import connect

HERE = Path(__file__).parent


def create_app(db_path: Path, today: Callable[[], date] = dates.local_today) -> FastAPI:
    app = FastAPI(title="Journal", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    def db():
        return closing(connect(db_path))

    def page(request: Request, name: str, ctx: dict, nav: str):
        t = today()
        cal_week = dates.week_key(t)
        recent = [dates.shift_week(cal_week, -i) for i in (1, 2)]
        return templates.TemplateResponse(request, name, {
            **ctx, "nav": nav, "today": t, "today_label": views.short_day(t),
            "this_week": cal_week, "this_week_number": dates.parse_week_key(cal_week)[1],
            "recent_weeks": [(k, views.week_label(k), views.week_range(k)) for k in recent],
            "next": request.url.path,
        })

    def back(next_url: str) -> RedirectResponse:
        # Only ever redirect within this app.
        path = urlsplit(next_url).path if next_url else "/"
        return RedirectResponse(path if path.startswith("/") and not path.startswith("//") else "/", status_code=303)

    # --- Pages --------------------------------------------------------------

    @app.get("/")
    def home():
        return RedirectResponse(f"/week/{dates.week_key(today())}", status_code=303)

    @app.get("/today")
    def go_today():
        return RedirectResponse(f"/day/{today().isoformat()}", status_code=303)

    @app.get("/week/{key}", response_class=HTMLResponse)
    def week(request: Request, key: str):
        try:
            dates.parse_week_key(key)
        except ValueError:
            raise HTTPException(404, "No such week")
        with db() as conn:
            j.carry_over(conn, today=today())
            ctx = views.week_view(conn, key, today())
        nav = "week" if key == dates.week_key(today()) else f"week:{key}"
        return page(request, "week.html", ctx, nav)

    @app.get("/day/{day}", response_class=HTMLResponse)
    def day(request: Request, day: str):
        try:
            d = date.fromisoformat(day)
        except ValueError:
            raise HTTPException(404, "No such day")
        with db() as conn:
            j.carry_over(conn, today=today())
            ctx = views.day_view(conn, d, today())
        return page(request, "day.html", ctx, "today" if d == today() else "day")

    # --- Writes -------------------------------------------------------------

    def act(fn, *args, next_url: str):
        with db() as conn:
            try:
                fn(conn, *args)
            except j.JournalError as e:
                raise HTTPException(400, str(e))
        return back(next_url)

    @app.post("/entries")
    def add(kind: str = Form(...), text: str = Form(...), target: str = Form(...), next: str = Form("/")):
        try:
            where, value = target.split(":", 1)
            loc = {"on": date.fromisoformat(value)} if where == "d" else {"week": value}
            if where not in ("d", "w"):
                raise ValueError
        except ValueError:
            raise HTTPException(400, "Bad target")
        return act(lambda conn: j.add_entry(conn, kind, text, **loc), next_url=next)

    @app.post("/entries/{entry_id}/done")
    def done(entry_id: int, next: str = Form("/")):
        return act(j.mark_done, entry_id, next_url=next)

    @app.post("/entries/{entry_id}/cancel")
    def cancel(entry_id: int, next: str = Form("/")):
        return act(j.cancel, entry_id, next_url=next)

    @app.post("/entries/{entry_id}/reopen")
    def reopen(entry_id: int, next: str = Form("/")):
        return act(j.reopen, entry_id, next_url=next)

    return app
