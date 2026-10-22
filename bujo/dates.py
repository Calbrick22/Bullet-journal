"""Pure date logic: working days, ISO weeks, local time and carry-over rules.

No database or I/O here. Everything takes plain dates/datetimes so it can be
unit tested exhaustively. Journal dates are local calendar dates
(Europe/London); instants such as meeting times are UTC datetimes.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from .holidays import england_bank_holidays

LOCAL_TZ = ZoneInfo("Europe/London")
MON, TUE, WED, THU, FRI, SAT, SUN = range(7)


# --- Local time -------------------------------------------------------------

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def local_today(now_utc: datetime | None = None, tz: ZoneInfo = LOCAL_TZ) -> date:
    """The local calendar date at a given UTC instant (default: now)."""
    now_utc = now_utc or utc_now()
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    return now_utc.astimezone(tz).date()


def day_bounds_utc(d: date, tz: ZoneInfo = LOCAL_TZ) -> tuple[datetime, datetime]:
    """UTC start (inclusive) and end (exclusive) of a local day.

    Days are 23 or 25 hours long when the clocks change, so never compute
    the end as start + 24h.
    """
    start = datetime.combine(d, time.min, tz)
    end = datetime.combine(d + timedelta(days=1), time.min, tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def to_local(instant_utc: datetime, tz: ZoneInfo = LOCAL_TZ) -> datetime:
    return instant_utc.astimezone(tz)


# --- ISO weeks --------------------------------------------------------------

def week_key(d: date) -> str:
    """ISO week identifier, e.g. '2026-W43'. Note the ISO year can differ
    from the calendar year around 1 January."""
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def parse_week_key(key: str) -> tuple[int, int]:
    try:
        year_s, week_s = key.split("-W")
        year, week = int(year_s), int(week_s)
        date.fromisocalendar(year, week, 1)  # validates week 53 etc.
    except ValueError as e:
        raise ValueError(f"Not an ISO week key: {key!r}") from e
    return year, week


def week_monday(key: str) -> date:
    return date.fromisocalendar(*parse_week_key(key), 1)


def week_dates(key: str) -> list[date]:
    monday = week_monday(key)
    return [monday + timedelta(days=i) for i in range(7)]


def shift_week(key: str, weeks: int) -> str:
    return week_key(week_monday(key) + timedelta(weeks=weeks))


def weeks_in_year(iso_year: int) -> int:
    # 28 December is always in the last ISO week of its year.
    return date(iso_year, 12, 28).isocalendar()[1]


# --- Working days -----------------------------------------------------------

@dataclass(frozen=True)
class WorkCalendar:
    """Which dates are working days.

    working_weekdays: weekday numbers (Mon=0) normally worked.
    non_working: extra days off (annual leave, one-off holidays).
    extra_working: weekend or holiday dates you chose to work.
    bank_holidays: include England & Wales bank holidays.
    """

    working_weekdays: frozenset[int] = frozenset({MON, TUE, WED, THU, FRI})
    non_working: frozenset[date] = field(default_factory=frozenset)
    extra_working: frozenset[date] = field(default_factory=frozenset)
    bank_holidays: bool = True

    def is_working_day(self, d: date) -> bool:
        if d in self.extra_working:
            return True
        if d in self.non_working:
            return False
        if self.bank_holidays and d in _bank_holidays(d.year):
            return False
        return d.weekday() in self.working_weekdays

    def holiday_name(self, d: date) -> str | None:
        return _bank_holidays(d.year).get(d) if self.bank_holidays else None

    def _step(self, d: date, direction: int, inclusive: bool) -> date:
        if not self.working_weekdays and not self.extra_working:
            raise ValueError("No working days configured")
        cur = d if inclusive else d + timedelta(days=direction)
        # A whole year without a working day means the config is broken.
        for _ in range(366 * 2):
            if self.is_working_day(cur):
                return cur
            cur += timedelta(days=direction)
        raise ValueError(f"No working day found within two years of {d}")

    def next_working_day(self, d: date, inclusive: bool = False) -> date:
        return self._step(d, +1, inclusive)

    def previous_working_day(self, d: date, inclusive: bool = False) -> date:
        return self._step(d, -1, inclusive)

    def working_days_in_week(self, key: str) -> list[date]:
        return [d for d in week_dates(key) if self.is_working_day(d)]

    def working_days_between(self, start: date, end: date) -> list[date]:
        """Working days in [start, end)."""
        out, cur = [], start
        while cur < end:
            if self.is_working_day(cur):
                out.append(cur)
            cur += timedelta(days=1)
        return out


@lru_cache(maxsize=64)
def _bank_holidays(year: int) -> dict[date, str]:
    return england_bank_holidays(year)


# --- Carry-over rules -------------------------------------------------------

def carry_over_target(today: date, cal: WorkCalendar) -> date:
    """The day open tasks should live on: the current working day.

    That is today if today is a working day, otherwise the most recent
    working day before it. So opening the app on a Saturday leaves Friday's
    tasks on Friday; they move on Monday.
    """
    return cal.previous_working_day(today, inclusive=True)


def is_overdue(entry_date: date | None, entry_week: str | None, target: date) -> bool:
    """Should an open task be carried forward to `target`?

    Dated tasks: anything before the target day (including tasks dated on
    weekends or holidays, and any number of days back).
    Week-only tasks: only once their whole week is in the past, so a task
    parked in this week's spread stays there until given a day.
    """
    if entry_date is not None:
        return entry_date < target
    if entry_week is not None:
        return week_monday(entry_week) < week_monday(week_key(target))
    return False
