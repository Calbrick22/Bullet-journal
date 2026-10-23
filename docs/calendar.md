# Calendar: Power Automate → OneDrive → the journal

The app never talks to Microsoft. A scheduled cloud flow in your Microsoft 365 account
writes your meetings to a JSON file in OneDrive; OneDrive syncs it to the laptop; the
app reads it whenever it changes (`bujo/calendar.py`) and keeps a local copy in the
journal database, so it opens fast and works offline. Nothing is ever written back.

## 1. Build the flow (make.powerautomate.com, about 10 minutes)

These steps are written from the connectors' documentation and haven't been run on
your tenant yet. The app's reader is tested against the format below, and it's
deliberately tolerant. If a step's name or option differs, the first real export
will show what to adjust.

Create → **Scheduled cloud flow**, name it "Journal calendar export", repeat every
**30 minutes**. Then add these steps:

1. **Office 365 Outlook → Get calendar view of events (V3)**
   - Calendar id: *Calendar*
   - Start Time: `addDays(startOfDay(utcNow()), -7)`
   - End Time: `addDays(startOfDay(utcNow()), 56)`
2. **Data operation → Select**
   - From: `value` (from step 1)
   - Map (switch to text mode and paste):
     ```
     {"id": @{item()?['id']}, "subject": @{item()?['subject']}, "start": @{item()?['start']},
      "end": @{item()?['end']}, "isAllDay": @{item()?['isAllDay']}, "location": @{item()?['location']},
      "showAs": @{item()?['showAs']}}
     ```
     (Or add the seven keys in the key/value table and pick each from Dynamic content.)
3. **OneDrive for Business → Create file**
   - Folder path: `/Apps/BulletJournal`
   - File name: `calendar.json`
   - File content (expression):
     ```
     concat('{"exported_at":"', utcNow(), '","window":{"start":"', addDays(startOfDay(utcNow()), -7),
       '","end":"', addDays(startOfDay(utcNow()), 56), '"},"events":', string(body('Select')), '}')
     ```
   - In the action's settings, allow it to **replace** an existing file. (If your tenant's
     version has no replace option, use **Update file** on the same path after the first run.)

Run it once by hand and check that `calendar.json` appears in OneDrive.

## 2. Point the journal at it

Create `config.toml` next to `run.py` (it's git-ignored):

```toml
calendar_path = 'C:\Users\<you>\OneDrive - <Your Org>\Apps\BulletJournal\calendar.json'
```

Use single quotes so the backslashes are kept. Restart `py run.py`.

## What the app understands

```json
{"exported_at": "2026-10-22T07:45:00Z",
 "window": {"start": "2026-10-15T00:00:00Z", "end": "2026-12-17T00:00:00Z"},
 "events": [{"id": "AAMk…", "subject": "Ops review", "start": "2026-10-22T10:00:00.0000000",
             "end": "2026-10-22T11:00:00.0000000", "isAllDay": false, "location": "Room 3.12",
             "showAs": "busy"}]}
```

- Times are UTC as Power Automate writes them (seven decimals, no offset); offsets and
  `startWithTimeZone` are accepted too. All-day events keep their written date.
- Each import **replaces the cached meetings inside `window`**, so meetings you delete
  or decline in Outlook disappear; meetings from before the window stay as history.
- Cancelled meetings (`isCancelled`, or a "Canceled:" subject) are hidden.
- `showAs`: busy = filled block; tentative = dashed edge; free / working elsewhere =
  outline; out of office = darker. Only busy, tentative and out of office count as
  "booked" time.
- A broken or half-synced file is ignored and the last good meetings stay; the sidebar
  says what went wrong. If the export is more than 2 hours old the sidebar says
  "not updating?".

## Swapping the source later

Anything that implements `CalendarSource` (`signature()` and `load()` returning an
`Export`) can replace the Power Automate file: Microsoft Graph, an ICS URL or Outlook
on the desktop. Nothing else in the app changes.
