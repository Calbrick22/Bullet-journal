"""Sample journal for trying the app (`py run.py --demo`) and for design checks.

Built through the real journal functions, replaying the week day by day so
carry-over, history and trails are produced exactly as they would be in use.
Everything here is made-up sample content.
"""

import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from . import categories as cats, dates, journal as j
from .calendar import Meeting

# Per weekday of the current week (0 = Monday): (kind, text, done_by_end_of_day)
PLAN = {
    0: [("task", "Draft agenda for Thursday's review", True),
        ("task", "Send Q3 figures to Priya", False),
        ("task", "Book train to Leeds for 3 Nov", True),
        ("note", "Ops review moved to Thursday", False)],
    1: [("task", "Reply to Hannah about the supplier contract", True),
        ("task", "Review Dev's onboarding checklist", False),
        ("task", "Order a new laptop charger", "cancel")],
    2: [("task", "Update the risk register", True),
        ("task", "Chase IT about the VPN token", False),
        ("event", "Fire drill at 11:00", False),
        ("note", "Priya wants the regional split, not just totals", False)],
    3: [("task", "Approve October timesheets", True),
        ("task", "Prepare slides for the ops review", False),
        ("task", "Book a room for the team lunch", False),
        ("note", "Ask about Q1 headcount", False)],
    4: [("task", "Send the ops review minutes", False),
        ("event", "Team lunch, 12:30", False)],
}


def seed(conn, today: date) -> None:
    cal = j.load_calendar(conn)
    week = dates.week_key(today)
    monday = dates.week_monday(week)

    # A task planned two weeks ago for this Friday, so its "planned on" note shows.
    planned = j.add_entry(conn, "task", "Submit September expenses", on=monday - timedelta(days=11))
    j.move_task(conn, planned.id, on=monday + timedelta(days=4), today=monday - timedelta(days=11))

    for offset, items in PLAN.items():
        d = monday + timedelta(days=offset)
        if d > today:
            # Future days: plan ahead, nothing done yet.
            for kind, text, _ in items:
                j.add_entry(conn, kind, text, on=d)
            continue
        if not cal.is_working_day(d):
            continue
        j.carry_over(conn, today=d, cal=cal)
        for kind, text, done in items:
            e = j.add_entry(conn, kind, text, on=d)
            if done is True and d < today or (done is True and offset == today.weekday() and kind == "task" and "timesheets" in text):
                j.mark_done(conn, e.id)
            elif done == "cancel":
                j.cancel(conn, e.id)
    j.carry_over(conn, today=today, cal=cal)

    for text in ("Clear out the shared drive folder", "Read the new travel policy"):
        j.add_entry(conn, "task", text, week=week)

    next_monday = monday + timedelta(weeks=1)
    j.add_entry(conn, "task", "Plan the November rota", on=next_monday)
    j.add_entry(conn, "task", "Start the Q1 headcount plan", week=dates.shift_week(week, 2))
    j.add_entry(conn, "event", "Leeds site visit", on=next_monday + timedelta(days=8))
    j.add_entry(conn, "task", "Book the dentist", on=next_monday + timedelta(days=10))
    for i in range(3):  # three days' leave in three weeks' time
        j.set_day_override(conn, monday + timedelta(weeks=3, days=i), working=False, reason="Annual leave")

    for text in ("Tidy the team wiki", "Archive the 2025 project folders", "Draft onboarding guide v2",
                 "Look into a better expenses template"):
        j.add_entry(conn, "task", text, lst="backlog")
    for text in ("Q4 budget model", "Supplier contract renewal"):
        j.add_entry(conn, "task", text, lst="ongoing")
    j.mark_done(conn, j.add_entry(conn, "task", "Update the team org chart", lst="ongoing").id)

    # Meeting categories, remembered by meeting name
    atlas, internal, hiring = (cats.add(conn, "Project Atlas", "mint"), cats.add(conn, "Internal", "lime"),
                               cats.add(conn, "Hiring", "rose"))
    old = cats.add(conn, "Brightline pilot", "peach")
    cats.set_archived(conn, old.id, True)
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for subject, cat in (("Weekly ops stand-up", internal), ("Q4 planning", atlas), ("Ops review", atlas),
                         ("Vendor demo: Fieldline", atlas), ("Hiring sync", hiring), ("1:1 with Hannah", internal)):
        cats.tag(conn, Meeting("demo-seed", subject, stamp, stamp), cat.id)


# Meetings per weekday: (start, end, subject, location, showAs). Repeated each week.
MEETINGS = {
    0: [("09:30", "10:00", "Weekly ops stand-up", "Teams", "busy"), ("14:00", "15:00", "Q4 planning", "Room 3.12", "busy")],
    1: [("10:00", "10:30", "1:1 with Hannah", "", "busy"), ("13:00", "14:00", "Supplier call: Brightline", "Teams", "busy"),
        ("16:00", "16:30", "Budget check-in", "", "tentative")],
    2: [("09:30", "10:00", "Weekly ops stand-up", "Teams", "busy"), ("11:30", "12:30", "Vendor demo: Fieldline", "Room 2.04", "busy"),
        ("15:00", "15:30", "Hiring sync", "", "busy")],
    3: [("09:30", "10:00", "Weekly ops stand-up", "Teams", "busy"), ("11:00", "12:00", "Ops review", "Room 3.12", "busy"),
        ("14:00", "14:30", "1:1 with Sam", "", "busy"), ("16:30", "17:00", "Quarterly numbers with Priya", "Teams", "busy")],
    4: [("09:30", "10:00", "Weekly ops stand-up", "Teams", "busy"), ("12:30", "13:30", "Team lunch", "The Crown", "free")],
}


def _pa_utc(d: date, hhmm: str) -> str:
    """A local time as Power Automate writes it: UTC, seven fractional digits, no offset."""
    local = datetime.combine(d, time.fromisoformat(hhmm), dates.LOCAL_TZ)
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.0000000")


def write_calendar(path: Path, today: date) -> None:
    """A sample Power Automate export: last week to six weeks ahead."""
    monday = dates.week_monday(dates.week_key(today))
    first, last = monday - timedelta(weeks=1), monday + timedelta(weeks=6)
    events = []
    d = first
    while d < last:
        for i, (s, e, subject, where, show) in enumerate(MEETINGS.get(d.weekday(), [])):
            events.append({"id": f"demo-{d.isoformat()}-{i}", "subject": subject, "start": _pa_utc(d, s),
                           "end": _pa_utc(d, e), "isAllDay": False, "location": where, "showAs": show})
        d += timedelta(days=1)
    off = monday + timedelta(days=4)
    events.append({"id": "demo-allday", "subject": "Payroll deadline", "start": f"{off.isoformat()}T00:00:00.0000000",
                   "end": f"{(off + timedelta(days=1)).isoformat()}T00:00:00.0000000", "isAllDay": True,
                   "location": "", "showAs": "free"})
    data = {
        "exported_at": datetime.combine(today, time(8, 45), dates.LOCAL_TZ).astimezone(timezone.utc).isoformat(),
        "window": {"start": _pa_utc(first, "00:00") + "Z", "end": _pa_utc(last, "00:00") + "Z"},
        "events": events,
    }
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
