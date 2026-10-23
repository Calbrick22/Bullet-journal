"""What each screen shows, built from the database. No HTML here, no writes."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import backup, calendar as calmod, categories as catmod, dates, journal as j, notes as notemod, startup
from .categories import Category
from .calendar import Meeting
from .journal import Entry

AHEAD_ROWS = 4
BACKLOG_ROWS = 5         # the backlog preview on today's page
DONE_VISIBLE = timedelta(days=7)   # ticked ongoing tasks stay visible this long
LIST_TARGETS = [("l:ongoing", "Ongoing"), ("l:backlog", "Backlog")]
NEXT_ROWS = 5            # the day view's preview of the next working day
DAYS_OFF_HORIZON = 120   # how far ahead "Ahead" looks for days off
FUTURE_HORIZON = 365     # how far ahead the future log looks for days off
FUTURE_WEEKS = 6         # weeks listed in the future log's side panel
BOOKED = {"busy", "tentative", "oof"}   # what counts towards "booked" time


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


def duration(minutes: int) -> str:      # "3 h 30 m", "45 m", "2 h"
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h} h {m} m"
    return f"{h} h" if h else f"{m} m"


def where(e: Entry, near: date) -> str:
    """Where an entry lives, as briefly as is clear from `near`."""
    if e.entry_list:
        return e.entry_list.capitalize()        # "Backlog", "Ongoing"
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
    forward: str = ""                   # where ">" would send it: "Fri 23", "Week 45"

    @property
    def carried(self) -> bool:
        return bool(self.trail)

    @property
    def day_count(self) -> str:         # "4th day"
        return f"{ordinal(len(self.trail))} day"


def rows_for(conn, entries: list[Entry], near: date, today: date | None = None,
             cal: dates.WorkCalendar | None = None) -> list[Row]:
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
        if e.kind == "task" and e.state == "open":
            # Lists aren't day-by-day, so their tasks never show a carry trail.
            if e.carry_count > 0 and not e.entry_list:
                chain = [x for x in j.history(conn, e.id) if x.carry_count <= e.carry_count]
                here = e.entry_date or dates.week_monday(e.entry_week)
                row.trail = [where(x, here) for x in chain]
            if today and cal:
                on, week = j.forward_target(e, today, cal)
                row.forward = short_day(on) if on else week_label(week)
        out.append(row)
    return out


# --- Meetings ---------------------------------------------------------------

@dataclass
class MeetingRow:
    m: Meeting
    time: str                           # "09:30–10:00" or "All day"
    kind: str                           # busy / tentative / free / oof / workingelsewhere
    past: bool = False
    # Placement in the week's time grid (pixels, and side-by-side lanes for clashes)
    top: int = 0
    height: int = 0
    lane: int = 0
    lanes: int = 1
    category: Category | None = None


def meeting_rows(meetings: list[Meeting], d: date, now: datetime,
                 cats: dict[str, Category | None] | None = None) -> list[MeetingRow]:
    out = []
    for m in meetings:
        if m.all_day:
            time = "All day"
        else:
            s, e = m.local_start(), m.local_end()
            # A meeting that started before this day, or runs past it
            start = f"{s:%H:%M}" if s.date() == d else "…"
            end = f"{e:%H:%M}" if e.date() == d or (e.date() == d + timedelta(days=1) and e.hour == 0 and e.minute == 0) else "…"
            time = f"{start}–{end}"
        out.append(MeetingRow(m, time, m.show_as, past=m.end <= now, category=(cats or {}).get(m.id)))
    return out


HOUR_PX = 56          # time grid: pixels per hour
MIN_BLOCK_PX = 22     # a 15-minute meeting still shows its time


def grid_hours(rows: list[MeetingRow]) -> tuple[int, int]:
    """The week's visible hours: 08:00-18:00, widened to fit early or late meetings."""
    timed = [r.m for r in rows if not r.m.all_day]
    first = min([8] + [m.local_start().hour for m in timed])
    last = max([18] + [m.local_end().hour + (1 if m.local_end().minute else 0) for m in timed])
    return max(0, first), min(24, last)


def lay_out(rows: list[MeetingRow], d: date, first_hour: int, last_hour: int) -> None:
    """Position each timed meeting in the day's track; clashing meetings share
    the width in lanes (greedy interval partitioning per cluster)."""
    timed = [r for r in rows if not r.m.all_day]
    span = (last_hour - first_hour) * 60
    for r in timed:
        s, e = r.m.local_start(), r.m.local_end()
        start = (s.hour * 60 + s.minute) if s.date() == d else 0
        end = (e.hour * 60 + e.minute) if e.date() == d else 24 * 60
        top = max(0, min(span, start - first_hour * 60))
        bottom = max(top, min(span, end - first_hour * 60))
        r.top = round(top * HOUR_PX / 60)
        r.height = max(MIN_BLOCK_PX, round((bottom - top) * HOUR_PX / 60) - 2)
    cluster: list[MeetingRow] = []
    lane_ends: list[datetime] = []
    cluster_end: datetime | None = None

    def finish():
        for c in cluster:
            c.lanes = len(lane_ends)

    for r in sorted(timed, key=lambda r: (r.m.start, r.m.end)):
        if cluster and r.m.start >= cluster_end:
            finish()
            cluster, lane_ends, cluster_end = [], [], None
        free = next((i for i, end in enumerate(lane_ends) if end <= r.m.start), None)
        if free is None:
            lane_ends.append(r.m.end)
            r.lane = len(lane_ends) - 1
        else:
            lane_ends[free] = r.m.end
            r.lane = free
        cluster.append(r)
        cluster_end = r.m.end if cluster_end is None else max(cluster_end, r.m.end)
    finish()


def booked_minutes(meetings: list[Meeting]) -> int:
    return sum(m.minutes for m in meetings if not m.all_day and m.show_as in BOOKED)


def next_meeting(meetings: list[Meeting], now: datetime) -> Meeting | None:
    upcoming = [m for m in meetings if not m.all_day and m.start > now]
    return min(upcoming, key=lambda m: m.start) if upcoming else None


@dataclass
class CalendarLine:
    text: str
    problem: bool = False


def calendar_line(status: calmod.Status, now: datetime) -> CalendarLine:
    if not status.configured:
        return CalendarLine("Calendar not set up")
    if status.error:
        return CalendarLine(status.error, problem=True)
    if not status.exported_at:
        return CalendarLine("Outlook export found")
    local = dates.to_local(status.exported_at)
    when = f"{local:%H:%M}" if local.date() == dates.local_today(now) else f"{local.day} {local:%b}, {local:%H:%M}"
    stale = now - status.exported_at > timedelta(hours=2)
    return CalendarLine(f"Outlook as of {when}" + (" (not updating?)" if stale else ""), problem=stale)


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


def planned_after(conn, cal, week: str, today: date, horizon: int) -> list[AheadItem]:
    """Open entries and days off after a week, in date order."""
    rows = rows_for(conn, j.entries_after(conn, week), today, today, cal)
    items = [
        AheadItem(on=r.e.entry_date or dates.week_monday(r.e.entry_week),
                  when=day_month(r.e.entry_date) if r.e.entry_date else week_label(r.e.entry_week), row=r)
        for r in rows
    ]
    start = dates.week_dates(week)[-1] + timedelta(days=1)
    items += days_off_after(cal, j.day_off_reasons(conn), start, horizon)
    items.sort(key=lambda a: (a.on, a.row is None))
    return items


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
    meetings: list[MeetingRow]
    booked: int = 0                     # minutes

    @property
    def open_tasks(self) -> int:
        return sum(1 for r in self.rows if r.e.kind == "task" and r.e.state == "open")

    @property
    def booked_label(self) -> str:
        return duration(self.booked) if self.booked else ""

    @property
    def n_meetings(self) -> int:
        return sum(1 for mr in self.meetings if not mr.m.all_day)


WEEK_SHOW = ("meetings", "all")


def week_view(conn, key: str, today: date, now: datetime, show: str = "meetings") -> dict:
    cal = j.load_calendar(conn)
    reasons = j.day_off_reasons(conn)
    by_day, unplaced = j.entries_for_week(conn, key)
    cols = []
    all_meetings: list[Meeting] = []
    on_day = {d: calmod.meetings_on(conn, d) for d in by_day}
    cats = catmod.for_meetings(conn, list({m.id: m for ms in on_day.values() for m in ms}.values()))
    for d, es in by_day.items():
        ms = on_day[d]
        if not (d.weekday() in cal.working_weekdays or cal.is_working_day(d) or es or ms):
            continue
        all_meetings += [m for m in ms if m not in all_meetings]
        cols.append(DayCol(d, short_day(d), d == today, d < today, off_reason(cal, reasons, d),
                           rows_for(conn, es, d, today, cal), meeting_rows(ms, d, now, cats), booked_minutes(ms)))
    monday = dates.week_monday(key)
    is_current = key == dates.week_key(today)
    year, number = dates.parse_week_key(key)

    n_meetings = sum(1 for m in all_meetings if not m.all_day)
    week_meetings = f"{plural(n_meetings, 'meeting')}, {duration(booked_minutes(all_meetings))}" if n_meetings else "no meetings"
    if show == "meetings":
        nxt = next_meeting(all_meetings, now)
        if is_current:
            title = f"{today:%A}, week {number}"
            facts = f"{today.day} {today:%B} · {week_meetings} this week"
            if nxt:
                when = f"{nxt.local_start():%H:%M}" if nxt.local_start().date() == today else f"{nxt.local_start():%a} {nxt.local_start():%H:%M}"
                facts += f" · next: {nxt.subject} at {when}"
        else:
            title = week_label(key)
            facts = f"{week_range(key)} {year} · {week_meetings}"
    elif is_current:
        target = dates.carry_over_target(today, cal)
        today_rows = rows_for(conn, j.entries_for_day(conn, target), target)
        open_today = sum(1 for r in today_rows if r.e.kind == "task" and r.e.state == "open")
        title = f"{today:%A}, week {number}"
        facts = f"{today.day} {today:%B} · {open_today} open today · {carried_fact(today_rows)}"
    else:
        open_total = sum(c.open_tasks for c in cols)
        done = sum(1 for c in cols for r in c.rows if r.e.state == "done")
        title = week_label(key)
        facts = f"{week_range(key)} {year} · {plural(open_total, 'open task')} · {done} done"

    first_hour, last_hour = grid_hours([r for c in cols for r in c.meetings])
    for c in cols:
        lay_out(c.meetings, c.date, first_hour, last_hour)
    now_local = dates.to_local(now)
    now_px = None
    if is_current and first_hour <= now_local.hour < last_hour:
        now_px = round(((now_local.hour - first_hour) * 60 + now_local.minute) * HOUR_PX / 60)
    grid = {
        "hours": [(h, f"{h:02d}:00", (h - first_hour) * HOUR_PX) for h in range(first_hour, last_hour)],
        "height": (last_hour - first_hour) * HOUR_PX,
        "all_day_rows": max([0] + [sum(1 for r in c.meetings if r.m.all_day) for c in cols]),
        "now_px": now_px,
    }

    targets = [(f"d:{c.date.isoformat()}", c.label) for c in cols] + [(f"w:{key}", "No day yet")] + LIST_TARGETS
    default = f"d:{today.isoformat()}" if any(c.is_today for c in cols) else f"w:{key}"
    ahead_items = planned_after(conn, cal, key, today, DAYS_OFF_HORIZON)
    return {
        "key": key, "title": title, "facts": facts, "is_current": is_current, "show": show, "grid": grid,
        "prev_key": dates.shift_week(key, -1), "next_key": dates.shift_week(key, 1),
        "prev_label": week_label(dates.shift_week(key, -1)), "next_label": week_label(dates.shift_week(key, 1)),
        "days": cols, "unplaced": rows_for(conn, unplaced, monday, today, cal),
        "targets": targets, "default_target": default,
        "ahead": ahead_items[:AHEAD_ROWS], "ahead_more": max(0, len(ahead_items) - AHEAD_ROWS),
        "rolling": rolling(conn, cal, today),
        "phone_title": f"Week {number}",
    }


# --- Day --------------------------------------------------------------------

def day_view(conn, d: date, today: date, now: datetime) -> dict:
    cal = j.load_calendar(conn)
    reasons = j.day_off_reasons(conn)
    rows = rows_for(conn, j.entries_for_day(conn, d), d, today, cal)
    key = dates.week_key(d)
    _, unplaced = j.entries_for_week(conn, key)
    ms = calmod.meetings_on(conn, d)
    open_n = sum(1 for r in rows if r.e.kind == "task" and r.e.state == "open")
    done_n = sum(1 for r in rows if r.e.state == "done")
    _, number = dates.parse_week_key(key)
    n_meetings = sum(1 for m in ms if not m.all_day)
    facts = f"Week {number} · {open_n} open, {done_n} done"
    if n_meetings:
        facts += f" · {plural(n_meetings, 'meeting')}, {duration(booked_minutes(ms))}"
    if d == dates.carry_over_target(today, cal):
        facts += f" · {carried_fact(rows)}"
    off = off_reason(cal, reasons, d)
    if off:
        facts = f"{off} · " + facts
    nxt = cal.next_working_day(d)
    coming = j.entries_for_day(conn, nxt)
    backlog = j.entries_in_list(conn, "backlog")
    return {
        "date": d, "title": long_day(d), "facts": facts, "is_today": d == today,
        "week_key": key, "week_label": f"Week {number}",
        "prev_day": cal.previous_working_day(d), "next_day": nxt,
        "prev_label": short_day(cal.previous_working_day(d)), "next_label": short_day(nxt),
        "rows": rows, "unplaced": rows_for(conn, unplaced, d, today, cal),
        "meetings": meeting_rows(ms, d, now, catmod.for_meetings(conn, ms)),
        "coming": rows_for(conn, coming, d)[:NEXT_ROWS], "coming_more": max(0, len(coming) - NEXT_ROWS),
        "ongoing": rows_for(conn, j.entries_in_list(conn, "ongoing", now - DONE_VISIBLE), d, today, cal),
        "notes": notemod.for_day(conn, d),
        "backlog": rows_for(conn, backlog[:BACKLOG_ROWS], d, today, cal) if d == today else [],
        "backlog_more": max(0, len(backlog) - BACKLOG_ROWS), "backlog_total": len(backlog),
        "targets": [(f"d:{d.isoformat()}", short_day(d))] + LIST_TARGETS, "default_target": f"d:{d.isoformat()}",
        "phone_title": short_day(d),
    }


# --- Future log -------------------------------------------------------------

@dataclass
class WeekLoad:
    key: str
    label: str
    range: str
    planned: int
    meetings: int
    booked: int

    @property
    def booked_label(self) -> str:
        return duration(self.booked) if self.booked else "–"


def future_view(conn, today: date) -> dict:
    cal = j.load_calendar(conn)
    this_week = dates.week_key(today)
    items = planned_after(conn, cal, this_week, today, FUTURE_HORIZON)
    months: list[tuple[str, list[AheadItem]]] = []
    for a in items:
        label = f"{a.on:%B %Y}"
        if not months or months[-1][0] != label:
            months.append((label, []))
        months[-1][1].append(a)

    loads = []
    for i in range(1, FUTURE_WEEKS + 1):
        key = dates.shift_week(this_week, i)
        days = dates.week_dates(key)
        start, _ = dates.day_bounds_utc(days[0])
        _, end = dates.day_bounds_utc(days[-1])
        ms = calmod.meetings_between(conn, start, end)
        by_day, unplaced = j.entries_for_week(conn, key)
        planned = sum(1 for es in by_day.values() for e in es if e.state == "open") + sum(1 for e in unplaced if e.state == "open")
        loads.append(WeekLoad(key, week_label(key), week_range(key), planned,
                              sum(1 for m in ms if not m.all_day), booked_minutes(ms)))

    n = sum(1 for a in items if a.row)
    return {
        "title": "Future log",
        "facts": f"{n} {'entry' if n == 1 else 'entries'} planned after this week" if n
                 else "Nothing planned after this week yet",
        "months": months, "loads": loads,
        "min_date": (today + timedelta(days=1)).isoformat(),
        "default_week": dates.shift_week(this_week, 1),
        "phone_title": "Future log",
    }


# --- Backlog and ongoing ------------------------------------------------------

def backlog_view(conn, today: date, now: datetime) -> dict:
    cal = j.load_calendar(conn)
    ongoing = rows_for(conn, j.entries_in_list(conn, "ongoing"), today, today, cal)
    backlog = rows_for(conn, j.entries_in_list(conn, "backlog"), today, today, cal)
    finished = rows_for(conn, j.finished_from_lists(conn, now - timedelta(days=14)), today)
    n_on = sum(1 for r in ongoing if r.e.state == "open")
    return {
        "title": "Backlog",
        "facts": f"{n_on} ongoing · {len(backlog)} in the backlog",
        "ongoing": ongoing, "backlog": backlog, "finished": finished,
        "targets": [("l:backlog", "Backlog"), ("l:ongoing", "Ongoing"), (f"d:{today.isoformat()}", "Today")],
        "default_target": "l:backlog",
        "phone_title": "Backlog",
    }


# --- Settings -----------------------------------------------------------------

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@dataclass
class DayOffRun:
    start: date
    end: date
    reason: str
    days: int

    @property
    def label(self) -> str:
        if self.start == self.end:
            return day_month(self.start)
        if self.start.month == self.end.month:
            return f"{self.start.day}–{self.end.day} {self.end:%b}"
        return f"{self.start.day} {self.start:%b} – {self.end.day} {self.end:%b}"


def leave_runs(conn, today: date) -> list[DayOffRun]:
    """Your own days off from today on, grouped into runs (bank holidays aren't listed)."""
    rows = conn.execute(
        "SELECT date, reason FROM day_overrides WHERE working = 0 AND date >= ? ORDER BY date", (today.isoformat(),))
    runs: list[DayOffRun] = []
    for r in rows:
        d = date.fromisoformat(r["date"])
        last = runs[-1] if runs else None
        if last and last.reason == r["reason"] and (d - last.end).days <= 3 and all(
                (last.end + timedelta(days=i)).weekday() >= 5 for i in range(1, (d - last.end).days)):
            last.end, last.days = d, last.days + 1
        else:
            runs.append(DayOffRun(d, d, r["reason"], 1))
    return runs


def settings_view(conn, today: date, db_path) -> dict:
    cal = j.load_calendar(conn)
    backups = backup.list_backups(db_path)
    return {
        "title": "Settings",
        "facts": "Categories, working days, days off and backups",
        "categories": catmod.all_categories(conn, include_archived=False),
        "archived": [c for c in catmod.all_categories(conn) if c.archived],
        "palette": catmod.PALETTE,
        "weekdays": [(i, WEEKDAY_NAMES[i], i in cal.working_weekdays) for i in range(7)],
        "leave": leave_runs(conn, today),
        "min_date": today.isoformat(),
        "startup_available": startup.available(), "startup_on": startup.is_enabled(),
        "backups": [(p.name, f"{p.stat().st_size / 1024:.0f} KB") for p in backups[:5]],
        "backup_dir": str(backup.backup_dir(db_path)),
        "phone_title": "Settings",
    }


# --- Notes ----------------------------------------------------------------------

SIDEBAR_BOOKMARKS = 10


def note_when(n) -> str:
    return day_month(n.e.entry_date) if n.e.entry_date else week_label(n.e.entry_week)


def note_view(conn, entry_id: int, today: date) -> dict:
    n = notemod.get(conn, entry_id)
    key = n.e.entry_week or dates.week_key(n.e.entry_date)
    _, number = dates.parse_week_key(key)
    where = long_day(n.e.entry_date) if n.e.entry_date else f"{week_label(key)}, no day"
    siblings = [x for x in notemod.for_week(conn, key) if x.e.id != n.e.id]
    back = (f"/day/{n.e.entry_date.isoformat()}", short_day(n.e.entry_date)) if n.e.entry_date \
        else (f"/week/{key}?show=all", week_label(key))
    return {
        "title": n.e.text, "note": n,
        "facts": f"{where} · Week {number}" + (f" · {n.category.name}" if n.category else ""),
        "back_url": back[0], "back_label": back[1],
        "siblings": siblings, "week_label": week_label(key),
        "phone_title": "Note",
    }


@dataclass
class NoteGroup:
    key: str
    label: str
    sub: str
    notes: list


def notes_list_view(conn, by: str = "week", bookmarked_only: bool = False) -> dict:
    all_n = notemod.all_notes(conn, bookmarked_only)
    groups: list[NoteGroup] = []
    if by == "category":
        order = {c.id: i for i, c in enumerate(catmod.all_categories(conn))}
        by_cat: dict = {}
        for n in all_n:
            by_cat.setdefault(n.category.id if n.category else None, []).append(n)
        for cid in sorted(by_cat, key=lambda c: (c is None, order.get(c, 0))):
            ns = by_cat[cid]
            c = ns[0].category
            groups.append(NoteGroup(f"c{cid}", c.name if c else "No category",
                                    ("archived" if c and c.archived else ""), ns))
    else:
        for n in all_n:
            key = n.e.entry_week or dates.week_key(n.e.entry_date)
            if not groups or groups[-1].key != key:
                year, number = dates.parse_week_key(key)
                groups.append(NoteGroup(key, f"Week {number}", f"{week_range(key)} {year}", []))
            groups[-1].notes.append(n)
    n_book = sum(1 for n in all_n if n.bookmarked)
    total = len(all_n)
    facts = (f"{total} bookmarked note{'s' if total != 1 else ''}" if bookmarked_only
             else f"{total} note{'s' if total != 1 else ''}, {n_book} bookmarked")
    return {
        "title": "Notes", "facts": facts, "groups": groups, "by": by, "bookmarked_only": bookmarked_only,
        "phone_title": "Notes",
    }
