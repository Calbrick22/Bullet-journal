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
