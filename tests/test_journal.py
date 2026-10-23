from datetime import date

import pytest

from bujo import journal as j
from bujo.db import connect


def d(s: str) -> date:
    return date.fromisoformat(s)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "journal.sqlite")
    yield c
    c.close()


def texts(entries):
    return [e.text for e in entries]


def test_schema_is_versioned_and_reopenable(tmp_path):
    path = tmp_path / "j.sqlite"
    connect(path).close()
    c = connect(path)  # second open must not re-run migrations
    from bujo.db import MIGRATIONS
    assert c.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    c.close()


def test_add_and_read_day(conn):
    j.add_entry(conn, "task", "Write report", on=d("2026-10-22"))
    j.add_entry(conn, "note", "Ask about budget", on=d("2026-10-22"))
    j.add_entry(conn, "event", "Team lunch", on=d("2026-10-22"))
    entries = j.entries_for_day(conn, d("2026-10-22"))
    assert texts(entries) == ["Write report", "Ask about budget", "Team lunch"]
    assert [e.signifier for e in entries] == ["•", "–", "○"]


def test_add_validation(conn):
    with pytest.raises(j.JournalError):
        j.add_entry(conn, "task", "   ", on=d("2026-10-22"))
    with pytest.raises(j.JournalError):
        j.add_entry(conn, "task", "x")  # no location
    with pytest.raises(j.JournalError):
        j.add_entry(conn, "task", "x", on=d("2026-10-22"), week="2026-W43")
    with pytest.raises(ValueError):
        j.add_entry(conn, "task", "x", week="2025-W53")
    with pytest.raises(j.JournalError):
        j.add_entry(conn, "idea", "x", on=d("2026-10-22"))


def test_state_changes(conn):
    t = j.add_entry(conn, "task", "Call Sam", on=d("2026-10-22"))
    done = j.mark_done(conn, t.id)
    assert done.state == "done" and done.signifier == "×" and done.completed_at
    assert j.reopen(conn, t.id).state == "open"
    assert j.cancel(conn, t.id).state == "cancelled"
    with pytest.raises(j.JournalError):
        j.mark_done(conn, t.id)  # cancelled must be reopened first
    note = j.add_entry(conn, "note", "n", on=d("2026-10-22"))
    with pytest.raises(j.JournalError):
        j.mark_done(conn, note.id)


def test_week_view_includes_unassigned(conn):
    j.add_entry(conn, "task", "Mon thing", on=d("2026-10-19"))
    j.add_entry(conn, "task", "Sun thing", on=d("2026-10-25"))
    j.add_entry(conn, "task", "Sometime this week", week="2026-W43")
    j.add_entry(conn, "task", "Next week", on=d("2026-10-26"))
    by_day, unassigned = j.entries_for_week(conn, "2026-W43")
    assert len(by_day) == 7
    assert texts(by_day[d("2026-10-19")]) == ["Mon thing"]
    assert texts(by_day[d("2026-10-25")]) == ["Sun thing"]
    assert texts(unassigned) == ["Sometime this week"]


def test_week_53_spans_new_year(conn):
    j.add_entry(conn, "task", "NYE", on=d("2026-12-31"))
    j.add_entry(conn, "task", "Jan 2", on=d("2027-01-02"))
    by_day, _ = j.entries_for_week(conn, "2026-W53")
    assert texts(by_day[d("2026-12-31")]) == ["NYE"]
    assert texts(by_day[d("2027-01-02")]) == ["Jan 2"]


# --- Moving and scheduling --------------------------------------------------

def test_schedule_to_future_date_keeps_history(conn):
    t = j.add_entry(conn, "task", "Book dentist", on=d("2026-10-22"))
    copy = j.move_task(conn, t.id, on=d("2026-11-05"), today=d("2026-10-22"))
    orig = j.get_entry(conn, t.id)
    assert orig.state == "scheduled" and orig.signifier == "<"
    assert copy.entry_date == d("2026-11-05") and copy.state == "open"
    assert copy.moved_from_id == t.id and j.moved_to(conn, t.id).id == copy.id
    assert copy.carry_count == 0  # scheduling ahead isn't a rollover


def test_schedule_to_future_week_then_assign_day(conn):
    t = j.add_entry(conn, "task", "Plan offsite", on=d("2026-10-22"))
    in_week = j.move_task(conn, t.id, week="2026-W46", today=d("2026-10-22"))
    _, unassigned = j.entries_for_week(conn, "2026-W46")
    assert texts(unassigned) == ["Plan offsite"]
    # Giving it a day within that week places it: same entry, no extra history
    on_day = j.move_task(conn, in_week.id, on=d("2026-11-11"), today=d("2026-11-09"))
    assert on_day.id == in_week.id and on_day.entry_date == d("2026-11-11")
    assert on_day.entry_week is None and on_day.state == "open"
    assert len(j.history(conn, on_day.id)) == 2
    _, unassigned = j.entries_for_week(conn, "2026-W46")
    assert unassigned == []
    # Moving it to a day in a *different* week is a real move
    later = j.move_task(conn, on_day.id, on=d("2026-11-20"), today=d("2026-11-11"))
    assert j.get_entry(conn, on_day.id).state == "scheduled" and later.id != on_day.id


def test_cannot_move_closed_or_non_task(conn):
    t = j.add_entry(conn, "task", "x", on=d("2026-10-22"))
    j.mark_done(conn, t.id)
    with pytest.raises(j.JournalError):
        j.move_task(conn, t.id, on=d("2026-10-23"))
    n = j.add_entry(conn, "note", "n", on=d("2026-10-22"))
    with pytest.raises(j.JournalError):
        j.move_task(conn, n.id, on=d("2026-10-23"))
    t2 = j.add_entry(conn, "task", "y", on=d("2026-10-22"))
    with pytest.raises(j.JournalError):
        j.move_task(conn, t2.id, on=d("2026-10-22"))


# --- Carry-over -------------------------------------------------------------

def test_carry_over_basic(conn):
    j.add_entry(conn, "task", "Open task", on=d("2026-10-21"))
    done = j.add_entry(conn, "task", "Done task", on=d("2026-10-21"))
    j.mark_done(conn, done.id)
    j.add_entry(conn, "note", "A note", on=d("2026-10-21"))
    j.add_entry(conn, "event", "An event", on=d("2026-10-21"))
    moved = j.carry_over(conn, today=d("2026-10-22"))
    assert texts(moved) == ["Open task"]
    assert texts(j.entries_for_day(conn, d("2026-10-22"))) == ["Open task"]
    yesterday = {e.text: e for e in j.entries_for_day(conn, d("2026-10-21"))}
    assert yesterday["Open task"].state == "migrated"
    assert yesterday["Open task"].signifier == ">"
    assert yesterday["Done task"].state == "done"


def test_carry_over_is_idempotent(conn):
    j.add_entry(conn, "task", "Once only", on=d("2026-10-21"))
    assert len(j.carry_over(conn, today=d("2026-10-22"))) == 1
    assert j.carry_over(conn, today=d("2026-10-22")) == []
    assert j.carry_over(conn, today=d("2026-10-22")) == []
    assert texts(j.entries_for_day(conn, d("2026-10-22"))) == ["Once only"]
    total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    assert total == 2


def test_carry_over_friday_to_monday(conn):
    j.add_entry(conn, "task", "Friday task", on=d("2026-10-23"))
    assert j.carry_over(conn, today=d("2026-10-24")) == []  # Saturday: nothing moves
    assert j.carry_over(conn, today=d("2026-10-25")) == []  # Sunday
    moved = j.carry_over(conn, today=d("2026-10-26"))
    assert [e.entry_date for e in moved] == [d("2026-10-26")]


def test_carry_over_skips_bank_holiday(conn):
    j.add_entry(conn, "task", "Before Easter", on=d("2026-04-02"))
    assert j.carry_over(conn, today=d("2026-04-03")) == []  # Good Friday
    assert j.carry_over(conn, today=d("2026-04-06")) == []  # Easter Monday
    moved = j.carry_over(conn, today=d("2026-04-07"))
    assert moved[0].entry_date == d("2026-04-07")


def test_carry_over_after_long_gap_is_one_hop(conn):
    j.add_entry(conn, "task", "Old A", on=d("2026-10-12"))
    j.add_entry(conn, "task", "Old B", on=d("2026-10-14"))
    j.add_entry(conn, "task", "Old C", on=d("2026-10-16"))
    moved = j.carry_over(conn, today=d("2026-10-22"))  # app not opened for a week
    assert texts(moved) == ["Old A", "Old B", "Old C"]  # oldest first
    assert all(e.entry_date == d("2026-10-22") and e.carry_count == 1 for e in moved)
    assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 6


def test_carry_over_across_year_boundary_and_week_53(conn):
    j.add_entry(conn, "task", "Year end", on=d("2026-12-31"))
    j.add_entry(conn, "task", "Week 53 sometime", week="2026-W53")
    assert j.carry_over(conn, today=d("2027-01-01")) == []  # New Year's Day
    moved = j.carry_over(conn, today=d("2027-01-04"))
    assert sorted(texts(moved)) == ["Week 53 sometime", "Year end"]
    assert all(e.entry_date == d("2027-01-04") for e in moved)


def test_carry_over_respects_annual_leave(conn):
    j.add_entry(conn, "task", "Before leave", on=d("2026-10-23"))
    for day in ("2026-10-26", "2026-10-27", "2026-10-28"):
        j.set_day_override(conn, d(day), working=False, reason="Annual leave")
    assert j.carry_over(conn, today=d("2026-10-27")) == []
    assert j.carry_over(conn, today=d("2026-10-29"))[0].entry_date == d("2026-10-29")


def test_rollover_count_and_history(conn):
    t = j.add_entry(conn, "task", "Procrastinated", on=d("2026-10-19"))
    for today in ("2026-10-20", "2026-10-21", "2026-10-22"):
        j.carry_over(conn, today=d(today))
    chain = j.history(conn, t.id)
    assert [e.entry_date for e in chain] == [d("2026-10-19"), d("2026-10-20"), d("2026-10-21"), d("2026-10-22")]
    assert [e.state for e in chain] == ["migrated", "migrated", "migrated", "open"]
    assert chain[-1].carry_count == 3
    assert all(e.origin_id == t.id for e in chain[1:])


def test_future_and_current_week_items_untouched(conn):
    j.add_entry(conn, "task", "Future", on=d("2026-11-02"))
    j.add_entry(conn, "task", "This week, no day", week="2026-W43")
    assert j.carry_over(conn, today=d("2026-10-22")) == []


def test_working_weekday_setting(conn):
    j.set_working_weekdays(conn, {0, 1, 2, 3})  # Mon-Thu
    j.add_entry(conn, "task", "Thursday", on=d("2026-10-22"))
    assert j.carry_over(conn, today=d("2026-10-23")) == []  # Friday now a day off
    assert len(j.carry_over(conn, today=d("2026-10-26"))) == 1
    with pytest.raises(j.JournalError):
        j.set_working_weekdays(conn, set())


def test_unique_link_blocks_duplicate_copies(conn):
    """Belt and braces: even a buggy caller can't make two copies of one entry."""
    import sqlite3
    t = j.add_entry(conn, "task", "x", on=d("2026-10-21"))
    j.carry_over(conn, today=d("2026-10-22"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO entries (kind, text, entry_date, moved_from_id, created_at, updated_at) "
            "VALUES ('task', 'x', '2026-10-22', ?, 'now', 'now')", (t.id,),
        )


# --- Moving forward (">") and editing ----------------------------------------

def test_forward_from_today_goes_to_next_working_day(conn):
    t = j.add_entry(conn, "task", "Fri task", on=d("2026-10-23"))
    copy = j.move_forward(conn, t.id, today=d("2026-10-23"))
    assert copy.entry_date == d("2026-10-26")                 # over the weekend
    assert j.get_entry(conn, t.id).state == "migrated"        # ">" is always a migration
    assert copy.carry_count == 1


def test_forward_skips_bank_holiday(conn):
    t = j.add_entry(conn, "task", "Before Christmas", on=d("2026-12-24"))
    assert j.move_forward(conn, t.id, today=d("2026-12-24")).entry_date == d("2026-12-29")


def test_forward_of_a_past_task_lands_today(conn):
    t = j.add_entry(conn, "task", "Old", on=d("2026-10-19"))
    copy = j.move_forward(conn, t.id, today=d("2026-10-22"))
    assert copy.entry_date == d("2026-10-22") and copy.carry_count == 1
    assert j.get_entry(conn, t.id).state == "migrated"


def test_forward_of_week_task_goes_to_next_week(conn):
    t = j.add_entry(conn, "task", "Sometime", week="2026-W53")
    assert j.move_forward(conn, t.id, today=d("2026-12-29")).entry_week == "2027-W01"


def test_edit_text(conn):
    t = j.add_entry(conn, "task", "Typo here", on=d("2026-10-22"))
    assert j.edit_text(conn, t.id, "  Fixed  ").text == "Fixed"
    with pytest.raises(j.JournalError):
        j.edit_text(conn, t.id, " ")
    j.move_forward(conn, t.id, today=d("2026-10-22"))
    with pytest.raises(j.JournalError):
        j.edit_text(conn, t.id, "Rewrite history")


# --- Backlog and ongoing lists ------------------------------------------------

def test_add_to_lists_tasks_only(conn):
    b = j.add_entry(conn, "task", "Tidy the wiki", lst="backlog")
    o = j.add_entry(conn, "task", "Q4 budget model", lst="ongoing")
    assert (b.entry_list, b.entry_date, b.entry_week) == ("backlog", None, None)
    assert [e.text for e in j.entries_in_list(conn, "ongoing")] == ["Q4 budget model"]
    assert j.count_in_list(conn, "backlog") == 1
    with pytest.raises(j.JournalError):
        j.add_entry(conn, "note", "Notes don't go on lists", lst="backlog")
    with pytest.raises(j.JournalError):
        j.add_entry(conn, "task", "x", lst="someday")
    with pytest.raises(j.JournalError):
        j.add_entry(conn, "task", "x", on=d("2026-10-22"), lst="backlog")


def test_lists_never_carry_over(conn):
    j.add_entry(conn, "task", "Backlog item", lst="backlog")
    j.add_entry(conn, "task", "Ongoing item", lst="ongoing")
    assert j.carry_over(conn, today=d("2026-10-22")) == []
    assert j.entries_after(conn, "2026-W43") == []


def test_pull_from_backlog_moves_in_place(conn):
    b = j.add_entry(conn, "task", "Tidy the wiki", lst="backlog")
    o = j.move_task(conn, b.id, lst="ongoing", today=d("2026-10-22"))
    assert o.id == b.id and o.entry_list == "ongoing"
    t = j.move_task(conn, b.id, on=d("2026-10-22"), today=d("2026-10-22"))
    assert t.id == b.id and t.entry_date == d("2026-10-22") and t.entry_list is None
    assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 1


def test_day_task_to_backlog_leaves_a_migrated_original(conn):
    t = j.add_entry(conn, "task", "Not this week", on=d("2026-10-22"))
    copy = j.move_task(conn, t.id, lst="backlog", today=d("2026-10-22"))
    assert copy.entry_list == "backlog" and copy.moved_from_id == t.id
    assert j.get_entry(conn, t.id).state == "migrated"


def test_forward_from_a_list_goes_to_the_current_working_day(conn):
    o = j.add_entry(conn, "task", "Ongoing", lst="ongoing")
    assert j.move_forward(conn, o.id, today=d("2026-10-24")).entry_date == d("2026-10-23")  # Sat -> Fri


def test_done_ongoing_tasks_stay_visible_for_a_while(conn):
    from datetime import datetime, timezone
    o = j.add_entry(conn, "task", "Finish me", lst="ongoing")
    j.mark_done(conn, o.id)
    assert j.entries_in_list(conn, "ongoing") == []
    assert len(j.entries_in_list(conn, "ongoing", done_since=datetime(2000, 1, 1, tzinfo=timezone.utc))) == 1


def test_upgrade_keeps_entries_and_links(tmp_path):
    """A journal made before lists existed upgrades without losing anything."""
    import sqlite3
    from bujo import db
    path = tmp_path / "old.sqlite"
    raw = sqlite3.connect(path, isolation_level=None)
    for sql in db.MIGRATIONS[:2]:
        raw.executescript(sql)
    raw.execute("PRAGMA user_version = 2")
    raw.execute("INSERT INTO entries (id, kind, text, state, entry_date, created_at, updated_at) "
                "VALUES (1, 'task', 'Old', 'migrated', '2026-10-21', '2026-10-21T09:00:00+00:00', '2026-10-21T09:00:00+00:00')")
    raw.execute("INSERT INTO entries (id, kind, text, state, entry_date, moved_from_id, origin_id, carry_count, "
                "created_at, updated_at) VALUES (2, 'task', 'Old', 'open', '2026-10-22', 1, 1, 1, '2026-10-21T09:00:00+00:00', '2026-10-21T09:00:00+00:00')")
    raw.execute("INSERT INTO entries (id, kind, text, entry_week, created_at, updated_at) "
                "VALUES (3, 'note', 'Week note', '2026-W43', '2026-10-21T09:00:00+00:00', '2026-10-21T09:00:00+00:00')")
    raw.close()
    c = connect(path)
    assert c.execute("PRAGMA user_version").fetchone()[0] == len(db.MIGRATIONS)
    assert [e.text for e in j.history(c, 2)] == ["Old", "Old"]
    assert j.moved_to(c, 1).id == 2
    assert j.entries_for_week(c, "2026-W43")[1][0].text == "Week note"
    assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    c.close()
