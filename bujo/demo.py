"""Sample journal for trying the app (`py run.py --demo`) and for design checks.

Built through the real journal functions, replaying the week day by day so
carry-over, history and trails are produced exactly as they would be in use.
Everything here is made-up sample content.
"""

from datetime import date, timedelta

from . import dates, journal as j

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
