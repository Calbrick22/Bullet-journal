# Design

All UI follows the **tasteskill** (design-taste-frontend) app-screen run:
`references/app-screens.md`, dealt with `draw.mjs --app`, checked with `lint.mjs --app`
and `inspect.mjs --app`. Every screen uses **`bujo/static/css/tokens.css` only**: no raw
colours or sizes anywhere else.

## The style (dealt once, milestone 2)

- **Style:** `editorial-greeting` (light), seed `635589795`, dealt 2026-10-22, kind `workspace`.
  Sheet: `.taste-skill/app/direction.json` (reprint with `node <skill>/scripts/draw.mjs --show`).
- **Why this one:** of the two styles dealt, it's the one that suits a personal journal. Its
  greeting-as-title reads like a dated page, and its tonal panels can carry colour.
  `achromatic-ledger` keeps colour out of the screen entirely, which contradicts
  "fresh, colourful".
- **The move:** a serif greeting as the h1, in a centred 1100px column on a 12-column grid
  (77px columns, 16px gutters); figures at regular weight on tonal panels; one white
  inner card (today).
- **Face:** the grey line under the greeting states today's facts, computed from the
  data ("4 meetings, the first at 09:30 · 3 tasks came over, one on its 4th day").
- **Signature element:** the *carry trail* (Mon › Tue › Wed › Thu): a task's migration
  history, straight from `origin_id` / `carry_count`.

## Tokens

| Role | Value | Use |
|---|---|---|
| ground / surface / raised | `#ffffff` / `#f9f9f9` / `#ffffff` | page / panels / today |
| text / muted | `#1f201d` / `#636361` | ink / secondary (5.6:1) |
| accent | `#1b6e66` deep teal | today, focus. Under 2% of pixels |
| meeting | bg `#eaf2f8`, ink `#1c4a6e` | Outlook meetings (read-only) |
| unplaced | bg `#eaf4f1` | this week, no day yet |
| carried | pill `#fff4d6` / `#8a3c0b` | carried-over tasks |
| primary | `#1f201d` | the one filled button (Add) |
| type | Instrument Sans 400/500/600; Instrument Serif 400 (greeting only) | stored in `bujo/static/fonts` (SIL OFL), so the app works offline |
| sizes | 48 (greeting; 28 on phone) / 14 / 12 | |
| shape | card radius 22, rows 12, controls pill; one 16px gutter | |

## Journal conventions

Changed at your request in milestone 3: tasks are **tick boxes**, events a **star**,
notes a **dash**. Every mark sits in the same fixed 16px slot, so text always lines up.

| Entry | Mark | Text |
|---|---|---|
| Task, open | empty tick box (click, or Space when focused) | ink |
| Task, done | ticked box, teal fill, white tick | grey, struck through |
| Task, cancelled | dashed empty box | grey, struck through, "cancelled" |
| Task, migrated | `>` | grey, "to Thu" |
| Task, scheduled | `<` | grey, "to 5 Nov" |
| Event | outline star (drawn, so it renders the same everywhere) | ink |
| Note | `–` (en dash, semibold) | ink |

- **Meetings vs tasks** are told apart by shape, not colour alone: a meeting (milestone 5)
  is a filled block that starts with its time and has no tick box.
- **States:** today = white card, teal edge, the word "Today". Carried over = amber pill
  "4th day", plus the trail (Mon › Tue › Wed › Thu) in the day view and Rolling over.
  Future-scheduled = quiet grey "planned on 9 Oct".

## Week view (milestone 4)

- **Two modes, chosen by a toggle and remembered (cookie):** *Meetings* (default) and
  *Meetings and tasks*. `v` switches.
- **Meetings mode is a time grid:** 08:00–18:00 (widened for earlier or later meetings),
  56px an hour, an hour gutter on the left, faint hour lines, clashing meetings side by
  side. Past meetings turn grey; today is the white column with a 2px teal line at the
  current time. Blocks under 44px show only the subject, with the time on hover and for
  screen readers, since the position already gives the time. Phones get the same
  meetings as a list per day, today first.
- **Meeting marks** (shape as well as fill): busy filled; tentative dashed edge; free /
  working elsewhere outline only; out of office a darker step.

## Backlog, ongoing and categories (milestone 6)

- **Ongoing** uses the "no day yet" tint (pale teal): it's work without a day. It sits on
  the day view's side column (with a 5-row Backlog preview and Start, on today only) and beside the Backlog, which is the screen's main block (8 + 4).
- **Meeting categories** take one of eight pastels, each a fill, a one-step-darker edge
  and dark text at about 7:1 or better: sky, mint, peach, butter, rose, sage, lime, aqua.
  Peach and butter are a step deeper than a typical pastel, and lime replaced sand,
  because the house rules ban yellow-cream backgrounds (hue 22–62°, lightness over 88%).
  Untagged meetings are a neutral grey-blue, so they stand out at timesheet time.
  Tentative keeps its dashed edge over a category. Past meetings keep their category
  colour; untagged past meetings turn grey. The category name shows on roomy blocks
  and in every block's tooltip and accessible name.
- **Settings** follows the app-screen settings pattern: a 4-column label and help text
  beside an 8-column panel, sections split by a rule, one Save per panel.

## Departures from the sheet

- **No count tiles.** The home pattern's four KPI tiles are left out: the greeting's fact
  line carries those figures, and the tiles pushed today below the fold.
- **`app-title-size` WARN accepted:** the sheet sets this style's greeting in serif at
  48px. It drops to 28px on a phone.

## Gate log

- Fix + backlog on today (day view): lint 0/0; inspect 0 FAIL, WARNs as before (title
  size; `ragged-row`, the side column now holds four short lists). In-browser: day task →
  Backlog and → Ongoing render with "to Backlog/Ongoing", Start from today's Backlog panel.

- Milestone 6 (`--demo`): `lint.mjs --app` 0 FAIL / 0 WARN. `inspect.mjs --app` at
  1440/768/390 on all six screens: 0 FAIL. WARNs accepted: title size (all), day
  `ragged-row` (independent lists), Backlog `hero-void` (the demo backlog is four items;
  the screen fills as a real backlog grows). Fixed: cream-range category fills (peach,
  butter, sand), Backlog layout (now backlog 8 + ongoing/finished 4, rows level), a lint
  false alarm from the word "shadow" in a comment. In-browser: tag by name, per-meeting
  override via Enter, Start from backlog (offers Today/Ongoing/next week/date/week),
  add to backlog from the day view, category colour preview, add leave, b/s keys; no
  console errors.

- Milestone 4 (`--demo`, today pinned to Thu 22 Oct 09:00): `lint.mjs --app` 0 FAIL,
  1 WARN (dialog shadow, marked deliberate: dialogs float). `inspect.mjs --app` at
  1440/768/390 on week (meetings), week (all), day and future log: 0 FAIL each; WARNs:
  title size (all, accepted) and day-view `ragged-row` (accepted: two independent lists
  whose lengths change daily). Fixed across three rounds: the demo clock (now pinned with
  the date), past meetings greyed instead of faded, the meetings week rebuilt as a time
  grid (was a void), short meetings clipped, 12px text share, a text block at the 768px
  edge, the phone future-log composer. In-browser (Playwright): j/k, x, e, >, m, n with
  the `*` prefix, ?, w, v, ], f all work, focus kept, no console errors.

- Milestone 3 (live app, `--demo` data, today pinned to 2026-10-22): `lint.mjs --app` on
  templates, CSS and JS: 0 FAIL / 0 WARN. `inspect.mjs --app` at 1440/768/390: week and
  day each 0 FAIL, 1 WARN (title size, above). Three look-and-fix rounds: day view void
  and ragged column (fixed with the carry trail and a "Next" panel), phone composer order,
  tablet side panels. In-browser check (Playwright): tick/untick with Space keeps focus,
  quick-add keeps the cursor and kind, no full reloads, no console errors.

- Milestone 2 (`bujo/static/mock/week.html`): `lint.mjs --app` 0 FAIL / 0 WARN;
  `inspect.mjs --app` at 1440/768/390: 0 FAIL, 1 WARN (above). Three look-and-fix rounds.
  The inspector runs Chromium as root here, so it was launched through a wrapper adding
  `--no-sandbox` (`CHROME_PATH`).
