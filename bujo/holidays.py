"""England & Wales bank holidays, calculated from the rules.

Computed rather than downloaded so the app works offline for any year.
One-off changes (jubilees, coronations, moved holidays) are listed in
SPECIAL below. Anything announced in future that isn't here can be added
as a non-working day in the app, or to SPECIAL.
"""

from datetime import date, timedelta


def easter_sunday(year: int) -> date:
    """Gregorian Easter (anonymous Gregorian / Meeus algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _first_monday(year: int, month: int) -> date:
    d = date(year, month, 1)
    return d + timedelta(days=(0 - d.weekday()) % 7)


def _last_monday(year: int, month: int) -> date:
    next_month = date(year + month // 12, month % 12 + 1, 1)
    d = next_month - timedelta(days=1)
    return d - timedelta(days=d.weekday())


# Year -> (dates removed from the usual rules, dates added)
SPECIAL: dict[int, tuple[dict[date, str], dict[date, str]]] = {
    2011: ({}, {date(2011, 4, 29): "Royal wedding"}),
    2012: (
        {date(2012, 5, 28): "Spring bank holiday"},
        {date(2012, 6, 4): "Spring bank holiday", date(2012, 6, 5): "Diamond Jubilee"},
    ),
    2020: (
        {date(2020, 5, 4): "Early May bank holiday"},
        {date(2020, 5, 8): "Early May bank holiday (VE day)"},
    ),
    2022: (
        {date(2022, 5, 30): "Spring bank holiday"},
        {
            date(2022, 6, 2): "Spring bank holiday",
            date(2022, 6, 3): "Platinum Jubilee",
            date(2022, 9, 19): "State Funeral of Queen Elizabeth II",
        },
    ),
    2023: ({}, {date(2023, 5, 8): "Coronation of King Charles III"}),
}


def _substitute(fixed: list[tuple[date, str]], taken: dict[date, str]) -> None:
    """Add fixed-date holidays, moving weekend ones to the next free weekday."""
    for d, name in fixed:
        if d.weekday() < 5:
            taken[d] = name
    for d, name in fixed:
        if d.weekday() >= 5:
            sub = d + timedelta(days=1)
            while sub.weekday() >= 5 or sub in taken:
                sub += timedelta(days=1)
            taken[sub] = f"{name} (substitute day)"


def england_bank_holidays(year: int) -> dict[date, str]:
    easter = easter_sunday(year)
    days: dict[date, str] = {
        easter - timedelta(days=2): "Good Friday",
        easter + timedelta(days=1): "Easter Monday",
        _first_monday(year, 5): "Early May bank holiday",
        _last_monday(year, 5): "Spring bank holiday",
        _last_monday(year, 8): "Summer bank holiday",
    }
    _substitute([(date(year, 1, 1), "New Year's Day")], days)
    _substitute(
        [(date(year, 12, 25), "Christmas Day"), (date(year, 12, 26), "Boxing Day")], days
    )
    removed, added = SPECIAL.get(year, ({}, {}))
    for d in removed:
        days.pop(d, None)
    days.update(added)
    return dict(sorted(days.items()))
