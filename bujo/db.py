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


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for i, sql in enumerate(MIGRATIONS[version:], start=version + 1):
        with transaction(conn):
            for statement in sql.split(";"):
                if statement.strip():
                    conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {i}")


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
