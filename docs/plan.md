# Plan and decisions

## Decisions
- **Stack:** Python 3.11+, standard-library `sqlite3`, `tzdata` for Europe/London
  on Windows. Web: FastAPI + Jinja2, plain form posts that work without JavaScript,
  plus ~50 lines of vanilla JS (`static/js/app.js`) to update in place. No htmx needed.
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
2. ✅ Design: deal app style, tokens, base CSS, static mock of the weekly spread
3. ✅ Weekly spread + daily view, quick-add, done/cancel, carry-over on open
4. ✅ Forward planning (future log), migrate/reschedule, edit, keyboard shortcuts;
   week view toggle: meetings only (default, a time grid) / meetings and tasks
5. Calendar: ✅ JSON reader, local cache, meetings in week/day views (built early for the
   week toggle). Left: build the flow on your account (`docs/calendar.md`) and check
   it against a real export
6. ✅ Settings (categories, working days, leave, start with Windows, backups); plus
   requests: backlog + ongoing lists, meeting categories by name, start at login
7. Next: check against a real Power Automate export; anything you notice in daily use
