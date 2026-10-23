import re
from datetime import date

import pytest
from fastapi.testclient import TestClient

from bujo import journal as j
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
    html = client.get("/week/2026-W43").text
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
    html = client.get("/week/2026-W43").text
    assert f'id="t{e.id}" type="submit" role="checkbox" aria-checked="false"' in html

    client.post(f"/entries/{e.id}/done", data={"next": "/week/2026-W43"})
    html = client.get("/week/2026-W43").text
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
    html = client.get("/week/2026-W44").text
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
