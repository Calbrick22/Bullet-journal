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
    assert c.execute("PRAGMA user_version").fetchone()[0] == 1
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
