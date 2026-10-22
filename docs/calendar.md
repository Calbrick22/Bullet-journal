# Calendar export: Power Automate → OneDrive

The app never talks to Microsoft directly. A scheduled cloud flow writes your
upcoming meetings to a JSON file in OneDrive; OneDrive syncs it to the laptop.

## Flow (to build in milestone 5; checked against the app's reader then)

1. **Recurrence** — every 30 minutes.
2. **Office 365 Outlook → Get calendar view of events (V3)**
   - Calendar: Calendar
   - Start time: `addDays(startOfDay(utcNow()), -7)`
   - End time: `addDays(utcNow(), 56)`
3. **Select** — map to only the fields the app needs: `id`, `subject`, `start`,
   `end`, `isAllDay`, `location`, `showAs`, `isCancelled`.
4. **OneDrive for Business → Create file** (overwrite) at
   `/Apps/BulletJournal/calendar.json` with `{"exported_at": utcNow(), "events": <Select output>}`.

Then set the synced local path (e.g.
`C:\Users\<you>\OneDrive - <Org>\Apps\BulletJournal\calendar.json`) in `config.toml`,
which is git-ignored.

Things to confirm on the laptop: OneDrive sync is on, and you can create a
scheduled cloud flow using the Outlook and OneDrive connectors.
