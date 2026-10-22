from datetime import date, datetime, timedelta, timezone

import pytest

from bujo import dates
from bujo.dates import WorkCalendar, SAT, SUN

UTC = timezone.utc
CAL = WorkCalendar()


def d(s: str) -> date:
    return date.fromisoformat(s)


# --- ISO weeks, year boundaries, week 53 ------------------------------------

@pytest.mark.parametrize("day,key", [
    ("2026-10-22", "2026-W43"),
    ("2024-12-30", "2025-W01"),   # Monday in Dec belongs to next ISO year
    ("2027-01-01", "2026-W53"),   # Friday in Jan belongs to previous ISO year
    ("2027-01-03", "2026-W53"),
    ("2027-01-04", "2027-W01"),
    ("2021-01-03", "2020-W53"),
])
def test_week_key(day, key):
    assert dates.week_key(d(day)) == key


def test_weeks_in_year():
    assert dates.weeks_in_year(2026) == 53
    assert dates.weeks_in_year(2020) == 53
    assert dates.weeks_in_year(2025) == 52
    assert dates.weeks_in_year(2027) == 52


def test_week_dates_and_shift_across_week_53():
    assert dates.week_dates("2026-W53")[0] == d("2026-12-28")
    assert dates.week_dates("2026-W53")[-1] == d("2027-01-03")
    assert dates.shift_week("2026-W52", 1) == "2026-W53"
    assert dates.shift_week("2026-W53", 1) == "2027-W01"
    assert dates.shift_week("2027-W01", -1) == "2026-W53"


@pytest.mark.parametrize("bad", ["2025-W53", "2026-W00", "2026-43", "nonsense", "2026-W54"])
def test_parse_week_key_rejects_invalid(bad):
    with pytest.raises(ValueError):
        dates.parse_week_key(bad)


# --- Working days -----------------------------------------------------------

def test_friday_to_monday():
    assert CAL.next_working_day(d("2026-10-23")) == d("2026-10-26")
    assert CAL.previous_working_day(d("2026-10-26")) == d("2026-10-23")


def test_bank_holidays_skipped():
    # Thu 2 Apr 2026 -> Good Friday 3rd, weekend, Easter Monday 6th -> Tue 7th
    assert CAL.next_working_day(d("2026-04-02")) == d("2026-04-07")
    assert not CAL.is_working_day(d("2026-08-31"))
    assert CAL.holiday_name(d("2026-08-31")) == "Summer bank holiday"


def test_christmas_and_year_boundary():
    # Thu 24 Dec 2026 -> Christmas Fri, weekend, Boxing Day substitute Mon 28th
    assert CAL.next_working_day(d("2026-12-24")) == d("2026-12-29")
    # Thu 31 Dec 2026 -> New Year's Day Fri, weekend -> Mon 4 Jan 2027
    assert CAL.next_working_day(d("2026-12-31")) == d("2027-01-04")
    assert CAL.previous_working_day(d("2027-01-04")) == d("2026-12-31")


def test_annual_leave_and_extra_working_day():
    cal = WorkCalendar(
        non_working=frozenset({d("2026-10-26"), d("2026-10-27")}),
        extra_working=frozenset({d("2026-10-24")}),  # worked a Saturday
    )
    assert cal.next_working_day(d("2026-10-23")) == d("2026-10-24")
    assert cal.next_working_day(d("2026-10-24")) == d("2026-10-28")


def test_custom_working_week():
    cal = WorkCalendar(working_weekdays=frozenset({0, 1, 2, 3}))  # Mon-Thu
    assert cal.next_working_day(d("2026-10-22")) == d("2026-10-26")
    assert cal.working_days_in_week("2026-W43") == [d("2026-10-19") + timedelta(i) for i in range(4)]


def test_working_days_in_week_with_holiday():
    assert CAL.working_days_in_week("2026-W53") == [d("2026-12-29"), d("2026-12-30"), d("2026-12-31")]


def test_inclusive_flag():
    assert CAL.previous_working_day(d("2026-10-22"), inclusive=True) == d("2026-10-22")
    assert CAL.previous_working_day(d("2026-10-25"), inclusive=True) == d("2026-10-23")


def test_no_working_days_is_an_error():
    with pytest.raises(ValueError):
        WorkCalendar(working_weekdays=frozenset()).next_working_day(d("2026-10-22"))


# --- Local time and DST -----------------------------------------------------

@pytest.mark.parametrize("instant,expected", [
    (datetime(2026, 6, 30, 23, 30, tzinfo=UTC), "2026-07-01"),   # BST: already tomorrow
    (datetime(2026, 12, 31, 23, 30, tzinfo=UTC), "2026-12-31"),  # GMT: same day
    (datetime(2026, 3, 29, 0, 30, tzinfo=UTC), "2026-03-29"),    # just before spring forward
    (datetime(2026, 3, 28, 23, 59, tzinfo=UTC), "2026-03-28"),
    (datetime(2026, 10, 24, 23, 30, tzinfo=UTC), "2026-10-25"),  # BST night before fall back
    (datetime(2026, 10, 25, 23, 30, tzinfo=UTC), "2026-10-25"),  # GMT after fall back
])
def test_local_today(instant, expected):
    assert dates.local_today(instant) == d(expected)


def test_local_today_rejects_naive():
    with pytest.raises(ValueError):
        dates.local_today(datetime(2026, 1, 1))


def test_day_bounds_on_dst_days():
    start, end = dates.day_bounds_utc(d("2026-03-29"))  # clocks go forward
    assert start == datetime(2026, 3, 29, 0, 0, tzinfo=UTC)
    assert end == datetime(2026, 3, 29, 23, 0, tzinfo=UTC)
    assert end - start == timedelta(hours=23)

    start, end = dates.day_bounds_utc(d("2026-10-25"))  # clocks go back
    assert start == datetime(2026, 10, 24, 23, 0, tzinfo=UTC)
    assert end - start == timedelta(hours=25)

    start, end = dates.day_bounds_utc(d("2026-07-01"))
    assert start == datetime(2026, 6, 30, 23, 0, tzinfo=UTC)
    assert end - start == timedelta(hours=24)


# --- Carry-over rules -------------------------------------------------------

@pytest.mark.parametrize("today,target", [
    ("2026-10-22", "2026-10-22"),  # Thursday: today
    ("2026-10-24", "2026-10-23"),  # Saturday: stay on Friday
    ("2026-10-25", "2026-10-23"),  # Sunday: stay on Friday
    ("2026-10-26", "2026-10-26"),  # Monday
    ("2026-08-31", "2026-08-28"),  # bank holiday Monday: stay on Friday
    ("2027-01-01", "2026-12-31"),  # New Year's Day
])
def test_carry_over_target(today, target):
    assert dates.carry_over_target(d(today), CAL) == d(target)


def test_is_overdue_dated():
    t = d("2026-10-26")
    assert dates.is_overdue(d("2026-10-23"), None, t)
    assert dates.is_overdue(d("2026-10-25"), None, t)       # weekend-dated task
    assert dates.is_overdue(d("2026-09-01"), None, t)       # long gap
    assert not dates.is_overdue(d("2026-10-26"), None, t)
    assert not dates.is_overdue(d("2026-11-02"), None, t)   # future


def test_is_overdue_week_only():
    t = d("2026-10-22")  # 2026-W43
    assert not dates.is_overdue(None, "2026-W43", t)  # this week: stays in spread
    assert not dates.is_overdue(None, "2026-W44", t)
    assert dates.is_overdue(None, "2026-W42", t)
    assert dates.is_overdue(None, "2026-W53", d("2027-01-04"))  # across week 53
    assert not dates.is_overdue(None, None, t)
