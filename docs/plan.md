# Plan and decisions

## Decisions
- **Stack:** Python 3.10+, standard-library `sqlite3`, `tzdata` for Europe/London
  on Windows. Web layer (milestone 3): FastAPI + Jinja2 + htmx as a static file.
- **Calendar source:** a scheduled Power Automate flow writes upcoming events to a
  JSON file in OneDrive; OneDrive syncs it locally and the app reads it. No Graph
  app registration or IT consent needed. Behind a `CalendarSource` interface.
- **Working days:** Mon–Fri, England & Wales bank holidays, per-date overrides
  for leave or worked days.
- **Design:** all UI via the design-taste-frontend skill, app-screen run; style
  dealt once at milestone 2 ("fresh, colourful but not too bright"), recorded in
  `docs/design.md` and one tokens CSS file.

## Milestones
1. ✅ Data model, date logic, carry-over, tests
2. Design: deal app style, tokens, base CSS, static mock of the weekly spread
3. Weekly spread + daily view, quick-add, done/cancel, carry-over on open
4. Forward planning (future days/weeks), migrate/reschedule, keyboard shortcuts
5. Calendar: Power Automate flow, JSON reader, local cache, meetings in views
6. Settings (working days, leave), backup script, polish
