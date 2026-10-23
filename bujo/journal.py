"""Journal operations: entries, state changes, moving, and carry-over.

Date decisions come from `dates`; this module only reads and writes SQLite.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from . import dates
from .db import transaction

KINDS = ("task", "event", "note")
SIGNIFIERS = {
    ("task", "open"): "•",
    ("task", "done"): "×",
    ("task", "migrated"): ">",
    ("task", "scheduled"): "<",
    ("task", "cancelled"): "•",  # shown struck through
    ("event", "open"): "○",
    ("note", "open"): "–",
}


@dataclass(frozen=True)
class Entry:
    id: int
    kind: str
    text: str
    state: str
    entry_date: date | None
    entry_week: str | None
    position: int
    moved_from_id: int | None
    origin_id: int | None
    carry_count: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    @property
    def signifier(self) -> str:
        return SIGNIFIERS.get((self.kind, self.state), SIGNIFIERS[(self.kind, "open")])

    @property
    def week(self) -> str:
        return self.entry_week or dates.week_key(self.entry_date)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Entry":
        opt_dt = lambda v: datetime.fromisoformat(v) if v else None
        return cls(
            id=row["id"],
            kind=row["kind"],
            text=row["text"],
            state=row["state"],
            entry_date=date.fromisoformat(row["entry_date"]) if row["entry_date"] else None,
            entry_week=row["entry_week"],
            position=row["position"],
            moved_from_id=row["moved_from_id"],
            origin_id=row["origin_id"],
            carry_count=row["carry_count"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            completed_at=opt_dt(row["completed_at"]),
        )


class JournalError(ValueError):
    pass


def _now() -> str:
    return dates.utc_now().isoformat(timespec="seconds")


def _location(on: date | None, week: str | None) -> tuple[str | None, str | None]:
    if (on is None) == (week is None):
        raise JournalError("Give exactly one of a date or a week")
    if week is not None:
        dates.parse_week_key(week)
    return (on.isoformat() if on else None), week


def _next_position(conn, on: str | None, week: str | None) -> int:
    col, val = ("entry_date", on) if on else ("entry_week", week)
    row = conn.execute(
        f"SELECT COALESCE(MAX(position), -1) + 1 FROM entries WHERE {col} = ?", (val,)
    ).fetchone()
    return row[0]


# --- Reading ----------------------------------------------------------------

def get_entry(conn, entry_id: int) -> Entry:
    row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise JournalError(f"No entry {entry_id}")
    return Entry.from_row(row)


def entries_for_day(conn, d: date) -> list[Entry]:
    rows = conn.execute(
        "SELECT * FROM entries WHERE entry_date = ? ORDER BY position, id", (d.isoformat(),)
    )
    return [Entry.from_row(r) for r in rows]


def entries_for_week(conn, week: str) -> tuple[dict[date, list[Entry]], list[Entry]]:
    """Entries in a week: ({day: entries} for all 7 days, week-only entries)."""
    days = dates.week_dates(week)
    by_day: dict[date, list[Entry]] = {d: [] for d in days}
    rows = conn.execute(
        "SELECT * FROM entries WHERE entry_date BETWEEN ? AND ? ORDER BY entry_date, position, id",
        (days[0].isoformat(), days[-1].isoformat()),
    )
    for r in rows:
        e = Entry.from_row(r)
        by_day[e.entry_date].append(e)
    unassigned = [
        Entry.from_row(r)
        for r in conn.execute(
            "SELECT * FROM entries WHERE entry_week = ? ORDER BY position, id", (week,)
        )
    ]
    return by_day, unassigned


def history(conn, entry_id: int) -> list[Entry]:
    """Every entry in a task's migration chain, oldest first."""
    e = get_entry(conn, entry_id)
    origin = e.origin_id or e.id
    rows = conn.execute(
        "SELECT * FROM entries WHERE id = ? OR origin_id = ? ORDER BY carry_count, id",
        (origin, origin),
    )
    return [Entry.from_row(r) for r in rows]


def moved_to(conn, entry_id: int) -> Entry | None:
    row = conn.execute("SELECT * FROM entries WHERE moved_from_id = ?", (entry_id,)).fetchone()
    return Entry.from_row(row) if row else None


def copies_of(conn, ids: list[int]) -> dict[int, Entry]:
    """{original id: the copy it was moved to}, for many entries at once."""
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = conn.execute(f"SELECT * FROM entries WHERE moved_from_id IN ({marks})", ids)
    return {r["moved_from_id"]: Entry.from_row(r) for r in rows}


def entries_by_id(conn, ids: list[int]) -> dict[int, Entry]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = conn.execute(f"SELECT * FROM entries WHERE id IN ({marks})", ids)
    return {r["id"]: Entry.from_row(r) for r in rows}


def entries_after(conn, week: str) -> list[Entry]:
    """Open entries after a week: dated later, or parked in a later week.
    Sorted by date (a week-only entry sorts on its week's Monday)."""
    last_day = dates.week_dates(week)[-1].isoformat()
    rows = conn.execute(
        """SELECT * FROM entries WHERE state = 'open'
           AND (entry_date > ? OR (entry_week IS NOT NULL AND entry_week > ?))""",
        (last_day, week),
    )
    out = [Entry.from_row(r) for r in rows]
    out.sort(key=lambda e: (e.entry_date or dates.week_monday(e.entry_week), e.entry_week is None, e.position, e.id))
    return out


def day_off_reasons(conn) -> dict[date, str]:
    rows = conn.execute("SELECT date, reason FROM day_overrides WHERE working = 0")
    return {date.fromisoformat(r["date"]): r["reason"] for r in rows}


# --- Writing ----------------------------------------------------------------

def add_entry(conn, kind: str, text: str, on: date | None = None, week: str | None = None) -> Entry:
    if kind not in KINDS:
        raise JournalError(f"Unknown kind {kind!r}")
    text = text.strip()
    if not text:
        raise JournalError("Entry text is empty")
    on_s, week_s = _location(on, week)
    now = _now()
    with transaction(conn):
        cur = conn.execute(
            """INSERT INTO entries (kind, text, entry_date, entry_week, position, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (kind, text, on_s, week_s, _next_position(conn, on_s, week_s), now, now),
        )
    return get_entry(conn, cur.lastrowid)


def edit_text(conn, entry_id: int, text: str) -> Entry:
    text = text.strip()
    if not text:
        raise JournalError("Entry text is empty")
    conn.execute(
        "UPDATE entries SET text = ?, updated_at = ? WHERE id = ?", (text, _now(), entry_id)
    )
    return get_entry(conn, entry_id)


def _set_state(conn, entry_id: int, new: str, allowed_from: tuple[str, ...]) -> Entry:
    e = get_entry(conn, entry_id)
    if e.kind != "task":
        raise JournalError("Only tasks have states")
    if e.state not in allowed_from:
        raise JournalError(f"Can't change a {e.state} task to {new}")
    now = _now()
    conn.execute(
        "UPDATE entries SET state = ?, updated_at = ?, completed_at = ? WHERE id = ?",
        (new, now, now if new == "done" else None, entry_id),
    )
    return get_entry(conn, entry_id)


def mark_done(conn, entry_id: int) -> Entry:
    return _set_state(conn, entry_id, "done", ("open",))


def cancel(conn, entry_id: int) -> Entry:
    return _set_state(conn, entry_id, "cancelled", ("open",))


def reopen(conn, entry_id: int) -> Entry:
    """Undo done/cancelled. Migrated/scheduled entries are history: act on the copy."""
    return _set_state(conn, entry_id, "open", ("done", "cancelled"))


def _move(conn, e: Entry, state: str, on_s: str | None, week_s: str | None, now: str) -> int:
    conn.execute(
        "UPDATE entries SET state = ?, updated_at = ? WHERE id = ?", (state, now, e.id)
    )
    cur = conn.execute(
        """INSERT INTO entries (kind, text, entry_date, entry_week, position,
                                moved_from_id, origin_id, carry_count, created_at, updated_at)
           VALUES ('task', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            e.text, on_s, week_s, _next_position(conn, on_s, week_s),
            e.id, e.origin_id or e.id,
            e.carry_count + (1 if state == "migrated" else 0),
            now, now,
        ),
    )
    return cur.lastrowid


def move_task(conn, entry_id: int, on: date | None = None, week: str | None = None,
              today: date | None = None) -> Entry:
    """Move an open task elsewhere, keeping history.

    Moving to a later date or week than today's marks the original
    scheduled (<); anything else is a migration (>). Returns the new copy.
    """
    e = get_entry(conn, entry_id)
    if e.kind != "task" or e.state != "open":
        raise JournalError("Only open tasks can be moved")
    on_s, week_s = _location(on, week)
    if (on_s, week_s) == (e.entry_date and e.entry_date.isoformat(), e.entry_week):
        raise JournalError("Task is already there")
    if e.entry_week and on and dates.week_key(on) == e.entry_week:
        # Giving a week-only task a day in its own week just places it.
        conn.execute(
            "UPDATE entries SET entry_date = ?, entry_week = NULL, position = ?, updated_at = ? WHERE id = ?",
            (on_s, _next_position(conn, on_s, None), _now(), e.id),
        )
        return get_entry(conn, e.id)
    today = today or dates.local_today()
    future = (on > today) if on else (dates.week_monday(week) > dates.week_monday(dates.week_key(today)))
    with transaction(conn):
        new_id = _move(conn, e, "scheduled" if future else "migrated", on_s, week_s, _now())
    return get_entry(conn, new_id)


def carry_over(conn, today: date | None = None, cal: dates.WorkCalendar | None = None) -> list[Entry]:
    """Migrate every overdue open task to the current working day.

    Safe to call on every page load: migrated originals are no longer open,
    and moved_from_id is UNIQUE, so a second run finds nothing to do.
    Gaps are handled in one hop (a task from last Tuesday goes straight to
    today, counted as one migration). Returns the new copies.
    """
    today = today or dates.local_today()
    cal = cal or load_calendar(conn)
    target = dates.carry_over_target(today, cal)
    now = _now()
    with transaction(conn):
        rows = conn.execute(
            """SELECT * FROM entries
               WHERE kind = 'task' AND state = 'open'
                 AND (entry_date < ? OR entry_week IS NOT NULL)""",
            (target.isoformat(),),
        ).fetchall()
        overdue = [
            e for e in map(Entry.from_row, rows)
            if dates.is_overdue(e.entry_date, e.entry_week, target)
        ]
        overdue.sort(key=lambda e: (e.entry_date or dates.week_monday(e.entry_week), e.position, e.id))
        new_ids = [_move(conn, e, "migrated", target.isoformat(), None, now) for e in overdue]
    return [get_entry(conn, i) for i in new_ids]


# --- Working-day settings ---------------------------------------------------

def load_calendar(conn) -> dates.WorkCalendar:
    row = conn.execute("SELECT value FROM settings WHERE key = 'working_weekdays'").fetchone()
    weekdays = frozenset(json.loads(row[0])) if row else dates.WorkCalendar().working_weekdays
    off, on = set(), set()
    for r in conn.execute("SELECT date, working FROM day_overrides"):
        (on if r["working"] else off).add(date.fromisoformat(r["date"]))
    return dates.WorkCalendar(
        working_weekdays=weekdays, non_working=frozenset(off), extra_working=frozenset(on)
    )


def set_working_weekdays(conn, weekdays: set[int]) -> None:
    if not weekdays or not weekdays <= set(range(7)):
        raise JournalError("Working weekdays must be a non-empty set of 0-6")
    conn.execute(
        "INSERT INTO settings (key, value) VALUES ('working_weekdays', ?) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (json.dumps(sorted(weekdays)),),
    )


def set_day_override(conn, d: date, working: bool, reason: str = "") -> None:
    """Mark a date as a day off (leave) or as a working day (e.g. worked a holiday)."""
    conn.execute(
        "INSERT INTO day_overrides (date, working, reason) VALUES (?, ?, ?) "
        "ON CONFLICT (date) DO UPDATE SET working = excluded.working, reason = excluded.reason",
        (d.isoformat(), int(working), reason),
    )


def clear_day_override(conn, d: date) -> None:
    conn.execute("DELETE FROM day_overrides WHERE date = ?", (d.isoformat(),))
