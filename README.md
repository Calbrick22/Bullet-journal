# Bullet Journal

A small, local-first bullet journal for planning weeks and days, with Outlook
meetings shown alongside tasks (read-only). One user, one SQLite file, no server.

## Get it running on Windows

1. **Get the code onto your laptop.** On the GitHub page, click the green **Code**
   button → **Download ZIP**, then right-click the ZIP → **Extract All…** somewhere
   you'll keep it, e.g. `Documents\bullet-journal`. (With Git installed you can
   `git clone` instead, which makes updates a one-liner: `git pull`.)
2. **Double-click `Start Journal.bat`** in that folder. The first time, it sets
   things up (about a minute, needs the internet once). Then it opens the journal
   in your browser. Leave the black window open while you use it; close it to stop.
3. **Show your Outlook meetings:** open `config.toml` (made on first run, in the same
   folder) in Notepad and set `calendar_path` to your exported file. See
   `docs/calendar.md`.

Needs Python 3.11 or newer. Check with `py --version` in PowerShell.

### From a terminal instead

Python runs files relative to the folder you're *in*, so go to the project folder first:

```powershell
cd "$HOME\Documents\bullet-journal"     # wherever you extracted it
py -m venv .venv                         # once
.venv\Scripts\python.exe -m pip install -r requirements.txt   # once, and after updates
.venv\Scripts\python.exe run.py          # your journal
.venv\Scripts\python.exe run.py --demo   # a throwaway sample journal to try things out
```

Tip: in File Explorer, open the folder, click the address bar, type `powershell` and
press Enter. That opens PowerShell already in the right folder.

Your data is one file, `data\journal.sqlite`. Copy it to back up. Settings live in
`config.toml` (see `config.example.toml`). It's personal and never uploaded.

Tests: `.venv\Scripts\python.exe -m pip install -r requirements-dev.txt`, then
`.venv\Scripts\python.exe -m pytest`.

## Keyboard

`n` add (start with `*` for an event, `-` for a note) · `j`/`k` next/previous entry ·
`x` or Space tick · `>` migrate to the next working day · `m` or `<` move to a date or
week · `e` edit · `c` cancel/restore · `[`/`]` previous/next · `t` today · `w` week ·
`f` future log · `v` meetings / meetings and tasks · `?` all shortcuts.

Tests: `py -m pip install -r requirements-dev.txt`, then `py -m pytest`.

## Layout

| Path | What |
|---|---|
| `bujo/dates.py` | Pure date logic: working days, ISO weeks, Europe/London time, carry-over rules |
| `bujo/holidays.py` | England & Wales bank holidays, calculated (works offline, any year) |
| `bujo/db.py` | SQLite connection and versioned schema |
| `bujo/journal.py` | Entries, done/cancel/move, carry-over |
| `bujo/calendar.py` | Outlook meetings: Power Automate JSON reader, local cache, sync |
| `bujo/views.py` | What each screen shows (labels, trails, the fact line, Ahead) |
| `bujo/web.py`, `bujo/templates/` | The web app: server-rendered pages, plain form posts |
| `bujo/demo.py` | Sample journal for `--demo` |
| `bujo/static/css/tokens.css` | The design tokens: the only place colours and sizes are defined |
| `docs/design.md` | The dealt style, tokens and journal conventions |
| `docs/plan.md` | Milestones and decisions |
| `docs/calendar.md` | Setting up the Power Automate calendar export |

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
