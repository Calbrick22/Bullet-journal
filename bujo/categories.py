"""Meeting categories: your own names, each with a pastel colour.

A category is remembered by meeting name (every "Weekly ops stand-up" gets
it), and any single occurrence can be set differently. Archived categories
leave the picker but keep colouring the meetings already tagged with them.
"""

from dataclasses import dataclass

from .calendar import Meeting
from .db import transaction

# Palette keys; the colours themselves live in tokens.css (--cat-<key>-bg/-edge/-ink).
PALETTE = {
    "sky": "Sky", "mint": "Mint", "peach": "Peach", "butter": "Butter",
    "rose": "Rose", "sage": "Sage", "lime": "Lime", "aqua": "Aqua",
}
MAX_NAME = 40


class CategoryError(ValueError):
    pass


@dataclass(frozen=True)
class Category:
    id: int
    name: str
    colour: str
    archived: bool


def subject_key(subject: str) -> str:
    return " ".join(subject.split()).casefold()


def _row(r) -> Category:
    return Category(r["id"], r["name"], r["colour"], bool(r["archived"]))


def all_categories(conn, include_archived: bool = True) -> list[Category]:
    sql = "SELECT * FROM categories" + ("" if include_archived else " WHERE archived = 0") + " ORDER BY archived, position, id"
    return [_row(r) for r in conn.execute(sql)]


def get(conn, category_id: int) -> Category:
    r = conn.execute("SELECT * FROM categories WHERE id = ?", (category_id,)).fetchone()
    if r is None:
        raise CategoryError("No such category")
    return _row(r)


def _clean(name: str, colour: str) -> tuple[str, str]:
    name = " ".join(name.split())
    if not name:
        raise CategoryError("Give the category a name")
    if len(name) > MAX_NAME:
        raise CategoryError(f"Keep the name under {MAX_NAME} characters")
    if colour not in PALETTE:
        raise CategoryError("Pick one of the colours")
    return name, colour


def add(conn, name: str, colour: str) -> Category:
    name, colour = _clean(name, colour)
    if conn.execute("SELECT 1 FROM categories WHERE name = ?", (name,)).fetchone():
        raise CategoryError(f"There's already a category called {name!r}")
    pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM categories").fetchone()[0]
    cur = conn.execute("INSERT INTO categories (name, colour, position) VALUES (?, ?, ?)", (name, colour, pos))
    return get(conn, cur.lastrowid)


def update(conn, category_id: int, name: str, colour: str) -> Category:
    get(conn, category_id)
    name, colour = _clean(name, colour)
    if conn.execute("SELECT 1 FROM categories WHERE name = ? AND id <> ?", (name, category_id)).fetchone():
        raise CategoryError(f"There's already a category called {name!r}")
    conn.execute("UPDATE categories SET name = ?, colour = ? WHERE id = ?", (name, colour, category_id))
    return get(conn, category_id)


def set_archived(conn, category_id: int, archived: bool) -> Category:
    get(conn, category_id)
    conn.execute("UPDATE categories SET archived = ? WHERE id = ?", (int(archived), category_id))
    return get(conn, category_id)


def tag(conn, meeting: Meeting, category_id: int | None, only_this: bool = False) -> None:
    """Give a meeting a category (None = no category).

    By default the category is remembered for every meeting with this name,
    and this occurrence follows it. `only_this` sets just this occurrence.
    """
    if category_id is not None:
        c = get(conn, category_id)
        if c.archived:
            raise CategoryError(f"{c.name!r} is archived")
    key = subject_key(meeting.subject)
    with transaction(conn):
        if only_this:
            conn.execute(
                "INSERT INTO meeting_categories (meeting_id, category_id) VALUES (?, ?) "
                "ON CONFLICT (meeting_id) DO UPDATE SET category_id = excluded.category_id",
                (meeting.id, category_id),
            )
            return
        if category_id is None:
            conn.execute("DELETE FROM subject_categories WHERE subject_key = ?", (key,))
        else:
            conn.execute(
                "INSERT INTO subject_categories (subject_key, category_id) VALUES (?, ?) "
                "ON CONFLICT (subject_key) DO UPDATE SET category_id = excluded.category_id",
                (key, category_id),
            )
        conn.execute("DELETE FROM meeting_categories WHERE meeting_id = ?", (meeting.id,))


def for_meetings(conn, meetings: list[Meeting]) -> dict[str, Category | None]:
    """{meeting id: its category or None}. An occurrence's own setting wins
    over the one remembered for its name."""
    if not meetings:
        return {}
    cats = {c.id: c for c in all_categories(conn)}
    marks = ",".join("?" * len(meetings))
    own = {r["meeting_id"]: r["category_id"] for r in conn.execute(
        f"SELECT * FROM meeting_categories WHERE meeting_id IN ({marks})", [m.id for m in meetings])}
    keys = list({subject_key(m.subject) for m in meetings})
    by_name = {r["subject_key"]: r["category_id"] for r in conn.execute(
        f"SELECT * FROM subject_categories WHERE subject_key IN ({','.join('?' * len(keys))})", keys)}
    out = {}
    for m in meetings:
        cid = own[m.id] if m.id in own else by_name.get(subject_key(m.subject))
        out[m.id] = cats.get(cid) if cid is not None else None
    return out
