"""SQLite connection and schema. All data lives in one file.

Schema changes are added to MIGRATIONS (never edit an applied one);
PRAGMA user_version records how many have run.
"""

import sqlite3
from pathlib import Path

MIGRATIONS = [
    # 1: entries, day overrides, settings
    """
    CREATE TABLE entries (
        id            INTEGER PRIMARY KEY,
        kind          TEXT NOT NULL CHECK (kind IN ('task', 'event', 'note')),
        text          TEXT NOT NULL,
        state         TEXT NOT NULL DEFAULT 'open'
                      CHECK (state IN ('open', 'done', 'migrated', 'scheduled', 'cancelled')),
        entry_date    TEXT,              -- local date YYYY-MM-DD
        entry_week    TEXT,              -- ISO week '2026-W43' when no day yet
        position      INTEGER NOT NULL DEFAULT 0,
        moved_from_id INTEGER UNIQUE REFERENCES entries(id),  -- the entry this is a copy of
        origin_id     INTEGER REFERENCES entries(id),         -- first entry in the chain
        carry_count   INTEGER NOT NULL DEFAULT 0,             -- times migrated so far
        created_at    TEXT NOT NULL,     -- UTC ISO 8601
        updated_at    TEXT NOT NULL,
        completed_at  TEXT,
        CHECK ((entry_date IS NULL) <> (entry_week IS NULL))
    );
    CREATE INDEX entries_by_date ON entries (entry_date, position);
    CREATE INDEX entries_by_week ON entries (entry_week, position);
    CREATE INDEX entries_open ON entries (kind, state);

    -- Per-date exceptions to the normal working pattern.
    CREATE TABLE day_overrides (
        date    TEXT PRIMARY KEY,        -- local date YYYY-MM-DD
        working INTEGER NOT NULL CHECK (working IN (0, 1)),
        reason  TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
    # 2: cached Outlook meetings (read-only copy; see calendar.py)
    """
    CREATE TABLE meetings (
        id        TEXT PRIMARY KEY,      -- Outlook's event id
        subject   TEXT NOT NULL,
        start_utc TEXT NOT NULL,
        end_utc   TEXT NOT NULL,
        all_day   INTEGER NOT NULL DEFAULT 0,
        location  TEXT NOT NULL DEFAULT '',
        show_as   TEXT NOT NULL DEFAULT 'busy',
        cancelled INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX meetings_by_start ON meetings (start_utc);
    """,
    # 3: entries can also live on a list (backlog / ongoing) instead of a day or week.
    # SQLite can't change a CHECK constraint, so the table is rebuilt.
    """
    CREATE TABLE entries_new (
        id            INTEGER PRIMARY KEY,
        kind          TEXT NOT NULL CHECK (kind IN ('task', 'event', 'note')),
        text          TEXT NOT NULL,
        state         TEXT NOT NULL DEFAULT 'open'
                      CHECK (state IN ('open', 'done', 'migrated', 'scheduled', 'cancelled')),
        entry_date    TEXT,              -- local date YYYY-MM-DD
        entry_week    TEXT,              -- ISO week '2026-W43' when no day yet
        entry_list    TEXT CHECK (entry_list IN ('backlog', 'ongoing')),
        position      INTEGER NOT NULL DEFAULT 0,
        moved_from_id INTEGER UNIQUE REFERENCES entries(id),
        origin_id     INTEGER REFERENCES entries(id),
        carry_count   INTEGER NOT NULL DEFAULT 0,
        created_at    TEXT NOT NULL,
        updated_at    TEXT NOT NULL,
        completed_at  TEXT,
        CHECK ((entry_date IS NOT NULL) + (entry_week IS NOT NULL) + (entry_list IS NOT NULL) = 1)
    );
    INSERT INTO entries_new (id, kind, text, state, entry_date, entry_week, position, moved_from_id,
                             origin_id, carry_count, created_at, updated_at, completed_at)
        SELECT id, kind, text, state, entry_date, entry_week, position, moved_from_id,
               origin_id, carry_count, created_at, updated_at, completed_at FROM entries;
    DROP TABLE entries;
    ALTER TABLE entries_new RENAME TO entries;
    CREATE INDEX entries_by_date ON entries (entry_date, position);
    CREATE INDEX entries_by_week ON entries (entry_week, position);
    CREATE INDEX entries_by_list ON entries (entry_list, position);
    CREATE INDEX entries_open ON entries (kind, state);
    """,
    # 4: meeting categories, for colouring meetings (and timesheets)
    """
    CREATE TABLE categories (
        id       INTEGER PRIMARY KEY,
        name     TEXT NOT NULL UNIQUE COLLATE NOCASE,
        colour   TEXT NOT NULL,          -- a palette key from tokens.css, e.g. 'mint'
        archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
        position INTEGER NOT NULL DEFAULT 0
    );
    -- "Remember by meeting name": every meeting with this subject gets the category
    CREATE TABLE subject_categories (
        subject_key TEXT PRIMARY KEY,    -- normalised subject (trimmed, lower case)
        category_id INTEGER NOT NULL REFERENCES categories(id)
    );
    -- One occurrence set differently from its name's category (NULL = none for this one)
    CREATE TABLE meeting_categories (
        meeting_id  TEXT PRIMARY KEY,    -- Outlook id; not a foreign key, meetings are re-imported
        category_id INTEGER REFERENCES categories(id)
    );
    """,
    # 5: a note's details: formatted text, bookmark, category. Optional: a note
    # without a row here is just its title.
    """
    CREATE TABLE note_details (
        entry_id      INTEGER PRIMARY KEY REFERENCES entries(id),
        body          TEXT NOT NULL DEFAULT '',   -- sanitised HTML (see notes.sanitise)
        bookmarked    INTEGER NOT NULL DEFAULT 0 CHECK (bookmarked IN (0, 1)),
        bookmarked_at TEXT,
        category_id   INTEGER REFERENCES categories(id),
        updated_at    TEXT
    );
    CREATE INDEX note_bookmarks ON note_details (bookmarked);
    """,
]


def connect(path: str | Path) -> sqlite3.Connection:
    """Open (and create/upgrade if needed) the journal database.

    Autocommit mode: callers use `transaction()` for multi-step writes.
    """
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def _statements(sql: str) -> list[str]:
    """Split a script into statements, safely: a ';' inside a comment or a
    string doesn't end a statement (sqlite3.complete_statement decides)."""
    out, buf = [], ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                out.append(buf)
            buf = ""
    if buf.strip() and not all(l.strip().startswith("--") or not l.strip() for l in buf.splitlines()):
        raise ValueError(f"Unfinished SQL statement: {buf.strip()[:60]}")
    return out


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= len(MIGRATIONS):
        return
    # Table rebuilds need foreign keys off (it can only change outside a transaction);
    # the check afterwards proves nothing was broken.
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        for i, sql in enumerate(MIGRATIONS[version:], start=version + 1):
            with transaction(conn):
                for statement in _statements(sql):
                    conn.execute(statement)
                if conn.execute("PRAGMA foreign_key_check").fetchall():
                    raise sqlite3.IntegrityError(f"Migration {i} broke a link between entries")
                conn.execute(f"PRAGMA user_version = {i}")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


class transaction:
    """`with transaction(conn):` — BEGIN IMMEDIATE ... COMMIT/ROLLBACK.

    IMMEDIATE takes the write lock up front, so two carry-overs running at
    once (e.g. two browser tabs) are serialised rather than interleaved.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        self.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        return False
