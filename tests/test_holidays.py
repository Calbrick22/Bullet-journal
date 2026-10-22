from datetime import date

import pytest

from bujo.holidays import easter_sunday, england_bank_holidays

# Published England & Wales dates (gov.uk/bank-holidays).
PUBLISHED = {
    2020: ["01-01", "04-10", "04-13", "05-08", "05-25", "08-31", "12-25", "12-28"],
    2021: ["01-01", "04-02", "04-05", "05-03", "05-31", "08-30", "12-27", "12-28"],
    2022: ["01-03", "04-15", "04-18", "05-02", "06-02", "06-03", "08-29", "09-19", "12-26", "12-27"],
    2023: ["01-02", "04-07", "04-10", "05-01", "05-08", "05-29", "08-28", "12-25", "12-26"],
    2024: ["01-01", "03-29", "04-01", "05-06", "05-27", "08-26", "12-25", "12-26"],
    2025: ["01-01", "04-18", "04-21", "05-05", "05-26", "08-25", "12-25", "12-26"],
    2026: ["01-01", "04-03", "04-06", "05-04", "05-25", "08-31", "12-25", "12-28"],
    2027: ["01-01", "03-26", "03-29", "05-03", "05-31", "08-30", "12-27", "12-28"],
}


@pytest.mark.parametrize("year", PUBLISHED)
def test_matches_published_dates(year):
    expected = [date.fromisoformat(f"{year}-{md}") for md in PUBLISHED[year]]
    assert list(england_bank_holidays(year)) == expected


@pytest.mark.parametrize("year,expected", [
    (2019, date(2019, 4, 21)), (2024, date(2024, 3, 31)),
    (2026, date(2026, 4, 5)), (2038, date(2038, 4, 25)),
])
def test_easter(year, expected):
    assert easter_sunday(year) == expected


def test_substitute_names():
    hols = england_bank_holidays(2021)  # Christmas Sat, Boxing Day Sun
    assert hols[date(2021, 12, 27)] == "Christmas Day (substitute day)"
    assert hols[date(2021, 12, 28)] == "Boxing Day (substitute day)"


def test_never_on_a_weekend():
    for year in range(2010, 2060):
        assert all(d.weekday() < 5 for d in england_bank_holidays(year)), year
