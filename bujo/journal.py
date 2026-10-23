"""Journal operations: entries, state changes, moving, and carry-over.

Date decisions come from `dates`; this module only reads and writes SQLite.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

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
    entry_list: str | None          # "backlog" or "ongoing": no day or week
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
    def week(self) -> str | None:
        if self.entry_list:
            return None
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
            entry_list=row["entry_list"],
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


LISTS = ("backlog", "ongoing")


def _location(on: date | None, week: str | None, lst: str | None = None) -> tuple[str | None, str | None, str | None]:
    if (on is not None) + (week is not None) + (lst is not None) != 1:
        raise JournalError("Give exactly one of a date, a week or a list")
    if week is not None:
        dates.parse_week_key(week)
    if lst is not None and lst not in LISTS:
        raise JournalError(f"Unknown list {lst!r}")
    return (on.isoformat() if on else None), week, lst


def _next_position(conn, on: str | None, week: str | None, lst: str | None = None) -> int:
    col, val = ("entry_date", on) if on else ("entry_week", week) if week else ("entry_list", lst)
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


def entries_in_list(conn, lst: str, done_since: datetime | None = None) -> list[Entry]:
    """Open entries on a list, plus any finished since `done_since` (so a
    ticked task stays visible for a while instead of vanishing)."""
    rows = conn.execute(
        """SELECT * FROM entries WHERE entry_list = ?
           AND (state = 'open' OR (state = 'done' AND completed_at >= ?))
           ORDER BY position, id""",
        (lst, done_since.isoformat(timespec="seconds") if done_since else "9999"),
    )
    return [Entry.from_row(r) for r in rows]


def finished_from_lists(conn, since: datetime, limit: int = 8) -> list[Entry]:
    """Backlog and ongoing tasks ticked off since a time, newest first."""
    rows = conn.execute(
        """SELECT * FROM entries WHERE entry_list IS NOT NULL AND state = 'done' AND completed_at >= ?
           ORDER BY completed_at DESC LIMIT ?""",
        (since.isoformat(timespec="seconds"), limit),
    )
    return [Entry.from_row(r) for r in rows]


def count_in_list(conn, lst: str) -> int:
    return conn.execute("SELECT COUNT(*) FROM entries WHERE entry_list = ? AND state = 'open'", (lst,)).fetchone()[0]


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

def add_entry(conn, kind: str, text: str, on: date | None = None, week: str | None = None,
              lst: str | None = None) -> Entry:
    if kind not in KINDS:
        raise JournalError(f"Unknown kind {kind!r}")
    text = text.strip()
    if not text:
        raise JournalError("Entry text is empty")
    on_s, week_s, lst = _location(on, week, lst)
    if lst and kind != "task":
        raise JournalError("Only tasks go on the backlog or ongoing list")
    now = _now()
    with transaction(conn):
        cur = conn.execute(
            """INSERT INTO entries (kind, text, entry_date, entry_week, entry_list, position, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (kind, text, on_s, week_s, lst, _next_position(conn, on_s, week_s, lst), now, now),
        )
    return get_entry(conn, cur.lastrowid)


def edit_text(conn, entry_id: int, text: str) -> Entry:
    """Fix an entry's wording. Migrated/scheduled entries are history: edit the copy."""
    text = text.strip()
    if not text:
        raise JournalError("Entry text is empty")
    if get_entry(conn, entry_id).state in ("migrated", "scheduled"):
        raise JournalError("This entry has moved on; edit the newer copy")
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


def _move(conn, e: Entry, state: str, on_s: str | None, week_s: str | None, now: str,
          lst: str | None = None) -> int:
    conn.execute(
        "UPDATE entries SET state = ?, updated_at = ? WHERE id = ?", (state, now, e.id)
    )
    cur = conn.execute(
        """INSERT INTO entries (kind, text, entry_date, entry_week, entry_list, position,
                                moved_from_id, origin_id, carry_count, created_at, updated_at)
           VALUES ('task', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            e.text, on_s, week_s, lst, _next_position(conn, on_s, week_s, lst),
            e.id, e.origin_id or e.id,
            e.carry_count + (1 if state == "migrated" else 0),
            now, now,
        ),
    )
    return cur.lastrowid


def move_task(conn, entry_id: int, on: date | None = None, week: str | None = None,
              today: date | None = None, mark: str | None = None, lst: str | None = None) -> Entry:
    """Move an open task elsewhere, keeping history.

    Moving to a later date or week than today's marks the original
    scheduled (<); anything else is a migration (>). `mark` forces one
    ("migrated" for `>`). Returns the new copy.

    The backlog and ongoing lists aren't a log, so a task leaving one of
    them is simply relocated (same entry, no copy). A task moving from a day
    or week onto a list leaves a migrated (>) original behind as usual.
    """
    e = get_entry(conn, entry_id)
    if e.kind != "task" or e.state != "open":
        raise JournalError("Only open tasks can be moved")
    on_s, week_s, lst = _location(on, week, lst)
    if (on_s, week_s, lst) == (e.entry_date and e.entry_date.isoformat(), e.entry_week, e.entry_list):
        raise JournalError("Task is already there")
    if e.entry_list:
        conn.execute(
            "UPDATE entries SET entry_date = ?, entry_week = ?, entry_list = ?, position = ?, updated_at = ? WHERE id = ?",
            (on_s, week_s, lst, _next_position(conn, on_s, week_s, lst), _now(), e.id),
        )
        return get_entry(conn, e.id)
    if lst:
        with transaction(conn):
            new_id = _move(conn, e, "migrated", None, None, _now(), lst)
        return get_entry(conn, new_id)
    if e.entry_week and on and dates.week_key(on) == e.entry_week:
        # Giving a week-only task a day in its own week just places it.
        conn.execute(
            "UPDATE entries SET entry_date = ?, entry_week = NULL, position = ?, updated_at = ? WHERE id = ?",
            (on_s, _next_position(conn, on_s, None), _now(), e.id),
        )
        return get_entry(conn, e.id)
    today = today or dates.local_today()
    future = (on > today) if on else (dates.week_monday(week) > dates.week_monday(dates.week_key(today)))
    if mark not in (None, "migrated", "scheduled"):
        raise JournalError(f"Unknown mark {mark!r}")
    with transaction(conn):
        new_id = _move(conn, e, mark or ("scheduled" if future else "migrated"), on_s, week_s, _now())
    return get_entry(conn, new_id)


def forward_target(e: Entry, today: date, cal: dates.WorkCalendar) -> tuple[date | None, str | None]:
    """Where `>` sends a task: one step forward.

    A week-only task goes to the next week. A dated task goes to the next
    working day after its date, or to the current working day if it's
    already in the past.
    """
    current = dates.carry_over_target(today, cal)
    if e.entry_list:
        return current, None
    if e.entry_week:
        return None, dates.shift_week(e.entry_week, 1)
    if e.entry_date < current:
        return current, None
    return cal.next_working_day(e.entry_date), None


def move_forward(conn, entry_id: int, today: date | None = None, cal: dates.WorkCalendar | None = None) -> Entry:
    today = today or dates.local_today()
    cal = cal or load_calendar(conn)
    on, week = forward_target(get_entry(conn, entry_id), today, cal)
    return move_task(conn, entry_id, on=on, week=week, today=today, mark="migrated")


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


def add_leave(conn, start: date, end: date, reason: str = "Annual leave") -> int:
    """Mark a run of days off. Only usual working days are recorded (a week of
    leave doesn't need its weekend). Returns how many days were added."""
    if end < start:
        raise JournalError("The last day is before the first")
    if (end - start).days > 366:
        raise JournalError("That's more than a year of leave")
    reason = " ".join(reason.split()) or "Day off"
    weekdays = load_calendar(conn).working_weekdays
    n = 0
    with transaction(conn):
        d = start
        while d <= end:
            if d.weekday() in weekdays:
                conn.execute(
                    "INSERT INTO day_overrides (date, working, reason) VALUES (?, 0, ?) "
                    "ON CONFLICT (date) DO UPDATE SET working = 0, reason = excluded.reason",
                    (d.isoformat(), reason),
                )
                n += 1
            d += timedelta(days=1)
    return n


def remove_leave(conn, start: date, end: date) -> None:
    conn.execute("DELETE FROM day_overrides WHERE working = 0 AND date BETWEEN ? AND ?",
                 (start.isoformat(), end.isoformat()))
