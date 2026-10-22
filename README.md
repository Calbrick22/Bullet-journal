# Bullet Journal

A small, local-first bullet journal for planning weeks and days, with Outlook
meetings shown alongside tasks (read-only). One user, one SQLite file, no server.

## Setup (Windows, PowerShell)

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r requirements-dev.txt
py -m pytest
```

Requires Python 3.10+. The app itself (milestone 3) will start with `py run.py`.

## Layout

| Path | What |
|---|---|
| `bujo/dates.py` | Pure date logic: working days, ISO weeks, Europe/London time, carry-over rules |
| `bujo/holidays.py` | England & Wales bank holidays, calculated (works offline, any year) |
| `bujo/db.py` | SQLite connection and versioned schema |
| `bujo/journal.py` | Entries, done/cancel/move, carry-over |
| `bujo/static/css/tokens.css` | The design tokens: the only place colours and sizes are defined |
| `bujo/static/mock/week.html` | Static weekly-spread mock (open it straight in a browser) |
| `docs/design.md` | The dealt style, tokens and journal conventions |
| `docs/plan.md` | Milestones and decisions |
| `docs/calendar.md` | Power Automate → OneDrive calendar export setup |

## Behaviour notes

- **Carry-over** moves every open task dated before the *current working day*
  to it, in one hop. On a weekend or holiday the current working day is the
  last one before it, so nothing moves until you're back. Originals are marked
  `>` and linked to their copy; `carry_count` says how often it has rolled.
  Running it repeatedly is safe.
- **Week-only tasks** stay in their week's spread until given a day; if the week
  ends first, they carry over like any other task.
- **Moving** an open task to a later date/week marks it scheduled (`<`); moving
  it to today or earlier marks it migrated (`>`). Giving a week-only task a day
  in its own week just places it.
- Dates in the journal are local calendar dates. Timestamps are stored in UTC.
