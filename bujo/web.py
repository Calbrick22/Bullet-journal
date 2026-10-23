"""The web app: server-rendered pages and plain form posts.

Every page load runs carry-over (idempotent) and a calendar sync (only reads
the export when it changed) first, so a new working day and new meetings are
picked up whenever the app is opened or refreshed. Every write is a form POST
that redirects back, so the basics work without JavaScript; static/js/app.js
upgrades posts to in-place updates and adds the keyboard shortcuts.
"""

from collections.abc import Callable
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import calendar as calmod, dates, journal as j, views
from .db import connect

HERE = Path(__file__).parent
SHOW_COOKIE = "week_show"
# Typed prefixes in the quick-add box: "* Team lunch" is an event, "- idea" a note.
PREFIXES = {"* ": "event", "- ": "note", "– ": "note"}


def create_app(db_path: Path, today: Callable[[], date] = dates.local_today,
               calendar: calmod.CalendarSource | None = None,
               now: Callable[[], datetime] = dates.utc_now) -> FastAPI:
    app = FastAPI(title="Journal", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    def db():
        return closing(connect(db_path))

    def refresh(conn) -> calmod.Status:
        j.carry_over(conn, today=today())
        return calmod.sync(conn, calendar)

    def page(request: Request, name: str, ctx: dict, nav: str, status: calmod.Status):
        t = today()
        cal_week = dates.week_key(t)
        recent = [dates.shift_week(cal_week, -i) for i in (1, 2)]
        return templates.TemplateResponse(request, name, {
            **ctx, "nav": nav, "today": t, "today_label": views.short_day(t),
            "this_week": cal_week, "this_week_number": dates.parse_week_key(cal_week)[1],
            "recent_weeks": [(k, views.week_label(k), views.week_range(k)) for k in recent],
            "next_week": dates.shift_week(cal_week, 1),
            "next_week_label": views.week_label(dates.shift_week(cal_week, 1)),
            "calendar": views.calendar_line(status, now()),
            "next": request.url.path,
        })

    def back(next_url: str) -> RedirectResponse:
        # Only ever redirect within this app (a host in `next` is dropped).
        path = urlsplit(next_url).path if next_url else "/"
        return RedirectResponse(path if path.startswith("/") and not path.startswith("//") else "/", status_code=303)

    # --- Pages --------------------------------------------------------------

    @app.get("/")
    def home():
        return RedirectResponse(f"/week/{dates.week_key(today())}", status_code=303)

    @app.get("/today")
    def go_today():
        return RedirectResponse(f"/day/{today().isoformat()}", status_code=303)

    @app.get("/week")
    def go_week():
        return RedirectResponse(f"/week/{dates.week_key(today())}", status_code=303)

    @app.get("/week/{key}", response_class=HTMLResponse)
    def week(request: Request, key: str, show: str | None = None):
        try:
            dates.parse_week_key(key)
        except ValueError:
            raise HTTPException(404, "No such week")
        # Meetings only by default; the toggle's choice is remembered in a cookie.
        chosen = show if show in views.WEEK_SHOW else request.cookies.get(SHOW_COOKIE)
        chosen = chosen if chosen in views.WEEK_SHOW else "meetings"
        with db() as conn:
            status = refresh(conn)
            ctx = views.week_view(conn, key, today(), now(), chosen)
        nav = "week" if key == dates.week_key(today()) else f"week:{key}"
        response = page(request, "week.html", ctx, nav, status)
        if show in views.WEEK_SHOW:
            response.set_cookie(SHOW_COOKIE, show, max_age=60 * 60 * 24 * 365, samesite="lax", httponly=True)
        return response

    @app.get("/day/{day}", response_class=HTMLResponse)
    def day(request: Request, day: str):
        try:
            d = date.fromisoformat(day)
        except ValueError:
            raise HTTPException(404, "No such day")
        with db() as conn:
            status = refresh(conn)
            ctx = views.day_view(conn, d, today(), now())
        return page(request, "day.html", ctx, "today" if d == today() else "day", status)

    @app.get("/future", response_class=HTMLResponse)
    def future(request: Request):
        with db() as conn:
            status = refresh(conn)
            ctx = views.future_view(conn, today())
        return page(request, "future.html", ctx, "future", status)

    # --- Writes -------------------------------------------------------------

    def act(fn, *args, next_url: str):
        with db() as conn:
            try:
                fn(conn, *args)
            except j.JournalError as e:
                raise HTTPException(400, str(e))
        return back(next_url)

    def location(target: str = "", on: str = "", week: str = "") -> dict:
        """A day or a week, from the composer's select ("d:2026-10-22" /
        "w:2026-W43") or from separate date/week fields (the future log)."""
        try:
            if target:
                kind, value = target.split(":", 1)
                if kind == "d":
                    return {"on": date.fromisoformat(value)}
                if kind == "w":
                    dates.parse_week_key(value)
                    return {"week": value}
                raise ValueError
            if on:
                return {"on": date.fromisoformat(on)}
            if week:
                dates.parse_week_key(week)
                return {"week": week}
        except ValueError:
            pass
        raise HTTPException(400, "Pick a day or a week")

    @app.post("/entries")
    def add(kind: str = Form(...), text: str = Form(...), target: str = Form(""),
            on: str = Form(""), week: str = Form(""), next: str = Form("/")):
        loc = location(target, on, week)
        for prefix, k in PREFIXES.items():
            if text.lstrip().startswith(prefix):
                kind, text = k, text.lstrip()[len(prefix):]
                break
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

    @app.post("/entries/{entry_id}/forward")
    def forward(entry_id: int, next: str = Form("/")):
        return act(lambda conn: j.move_forward(conn, entry_id, today=today()), next_url=next)

    @app.post("/entries/{entry_id}/move")
    def move(entry_id: int, to: str = Form(...), on: str = Form(""), week: str = Form(""), next: str = Form("/")):
        if to == "forward":
            return forward(entry_id, next)
        if to == "next-week":
            loc = {"week": dates.shift_week(dates.week_key(today()), 1)}
        elif to == "date":
            loc = location(on=on)
        elif to == "week":
            loc = location(week=week)
        else:
            raise HTTPException(400, "Unknown move")
        return act(lambda conn: j.move_task(conn, entry_id, today=today(), **loc), next_url=next)

    @app.post("/entries/{entry_id}/edit")
    def edit(entry_id: int, text: str = Form(...), next: str = Form("/")):
        return act(j.edit_text, entry_id, text, next_url=next)

    return app
