import json
import re
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from bujo import calendar as calmod, journal as j
from bujo.db import connect
from bujo.web import create_app


class Clock:
    def __init__(self, d: str):
        self.d = date.fromisoformat(d)

    def __call__(self) -> date:
        return self.d


@pytest.fixture
def env(tmp_path):
    path = tmp_path / "j.sqlite"
    clock = Clock("2026-10-22")  # Thursday, week 43
    client = TestClient(create_app(path, clock))
    return client, clock, path


def db(path):
    return connect(path)


def test_home_redirects_to_this_week(env):
    client, _, _ = env
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/week/2026-W43"
    assert client.get("/today", follow_redirects=False).headers["location"] == "/day/2026-10-22"


def test_week_page_shows_working_days_and_today(env):
    client, _, _ = env
    html = client.get("/week/2026-W43?show=all").text
    assert "Thursday, week 43" in html
    assert re.findall(r'<h2><a href="/day/[\d-]+">(\w+ \d+)</a></h2>', html) == \
        ["Mon 19", "Tue 20", "Wed 21", "Thu 22", "Fri 23"]
    assert 'class="today-label">Today<' in html


def test_bank_holiday_shown_in_spread(env):
    client, _, _ = env
    html = client.get("/week/2026-W53").text
    assert "Week 53" in html
    assert "Boxing Day (substitute day)" in html  # Mon 28 Dec


def test_bad_urls_404(env):
    client, _, _ = env
    assert client.get("/week/2025-W53").status_code == 404
    assert client.get("/day/2026-13-01").status_code == 404


def test_quick_add_then_tick_done_and_untick(env):
    client, _, path = env
    r = client.post("/entries", data={"kind": "task", "text": "Write report", "target": "d:2026-10-22",
                                      "next": "/week/2026-W43"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/week/2026-W43"
    with db(path) as conn:
        [e] = j.entries_for_day(conn, date(2026, 10, 22))
    html = client.get("/week/2026-W43?show=all").text
    assert f'id="t{e.id}" type="submit" role="checkbox" aria-checked="false"' in html

    client.post(f"/entries/{e.id}/done", data={"next": "/week/2026-W43"})
    html = client.get("/week/2026-W43?show=all").text
    assert 'class="entry task done"' in html and 'aria-checked="true"' in html

    client.post(f"/entries/{e.id}/reopen", data={"next": "/"})
    with db(path) as conn:
        assert j.get_entry(conn, e.id).state == "open"


def test_add_to_week_without_a_day(env):
    client, _, path = env
    client.post("/entries", data={"kind": "task", "text": "Someday this week", "target": "w:2026-W44"})
    with db(path) as conn:
        _, unplaced = j.entries_for_week(conn, "2026-W44")
    assert [e.text for e in unplaced] == ["Someday this week"]


def test_add_rejects_bad_input(env):
    client, _, _ = env
    assert client.post("/entries", data={"kind": "task", "text": "  ", "target": "d:2026-10-22"}).status_code == 400
    assert client.post("/entries", data={"kind": "idea", "text": "x", "target": "d:2026-10-22"}).status_code == 400
    assert client.post("/entries", data={"kind": "task", "text": "x", "target": "nonsense"}).status_code == 400
    assert client.post("/entries/999/done", data={}).status_code == 400


def test_redirect_stays_on_this_site(env):
    client, _, _ = env
    r = client.post("/entries", data={"kind": "note", "text": "n", "target": "d:2026-10-22",
                                      "next": "https://evil.example/x"}, follow_redirects=False)
    assert r.headers["location"] == "/x"
    r = client.post("/entries", data={"kind": "note", "text": "n", "target": "d:2026-10-22",
                                      "next": "//evil.example/x"}, follow_redirects=False)
    assert r.headers["location"] == "/x"  # host dropped: a local path, never another site


def test_cancel_and_restore(env):
    client, _, path = env
    client.post("/entries", data={"kind": "task", "text": "Maybe", "target": "d:2026-10-22"})
    with db(path) as conn:
        [e] = j.entries_for_day(conn, date(2026, 10, 22))
    client.post(f"/entries/{e.id}/cancel", data={})
    html = client.get("/day/2026-10-22").text
    assert "tick off" in html and ">cancelled<" in html and "Restore" in html
    client.post(f"/entries/{e.id}/reopen", data={})
    with db(path) as conn:
        assert j.get_entry(conn, e.id).state == "open"


def test_opening_the_app_carries_over_once(env):
    client, clock, path = env
    client.post("/entries", data={"kind": "task", "text": "Unfinished", "target": "d:2026-10-22"})
    clock.d = date(2026, 10, 26)  # Monday after
    for _ in range(3):
        client.get("/")
        client.get("/week/2026-W44")
    with db(path) as conn:
        today = j.entries_for_day(conn, date(2026, 10, 26))
        assert [(e.text, e.carry_count) for e in today] == [("Unfinished", 1)]
        assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 2
    html = client.get("/week/2026-W44?show=all").text
    assert "2nd day" in html and "Thu › Mon" in html


def test_symbols_for_each_kind(env):
    client, _, _ = env
    for kind in ("task", "note", "event"):
        client.post("/entries", data={"kind": kind, "text": f"A {kind}", "target": "d:2026-10-22"})
    html = client.get("/day/2026-10-22").text
    assert 'class="tick"' in html          # task: tick box
    assert 'class="sig dash"' in html      # note: dash
    assert 'class="sig star"' in html      # event: star


def test_demo_seed_runs_through_real_code(tmp_path):
    from bujo import demo
    with connect(tmp_path / "d.sqlite") as conn:
        demo.seed(conn, date(2026, 10, 22))
        rows = j.entries_for_day(conn, date(2026, 10, 22))
        carried = sorted(e.carry_count for e in rows if e.carry_count)
        assert carried == [1, 2, 3]
        assert j.carry_over(conn, today=date(2026, 10, 22)) == []


# --- Week toggle and meetings ------------------------------------------------

def export(tmp_path, events):
    f = tmp_path / "calendar.json"
    f.write_text(json.dumps({"exported_at": "2026-10-22T07:45:00Z", "events": events}), encoding="utf-8")
    return calmod.PowerAutomateJson(f)


@pytest.fixture
def with_meetings(tmp_path):
    src = export(tmp_path, [
        {"id": "m1", "subject": "Ops review", "start": "2026-10-22T10:00:00.0000000", "end": "2026-10-22T11:00:00.0000000",
         "location": "Room 3.12", "showAs": "busy"},
        {"id": "m2", "subject": "Maybe sync", "start": "2026-10-22T13:00:00.0000000", "end": "2026-10-22T13:30:00.0000000",
         "showAs": "tentative"},
        {"id": "m3", "subject": "Canceled: Old thing", "start": "2026-10-21T13:00:00.0000000", "end": "2026-10-21T14:00:00.0000000"},
    ])
    clock = Clock("2026-10-22")
    now = lambda: datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc)   # 09:00 BST
    client = TestClient(create_app(tmp_path / "j.sqlite", clock, src, now))
    return client, tmp_path / "j.sqlite"


def test_meetings_grid_places_meetings_and_now_line(with_meetings):
    client, _ = with_meetings
    html = client.get("/week/2026-W43").text
    # 11:00 BST is 3 h after 08:00: 3 x 56 = 168px; 13:00 UTC = 14:00 BST, 30 min tall
    assert 'style="top: 168px; height: 54px; --lane: 0; --lanes: 1"' in html
    assert 'style="top: 336px; height: 26px; --lane: 0; --lanes: 1"' in html
    assert 'class="now-line" style="top: 56px"' in html      # now = 09:00 BST


def test_week_defaults_to_meetings_only(with_meetings):
    client, _ = with_meetings
    client.post("/entries", data={"kind": "task", "text": "Hidden task", "target": "d:2026-10-22"})
    html = client.get("/week/2026-W43").text
    assert "Ops review" in html and "11:00–12:00" in html and "Room 3.12" in html   # local time (BST)
    assert "Hidden task" not in html and "No day yet" not in html
    assert 'class="meeting tentative' in html and "Old thing" not in html           # cancelled hidden
    assert "2 meetings, 1 h 30 m this week · next: Ops review at 11:00" in html
    assert 'aria-current="true">Meetings<' in html


def test_toggle_shows_tasks_and_is_remembered(with_meetings):
    client, _ = with_meetings
    client.post("/entries", data={"kind": "task", "text": "Visible task", "target": "d:2026-10-22"})
    r = client.get("/week/2026-W43?show=all")
    assert "Visible task" in r.text and "Ops review" in r.text and "No day yet" in r.text
    assert "week_show=all" in r.headers["set-cookie"]
    assert 'aria-current="true">Meetings and tasks<' in client.get("/week/2026-W44").text  # other weeks too
    assert 'aria-current="true">Meetings and tasks<' in client.get("/week/2026-W43").text
    client.get("/week/2026-W43?show=meetings")
    assert "Visible task" not in client.get("/week/2026-W43").text


def test_day_view_lists_meetings_and_sidebar_status(with_meetings):
    client, _ = with_meetings
    html = client.get("/day/2026-10-22").text
    assert "Ops review" in html and "Maybe sync" in html
    assert "Outlook as of 08:45" in html


def test_calendar_not_set_up_message(env):
    client, _, _ = env
    assert "Calendar not set up" in client.get("/day/2026-10-22").text


# --- Moving, editing, prefixes, future log ------------------------------------

def add(client, text, target="d:2026-10-22", kind="task"):
    client.post("/entries", data={"kind": kind, "text": text, "target": target})


def only(path, d):
    with db(path) as conn:
        return j.entries_for_day(conn, date.fromisoformat(d))


def test_forward_moves_to_next_working_day(env):
    client, _, path = env
    add(client, "Push me")
    [e] = only(path, "2026-10-22")
    assert client.post(f"/entries/{e.id}/forward", data={}).status_code == 200
    assert [x.text for x in only(path, "2026-10-23")] == ["Push me"]
    assert only(path, "2026-10-22")[0].state == "migrated"


def test_move_to_date_week_and_next_week(env):
    client, _, path = env
    for t in ("To a date", "To a week", "To next week"):
        add(client, t)
    a, b, c = only(path, "2026-10-22")
    client.post(f"/entries/{a.id}/move", data={"to": "date", "on": "2026-11-05"})
    client.post(f"/entries/{b.id}/move", data={"to": "week", "week": "2026-W46"})
    client.post(f"/entries/{c.id}/move", data={"to": "next-week"})
    assert [x.text for x in only(path, "2026-11-05")] == ["To a date"]
    with db(path) as conn:
        assert [x.text for x in j.entries_for_week(conn, "2026-W46")[1]] == ["To a week"]
        assert [x.text for x in j.entries_for_week(conn, "2026-W44")[1]] == ["To next week"]
    assert client.post(f"/entries/{a.id}/move", data={"to": "date", "on": "nope"}).status_code == 400
    assert client.post(f"/entries/{a.id}/move", data={"to": "sideways"}).status_code == 400


def test_edit(env):
    client, _, path = env
    add(client, "Tpyo")
    [e] = only(path, "2026-10-22")
    client.post(f"/entries/{e.id}/edit", data={"text": "Typo"})
    assert only(path, "2026-10-22")[0].text == "Typo"
    assert client.post(f"/entries/{e.id}/edit", data={"text": "  "}).status_code == 400


def test_prefixes_set_the_kind(env):
    client, _, path = env
    add(client, "* Team lunch")
    add(client, "- Remember the milk")
    add(client, "Plain task")
    assert [(e.kind, e.text) for e in only(path, "2026-10-22")] == [
        ("event", "Team lunch"), ("note", "Remember the milk"), ("task", "Plain task")]


def test_future_log(env):
    client, _, path = env
    client.post("/entries", data={"kind": "task", "text": "Dentist", "on": "2026-11-05"})
    client.post("/entries", data={"kind": "task", "text": "Headcount plan", "week": "2026-W46"})
    client.post("/entries", data={"kind": "task", "text": "Christmas cards", "on": "2026-12-14"})
    html = client.get("/future").text
    assert "3 entries planned after this week" in html
    assert html.index("November 2026") < html.index("Dentist") < html.index("Headcount plan") < html.index("December 2026")
    assert "Christmas Day" in html and "Weeks ahead" in html
    assert client.post("/entries", data={"kind": "task", "text": "x"}).status_code == 400   # no day or week


# --- Backlog, ongoing, categories, settings -----------------------------------

def test_healthz(env):
    client, _, _ = env
    assert client.get("/healthz").text == "bullet-journal"


def test_backlog_and_ongoing_from_any_add_box(env):
    client, _, path = env
    client.post("/entries", data={"kind": "task", "text": "Tidy the wiki", "target": "l:backlog"})
    client.post("/entries", data={"kind": "task", "text": "Budget model", "target": "l:ongoing"})
    html = client.get("/backlog").text
    assert "1 ongoing · 1 in the backlog" in html and ">Start<" in html
    assert "Budget model" in client.get("/day/2026-10-22").text            # ongoing shows on the day
    assert client.post("/entries", data={"kind": "note", "text": "n", "target": "l:backlog"}).status_code == 400
    assert client.post("/entries", data={"kind": "task", "text": "x", "target": "l:someday"}).status_code == 400


def test_start_from_backlog_each_way(env):
    client, _, path = env
    for t in ("To ongoing", "To today", "To a date"):
        client.post("/entries", data={"kind": "task", "text": t, "target": "l:backlog"})
    with db(path) as conn:
        a, b, c = j.entries_in_list(conn, "backlog")
    client.post(f"/entries/{a.id}/move", data={"to": "ongoing"})
    client.post(f"/entries/{b.id}/move", data={"to": "today"})
    client.post(f"/entries/{c.id}/move", data={"to": "date", "on": "2026-11-02"})
    with db(path) as conn:
        assert [e.text for e in j.entries_in_list(conn, "ongoing")] == ["To ongoing"]
        assert j.entries_in_list(conn, "backlog") == []
    assert [e.text for e in only(path, "2026-10-22")] == ["To today"]
    assert [e.text for e in only(path, "2026-11-02")] == ["To a date"]


def test_tag_meeting_by_name_and_only_this(with_meetings):
    client, path = with_meetings
    client.get("/week/2026-W43")   # sync the calendar
    client.post("/settings/categories", data={"name": "Atlas", "colour": "mint"})
    client.post("/settings/categories", data={"name": "Internal", "colour": "lime"})
    with db(path) as conn:
        from bujo import categories as cats
        atlas, internal = cats.all_categories(conn)
    client.post("/meetings/m1/category", data={"category": str(atlas.id)})
    html = client.get("/week/2026-W43").text
    assert 'cat cat-mint' in html and 'data-meeting="m1"' in html
    client.post("/meetings/m1/category", data={"category": str(internal.id), "only_this": "1"})
    assert 'cat cat-lime' in client.get("/day/2026-10-22").text
    client.post("/meetings/m1/category", data={"category": ""})
    assert 'cat cat-' not in client.get("/day/2026-10-22").text.split("<dialog")[0]
    assert client.post("/meetings/nope/category", data={"category": str(atlas.id)}).status_code == 400


def test_manage_categories(env):
    client, _, path = env
    client.post("/settings/categories", data={"name": "Atlas", "colour": "mint"})
    assert client.post("/settings/categories", data={"name": "atlas", "colour": "sky"}).status_code == 400
    with db(path) as conn:
        from bujo import categories as cats
        [c] = cats.all_categories(conn)
    client.post(f"/settings/categories/{c.id}", data={"name": "Atlas project", "colour": "rose"})
    client.post(f"/settings/categories/{c.id}/archive", data={})
    html = client.get("/settings").text
    assert "Archived" in html and "Atlas project" in html and "Restore" in html
    client.post(f"/settings/categories/{c.id}/restore", data={})
    assert "Archived" not in client.get("/settings").text


def test_working_days_and_leave_from_settings(env):
    client, _, path = env
    client.post("/settings/weekdays", data={"weekday": ["0", "1", "2", "3"]})
    with db(path) as conn:
        assert j.load_calendar(conn).working_weekdays == {0, 1, 2, 3}
    assert client.post("/settings/weekdays", data={}).status_code == 400   # at least one day
    client.post("/settings/leave", data={"start": "2026-11-09", "end": "2026-11-13", "reason": "Annual leave"})
    html = client.get("/settings").text
    assert "9–12 Nov" in html and "4 days" in html          # Fri isn't a working day any more
    client.post("/settings/leave/remove", data={"start": "2026-11-09", "end": "2026-11-12"})
    assert "No days off booked" in client.get("/settings").text
    assert client.post("/settings/leave", data={"start": "2026-11-13", "end": "2026-11-09"}).status_code == 400


def test_backup_now(env):
    client, _, path = env
    client.post("/settings/backup", data={})
    assert "journal-" in client.get("/settings").text


def test_startup_toggle_off_windows(env):
    client, _, _ = env
    assert "Available when the journal runs on Windows" in client.get("/settings").text
    assert client.post("/settings/startup", data={"on": "1"}).status_code == 400


def test_pages_render_after_moving_day_tasks_onto_lists(env):
    """Regression: a day task moved to Backlog/Ongoing crashed the day and backlog pages."""
    client, clock, path = env
    for t in ("To backlog", "To ongoing", "Carried then shelved"):
        add(client, t, target="d:2026-10-21")
    clock.d = date(2026, 10, 22)
    client.get("/")                                   # carry-over: all three now on Thu, 2nd day
    a, b, c = only(path, "2026-10-22")
    assert client.post(f"/entries/{a.id}/move", data={"to": "backlog"}).status_code == 200
    assert client.post(f"/entries/{b.id}/move", data={"to": "ongoing"}).status_code == 200
    assert client.post(f"/entries/{c.id}/move", data={"to": "backlog"}).status_code == 200
    day = client.get("/day/2026-10-22")
    assert day.status_code == 200 and "to Backlog" in day.text and "to Ongoing" in day.text
    assert client.get("/day/2026-10-21").status_code == 200
    backlog = client.get("/backlog")
    assert backlog.status_code == 200 and "To backlog" in backlog.text and "2nd day" not in backlog.text
    for url in ("/week/2026-W43?show=all", "/week/2026-W43", "/future"):
        assert client.get(url).status_code == 200
    # ...and back out again onto a day
    with db(path) as conn:
        [x, y] = j.entries_in_list(conn, "backlog")
    client.post(f"/entries/{x.id}/move", data={"to": "date", "on": "2026-10-23"})
    assert client.get("/day/2026-10-23").status_code == 200


def test_backlog_preview_on_todays_page_only(env):
    client, _, _ = env
    for i in range(7):
        client.post("/entries", data={"kind": "task", "text": f"Someday {i}", "target": "l:backlog"})
    today = client.get("/day/2026-10-22").text
    assert "Someday 0" in today and "Someday 4" in today and "Someday 5" not in today
    assert "2 more in the backlog" in today and today.count(">Start<") == 5
    assert "Someday 0" not in client.get("/day/2026-10-23").text
