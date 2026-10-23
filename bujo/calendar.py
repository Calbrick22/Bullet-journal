"""Outlook meetings: read-only, cached locally.

The app never talks to Microsoft. A source (today: a JSON file written by a
Power Automate flow and synced by OneDrive) is read whenever it changes, and
its events replace the cached ones in the window it covers. Everything else
reads the cache, so the app opens fast and works offline.

To add another source (Graph, ICS, Outlook COM), implement CalendarSource.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Protocol

from . import dates
from .db import transaction

SHOW_AS = {"free", "tentative", "busy", "oof", "workingelsewhere"}


@dataclass(frozen=True)
class Meeting:
    id: str
    subject: str
    start: datetime          # UTC; for all-day events, local midnight in UTC
    end: datetime            # UTC, exclusive
    all_day: bool = False
    location: str = ""
    show_as: str = "busy"
    cancelled: bool = False

    def local_start(self) -> datetime:
        return dates.to_local(self.start)

    def local_end(self) -> datetime:
        return dates.to_local(self.end)

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass(frozen=True)
class Export:
    events: list[Meeting]
    window_start: datetime | None = None
    window_end: datetime | None = None
    exported_at: datetime | None = None


class CalendarError(ValueError):
    pass


class CalendarSource(Protocol):
    def signature(self) -> str | None:
        """Something that changes when the source has new data; None if unavailable."""

    def load(self) -> Export:
        """Read everything the source currently has."""


# --- Power Automate JSON file ----------------------------------------------

def _instant(value: str) -> datetime:
    """Power Automate gives '2026-10-22T09:30:00.0000000' (UTC, no offset) or an
    ISO string with an offset. Seven fractional digits are trimmed for Python."""
    s = value.strip().replace("Z", "+00:00")
    if "." in s:
        head, frac = s.split(".", 1)
        tz = ""
        for sign in ("+", "-"):
            if sign in frac:
                frac, tz = frac.split(sign, 1)
                tz = sign + tz
        s = f"{head}.{frac[:6]}{tz}"
    dt = datetime.fromisoformat(s)
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _all_day_date(value: str) -> date:
    """All-day events are dates. Take the date as written when the time is
    midnight (how Outlook writes them); otherwise the local date of the instant."""
    s = value.strip()
    if "T00:00:00" in s:
        return date.fromisoformat(s[:10])
    return dates.local_today(_instant(s))


def _local_midnight_utc(d: date) -> datetime:
    return datetime.combine(d, time.min, dates.LOCAL_TZ).astimezone(timezone.utc)


def parse_event(raw: dict) -> Meeting:
    try:
        start_s = raw.get("startWithTimeZone") or raw["start"]
        end_s = raw.get("endWithTimeZone") or raw["end"]
        all_day = bool(raw.get("isAllDay", False))
        if all_day:
            start = _local_midnight_utc(_all_day_date(raw["start"]))
            end = _local_midnight_utc(_all_day_date(raw["end"]))
        else:
            start, end = _instant(start_s), _instant(end_s)
        subject = (raw.get("subject") or "").strip() or "(No subject)"
        location = raw.get("location") or ""
        if isinstance(location, dict):
            location = location.get("displayName", "")
        show_as = str(raw.get("showAs") or "busy").lower()
        cancelled = bool(raw.get("isCancelled")) or subject.lower().startswith(("canceled:", "cancelled:"))
        return Meeting(
            id=str(raw["id"]), subject=subject, start=start, end=max(end, start),
            all_day=all_day, location=str(location).strip(),
            show_as=show_as if show_as in SHOW_AS else "busy", cancelled=cancelled,
        )
    except (KeyError, TypeError, ValueError) as e:
        raise CalendarError(f"Couldn't read event {raw.get('id', '?')!r}: {e}") from e


def parse_export(data: dict | list) -> Export:
    """The flow writes {"exported_at", "window": {"start", "end"}, "events": [...]}.
    A bare list of events is accepted too (the window is then the events' span)."""
    if isinstance(data, list):
        data = {"events": data}
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise CalendarError("Calendar file has no list of events")
    events = [parse_event(e) for e in data["events"]]
    window = data.get("window") or {}
    w_start = _instant(window["start"]) if window.get("start") else None
    w_end = _instant(window["end"]) if window.get("end") else None
    if events and w_start is None:
        w_start = min(e.start for e in events)
    if events and w_end is None:
        w_end = max(e.end for e in events)
    exported = _instant(data["exported_at"]) if data.get("exported_at") else None
    return Export(events, w_start, w_end, exported)


class PowerAutomateJson:
    def __init__(self, path: Path):
        self.path = Path(path)

    def signature(self) -> str | None:
        try:
            st = self.path.stat()
        except OSError:
            return None
        return f"{st.st_mtime_ns}:{st.st_size}"

    def load(self) -> Export:
        try:
            # utf-8-sig: OneDrive/Power Automate files sometimes start with a BOM.
            return parse_export(json.loads(self.path.read_text(encoding="utf-8-sig")))
        except OSError as e:
            raise CalendarError(f"Couldn't open the calendar file: {e.strerror}") from e
        except json.JSONDecodeError as e:
            raise CalendarError(f"Calendar file isn't valid JSON (line {e.lineno})") from e


# --- Cache ------------------------------------------------------------------

def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def store(conn, export: Export) -> int:
    """Replace cached meetings in the export's window. Meetings outside it are
    kept, so past weeks still show their meetings after the window moves on."""
    with transaction(conn):
        if export.window_start and export.window_end:
            conn.execute(
                "DELETE FROM meetings WHERE start_utc < ? AND end_utc > ?",
                (_iso(export.window_end), _iso(export.window_start)),
            )
        for m in export.events:
            conn.execute(
                """INSERT INTO meetings (id, subject, start_utc, end_utc, all_day, location, show_as, cancelled)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (id) DO UPDATE SET subject = excluded.subject, start_utc = excluded.start_utc,
                     end_utc = excluded.end_utc, all_day = excluded.all_day, location = excluded.location,
                     show_as = excluded.show_as, cancelled = excluded.cancelled""",
                (m.id, m.subject, _iso(m.start), _iso(m.end), int(m.all_day), m.location, m.show_as, int(m.cancelled)),
            )
    return len(export.events)


def _row(r) -> Meeting:
    return Meeting(
        id=r["id"], subject=r["subject"],
        start=datetime.fromisoformat(r["start_utc"]), end=datetime.fromisoformat(r["end_utc"]),
        all_day=bool(r["all_day"]), location=r["location"], show_as=r["show_as"], cancelled=bool(r["cancelled"]),
    )


def meetings_between(conn, start: datetime, end: datetime, include_cancelled: bool = False) -> list[Meeting]:
    rows = conn.execute(
        "SELECT * FROM meetings WHERE start_utc < ? AND end_utc > ? ORDER BY all_day DESC, start_utc, end_utc, subject",
        (_iso(end), _iso(start)),
    )
    return [m for m in map(_row, rows) if include_cancelled or not m.cancelled]


def meetings_on(conn, d: date) -> list[Meeting]:
    start, end = dates.day_bounds_utc(d)
    return meetings_between(conn, start, end)


# --- Sync status ------------------------------------------------------------

@dataclass(frozen=True)
class Status:
    configured: bool
    exported_at: datetime | None = None   # when the flow last wrote the file
    error: str | None = None


def _get(conn, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def _set(conn, key: str, value: str | None) -> None:
    if value is None:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    else:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def sync(conn, source: CalendarSource | None) -> Status:
    """Import from the source if it changed since last time. Cheap to call on
    every page load: unchanged sources aren't read."""
    if source is None:
        return Status(configured=False)
    sig = source.signature()
    if sig is None:
        _set(conn, "calendar_error", "Calendar file not found. Is OneDrive syncing?")
    elif sig != _get(conn, "calendar_signature"):
        try:
            export = source.load()
            store(conn, export)
            _set(conn, "calendar_signature", sig)
            _set(conn, "calendar_exported_at", _iso(export.exported_at) if export.exported_at else None)
            _set(conn, "calendar_error", None)
        except CalendarError as e:
            _set(conn, "calendar_error", str(e))  # keep the cached meetings
    exported = _get(conn, "calendar_exported_at")
    return Status(True, datetime.fromisoformat(exported) if exported else None, _get(conn, "calendar_error"))
