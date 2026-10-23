import json
from datetime import date, datetime, timezone

import pytest

from bujo import calendar as cal
from bujo.db import connect

UTC = timezone.utc


def ev(id, start, end, **kw):
    return {"id": id, "subject": kw.pop("subject", f"Meeting {id}"), "start": start, "end": end, **kw}


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "j.sqlite")
    yield c
    c.close()


# --- Parsing ----------------------------------------------------------------

def test_power_automate_utc_strings_with_seven_digits():
    m = cal.parse_event(ev("a", "2026-10-22T08:30:00.0000000", "2026-10-22T09:00:00.0000000"))
    assert m.start == datetime(2026, 10, 22, 8, 30, tzinfo=UTC)
    assert m.local_start().strftime("%H:%M") == "09:30"  # BST
    assert m.minutes == 30


def test_with_timezone_fields_preferred():
    m = cal.parse_event(ev("a", "ignored", "ignored",
                           startWithTimeZone="2026-12-01T09:00:00+00:00", endWithTimeZone="2026-12-01T10:15:00+00:00"))
    assert m.local_start().strftime("%H:%M") == "09:00" and m.minutes == 75


def test_offsets_and_z():
    m = cal.parse_event(ev("a", "2026-10-22T10:30:00+01:00", "2026-10-22T09:45:00Z"))
    assert m.start == datetime(2026, 10, 22, 9, 30, tzinfo=UTC) and m.minutes == 15


def test_all_day_is_the_written_date_in_local_time():
    m = cal.parse_event(ev("a", "2026-10-23T00:00:00.0000000", "2026-10-24T00:00:00.0000000", isAllDay=True))
    assert m.all_day
    assert m.local_start() == datetime(2026, 10, 23, 0, 0, tzinfo=m.local_start().tzinfo)
    assert m.local_end().date() == date(2026, 10, 24)


def test_cancelled_and_show_as_and_location_object():
    m = cal.parse_event(ev("a", "2026-10-22T08:00:00", "2026-10-22T09:00:00", subject="Canceled: Sync",
                           showAs="Tentative", location={"displayName": "Room 3.12"}))
    assert m.cancelled and m.show_as == "tentative" and m.location == "Room 3.12"
    assert cal.parse_event(ev("b", "2026-10-22T08:00:00", "2026-10-22T09:00:00", showAs="weird")).show_as == "busy"


def test_bad_event_names_it():
    with pytest.raises(cal.CalendarError, match="'x1'"):
        cal.parse_event({"id": "x1", "subject": "No times"})


def test_export_window_defaults_to_event_span():
    exp = cal.parse_export([ev("a", "2026-10-20T08:00:00", "2026-10-20T09:00:00"),
                            ev("b", "2026-10-22T08:00:00", "2026-10-22T09:00:00")])
    assert exp.window_start.day == 20 and exp.window_end.day == 22


# --- Cache and sync ---------------------------------------------------------

def test_meetings_on_a_day_use_local_bounds(conn):
    cal.store(conn, cal.parse_export({"events": [
        ev("late", "2026-10-21T23:30:00", "2026-10-22T00:00:00"),   # 00:30 BST on the 22nd
        ev("day", "2026-10-22T13:00:00", "2026-10-22T14:00:00"),
        ev("gone", "2026-10-22T15:00:00", "2026-10-22T16:00:00", isCancelled=True),
        ev("allday", "2026-10-22T00:00:00", "2026-10-23T00:00:00", isAllDay=True),
    ]}))
    assert [m.id for m in cal.meetings_on(conn, date(2026, 10, 22))] == ["allday", "late", "day"]
    assert [m.id for m in cal.meetings_on(conn, date(2026, 10, 21))] == []


def test_meetings_across_the_clock_change(conn):
    # 25 Oct 2026: clocks go back. 09:00 GMT that day is 09:00 UTC.
    cal.store(conn, cal.parse_export([ev("a", "2026-10-25T09:00:00", "2026-10-25T10:00:00"),
                                      ev("b", "2026-10-24T23:30:00", "2026-10-25T00:00:00")]))  # 00:30 BST on 25th
    got = cal.meetings_on(conn, date(2026, 10, 25))
    assert [(m.id, m.local_start().strftime("%H:%M")) for m in got] == [("b", "00:30"), ("a", "09:00")]


def test_store_replaces_window_but_keeps_older_history(conn):
    cal.store(conn, cal.parse_export({"window": {"start": "2026-10-12T00:00:00Z", "end": "2026-10-19T00:00:00Z"},
                                      "events": [ev("old", "2026-10-13T08:00:00", "2026-10-13T09:00:00")]}))
    cal.store(conn, cal.parse_export({"window": {"start": "2026-10-19T00:00:00Z", "end": "2026-12-14T00:00:00Z"},
                                      "events": [ev("a", "2026-10-20T08:00:00", "2026-10-20T09:00:00"),
                                                 ev("b", "2026-10-21T08:00:00", "2026-10-21T09:00:00")]}))
    # b is deleted in Outlook; the next export no longer has it
    cal.store(conn, cal.parse_export({"window": {"start": "2026-10-19T00:00:00Z", "end": "2026-12-14T00:00:00Z"},
                                      "events": [ev("a", "2026-10-20T09:00:00", "2026-10-20T10:00:00")]}))
    everything = cal.meetings_between(conn, datetime(2026, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC))
    assert [(m.id, m.start.hour) for m in everything] == [("old", 8), ("a", 9)]


def write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_sync_reads_only_when_file_changes(conn, tmp_path):
    f = tmp_path / "calendar.json"
    src = cal.PowerAutomateJson(f)
    st = cal.sync(conn, src)
    assert st.configured and "not found" in st.error

    write(f, {"exported_at": "2026-10-22T07:45:00Z", "events": [ev("a", "2026-10-22T08:00:00", "2026-10-22T09:00:00")]})
    st = cal.sync(conn, src)
    assert st.error is None and st.exported_at == datetime(2026, 10, 22, 7, 45, tzinfo=UTC)
    assert len(cal.meetings_on(conn, date(2026, 10, 22))) == 1

    class Spy(cal.PowerAutomateJson):
        loads = 0
        def load(self):
            Spy.loads += 1
            return super().load()
    spy = Spy(f)
    cal.sync(conn, spy)
    assert Spy.loads == 0  # unchanged file: not read again


def test_sync_keeps_cache_on_a_broken_file(conn, tmp_path):
    f = tmp_path / "calendar.json"
    write(f, [ev("a", "2026-10-22T08:00:00", "2026-10-22T09:00:00")])
    cal.sync(conn, cal.PowerAutomateJson(f))
    f.write_text("{ half a file", encoding="utf-8")
    st = cal.sync(conn, cal.PowerAutomateJson(f))
    assert "isn't valid JSON" in st.error
    assert len(cal.meetings_on(conn, date(2026, 10, 22))) == 1


def test_sync_accepts_a_bom(conn, tmp_path):
    f = tmp_path / "calendar.json"
    f.write_bytes(b"\xef\xbb\xbf" + json.dumps([ev("a", "2026-10-22T08:00:00", "2026-10-22T09:00:00")]).encode())
    assert cal.sync(conn, cal.PowerAutomateJson(f)).error is None


def test_not_configured(conn):
    assert cal.sync(conn, None) == cal.Status(configured=False)
