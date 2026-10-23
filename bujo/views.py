"""What each screen shows, built from the database. No HTML here, no writes."""

from dataclasses import dataclass, field
from datetime import date, timedelta

from . import dates, journal as j
from .journal import Entry

AHEAD_ROWS = 4
NEXT_ROWS = 5          # the day view's preview of the next working day
DAYS_OFF_HORIZON = 120  # how far ahead "Ahead" looks for days off


# --- Formatting -------------------------------------------------------------

def ordinal(n: int) -> str:
    suffix = "th" if 10 < n % 100 < 14 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def short_day(d: date) -> str:          # "Mon 19"
    return f"{d:%a} {d.day}"


def day_month(d: date) -> str:          # "Mon 26 Oct"
    return f"{d:%a} {d.day} {d:%b}"


def long_day(d: date) -> str:           # "Thursday 22 October"
    return f"{d:%A} {d.day} {d:%B}"


def week_label(key: str) -> str:        # "Week 45" (with the year when it isn't this one)
    year, week = dates.parse_week_key(key)
    return f"Week {week}" if year == date.today().year else f"Week {week}, {year}"


def week_range(key: str) -> str:        # "19–23 Oct" or "28 Dec – 1 Jan"
    days = dates.week_dates(key)
    first, last = days[0], days[4]
    if first.month == last.month:
        return f"{first.day}–{last.day} {last:%b}"
    return f"{first.day} {first:%b} – {last.day} {last:%b}"


def where(e: Entry, near: date) -> str:
    """Where an entry lives, as briefly as is clear from `near`."""
    if e.entry_week:
        return week_label(e.entry_week)
    if abs((e.entry_date - near).days) < 7:
        return f"{e.entry_date:%a}"
    return f"{e.entry_date.day} {e.entry_date:%b}"


# --- Entry rows -------------------------------------------------------------

@dataclass
class Row:
    e: Entry
    note: str | None = None             # "to Thu", "planned on 9 Oct"
    trail: list[str] = field(default_factory=list)   # ["Mon", "Tue", "Wed", "Thu"]

    @property
    def carried(self) -> bool:
        return bool(self.trail)

    @property
    def day_count(self) -> str:         # "4th day"
        return f"{ordinal(len(self.trail))} day"


def rows_for(conn, entries: list[Entry], near: date) -> list[Row]:
    copies = j.copies_of(conn, [e.id for e in entries if e.state in ("migrated", "scheduled")])
    sources = j.entries_by_id(conn, [e.moved_from_id for e in entries if e.moved_from_id])
    out = []
    for e in entries:
        row = Row(e)
        if e.id in copies:
            row.note = f"to {where(copies[e.id], near)}"
        elif e.moved_from_id and sources[e.moved_from_id].state == "scheduled":
            src = sources[e.moved_from_id]
            row.note = f"planned on {src.entry_date.day} {src.entry_date:%b}" if src.entry_date else f"planned in {week_label(src.entry_week)}"
        if e.kind == "task" and e.state == "open" and e.carry_count > 0:
            chain = [x for x in j.history(conn, e.id) if x.carry_count <= e.carry_count]
            here = e.entry_date or dates.week_monday(e.entry_week)
            row.trail = [where(x, here) for x in chain]
        out.append(row)
    return out


# --- Shared pieces ----------------------------------------------------------

@dataclass
class AheadItem:
    on: date
    when: str
    row: Row | None = None
    off: str | None = None              # reason, for days off
    days: int = 0


def days_off_after(cal: dates.WorkCalendar, reasons: dict[date, str], start: date, horizon: int) -> list[AheadItem]:
    """Usual working days that are off (bank holidays, leave), grouped into runs."""
    items: list[AheadItem] = []
    last: AheadItem | None = None
    last_day: date | None = None
    for i in range(horizon):
        d = start + timedelta(days=i)
        if d.weekday() not in cal.working_weekdays or cal.is_working_day(d):
            continue
        reason = reasons.get(d) or cal.holiday_name(d) or "Day off"
        # Continue a run across a weekend, but not across a working day.
        if last and last.off == reason and cal.working_days_between(last_day + timedelta(days=1), d) == []:
            last.days += 1
            last.when = f"{last.on.day}–{d.day} {d:%b}" if last.on.month == d.month else f"{last.on.day} {last.on:%b} – {d.day} {d:%b}"
        else:
            last = AheadItem(on=d, when=day_month(d), off=reason, days=1)
            items.append(last)
        last_day = d
    return items


def ahead(conn, cal, week: str, near: date) -> tuple[list[AheadItem], int]:
    entries = j.entries_after(conn, week)
    rows = rows_for(conn, entries, near)
    items = [
        AheadItem(on=r.e.entry_date or dates.week_monday(r.e.entry_week),
                  when=day_month(r.e.entry_date) if r.e.entry_date else week_label(r.e.entry_week), row=r)
        for r in rows
    ]
    start = dates.week_dates(week)[-1] + timedelta(days=1)
    items += days_off_after(cal, j.day_off_reasons(conn), start, DAYS_OFF_HORIZON)
    items.sort(key=lambda a: (a.on, a.row is None))
    return items[:AHEAD_ROWS], max(0, len(items) - AHEAD_ROWS)


def rolling(conn, cal, today: date) -> list[Row]:
    target = dates.carry_over_target(today, cal)
    rows = rows_for(conn, j.entries_for_day(conn, target), target)
    return sorted((r for r in rows if r.carried), key=lambda r: -len(r.trail))


def carried_fact(rows: list[Row]) -> str:
    carried = [r for r in rows if r.carried]
    if not carried:
        return "nothing came over"
    longest = max(len(r.trail) for r in carried)
    if len(carried) == 1:
        return f"1 task came over, on its {ordinal(longest)} day"
    return f"{plural(len(carried), 'task')} came over, one on its {ordinal(longest)} day"


def off_reason(cal, reasons, d: date) -> str | None:
    if cal.is_working_day(d):
        return None
    return reasons.get(d) or cal.holiday_name(d) or ("Day off" if d.weekday() in cal.working_weekdays else None)


# --- Week -------------------------------------------------------------------

@dataclass
class DayCol:
    date: date
    label: str
    is_today: bool
    is_past: bool
    off: str | None
    rows: list[Row]

    @property
    def open_tasks(self) -> int:
        return sum(1 for r in self.rows if r.e.kind == "task" and r.e.state == "open")


def week_view(conn, key: str, today: date) -> dict:
    cal = j.load_calendar(conn)
    reasons = j.day_off_reasons(conn)
    by_day, unplaced = j.entries_for_week(conn, key)
    cols = [
        DayCol(d, short_day(d), d == today, d < today, off_reason(cal, reasons, d), rows_for(conn, es, d))
        for d, es in by_day.items()
        if d.weekday() in cal.working_weekdays or cal.is_working_day(d) or es
    ]
    monday = dates.week_monday(key)
    is_current = key == dates.week_key(today)
    year, number = dates.parse_week_key(key)
    open_total = sum(c.open_tasks for c in cols)

    if is_current:
        target = dates.carry_over_target(today, cal)
        today_rows = rows_for(conn, j.entries_for_day(conn, target), target)
        open_today = sum(1 for r in today_rows if r.e.kind == "task" and r.e.state == "open")
        title = f"{today:%A}, week {number}"
        facts = f"{today.day} {today:%B} · {open_today} open today · {carried_fact(today_rows)}"
    else:
        done = sum(1 for c in cols for r in c.rows if r.e.state == "done")
        title = week_label(key)
        facts = f"{week_range(key)} {year} · {plural(open_total, 'open task')} · {done} done"

    targets = [(f"d:{c.date.isoformat()}", c.label) for c in cols] + [(f"w:{key}", "No day yet")]
    default = f"d:{today.isoformat()}" if any(c.is_today for c in cols) else f"w:{key}"
    ahead_items, ahead_more = ahead(conn, cal, key, today)
    return {
        "key": key, "title": title, "facts": facts, "is_current": is_current,
        "prev_key": dates.shift_week(key, -1), "next_key": dates.shift_week(key, 1),
        "prev_label": week_label(dates.shift_week(key, -1)), "next_label": week_label(dates.shift_week(key, 1)),
        "days": cols, "unplaced": rows_for(conn, unplaced, monday),
        "targets": targets, "default_target": default,
        "ahead": ahead_items, "ahead_more": ahead_more,
        "rolling": rolling(conn, cal, today),
        "phone_title": f"Week {number}",
    }


# --- Day --------------------------------------------------------------------

def day_view(conn, d: date, today: date) -> dict:
    cal = j.load_calendar(conn)
    reasons = j.day_off_reasons(conn)
    rows = rows_for(conn, j.entries_for_day(conn, d), d)
    key = dates.week_key(d)
    _, unplaced = j.entries_for_week(conn, key)
    open_n = sum(1 for r in rows if r.e.kind == "task" and r.e.state == "open")
    done_n = sum(1 for r in rows if r.e.state == "done")
    _, number = dates.parse_week_key(key)
    facts = f"Week {number} · {open_n} open, {done_n} done"
    if d == dates.carry_over_target(today, cal):
        facts += f" · {carried_fact(rows)}"
    off = off_reason(cal, reasons, d)
    if off:
        facts = f"{off} · " + facts
    return {
        "date": d, "title": long_day(d), "facts": facts, "is_today": d == today,
        "week_key": key, "week_label": f"Week {number}",
        "prev_day": cal.previous_working_day(d), "next_day": cal.next_working_day(d),
        "prev_label": short_day(cal.previous_working_day(d)), "next_label": short_day(cal.next_working_day(d)),
        "rows": rows, "unplaced": rows_for(conn, unplaced, d),
        "coming": rows_for(conn, j.entries_for_day(conn, cal.next_working_day(d)), d)[:NEXT_ROWS],
        "coming_more": max(0, len(j.entries_for_day(conn, cal.next_working_day(d))) - NEXT_ROWS),
        "targets": [(f"d:{d.isoformat()}", short_day(d))], "default_target": f"d:{d.isoformat()}",
        "phone_title": short_day(d),
    }
