"""Notes with details: formatted text, a bookmark and a category.

Any note entry can have details; one without is just its title. The text is
stored as a small, safe subset of HTML: bold, italic, underline, paragraphs,
line breaks and bulleted or numbered lists. Everything else (styles, links,
scripts, pasted Word markup) is stripped on save, so stored notes are always
safe to show.
"""

import html
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser

from . import categories as catmod, dates, journal as j
from .categories import Category
from .db import transaction
from .journal import Entry

ALLOWED = {"strong", "em", "u", "ul", "ol", "li", "p", "br"}
RENAME = {"b": "strong", "i": "em", "div": "p"}
SKIP_CONTENT = {"script", "style", "head", "title", "template", "noscript"}
MAX_BODY = 200_000   # characters of stored HTML; about a hundred pages of text


class NoteError(ValueError):
    pass


class _Sanitiser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.open: list[str] = []
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_CONTENT:
            self.skipping += 1
            return
        tag = RENAME.get(tag, tag)
        if self.skipping or tag not in ALLOWED:
            return
        if tag == "br":
            self.out.append("<br>")
        else:
            self.out.append(f"<{tag}>")
            self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        if RENAME.get(tag, tag) == "br" and not self.skipping:
            self.out.append("<br>")

    def handle_endtag(self, tag):
        if tag in SKIP_CONTENT:
            self.skipping = max(0, self.skipping - 1)
            return
        tag = RENAME.get(tag, tag)
        if self.skipping or tag not in self.open:
            return
        # Close everything opened since, so the result is always well nested.
        while self.open:
            t = self.open.pop()
            self.out.append(f"</{t}>")
            if t == tag:
                break

    def handle_data(self, data):
        if not self.skipping:
            self.out.append(html.escape(data, quote=False))

    def result(self) -> str:
        while self.open:
            self.out.append(f"</{self.open.pop()}>")
        return "".join(self.out)


def sanitise(raw: str) -> str:
    p = _Sanitiser()
    p.feed(raw or "")
    p.close()
    out = p.result().replace("<p></p>", "").strip()      # empty paragraphs the editor leaves behind
    # An editor that has been emptied leaves "<p><br></p>" behind
    return "" if out in ("", "<br>", "<p></p>", "<p><br></p>") else out


class _Text(HTMLParser):
    """Text of each paragraph, list item or line, for one-line previews."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = [""]

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "li", "br", "div", "ul", "ol"):
            self.blocks.append("")

    def handle_data(self, data):
        self.blocks[-1] += data


def plain_text(body: str) -> str:
    """'<p>Needs:</p><ul><li>one</li><li>two</li></ul>' -> 'Needs: · one · two'"""
    p = _Text()
    p.feed(body or "")
    return " · ".join(t for t in (" ".join(b.split()) for b in p.blocks) if t)


# --- Reading ----------------------------------------------------------------------

@dataclass
class Note:
    e: Entry
    body: str = ""
    bookmarked: bool = False
    bookmarked_at: datetime | None = None
    category: Category | None = None
    updated_at: datetime | None = None

    @property
    def on(self) -> date:
        """The note's date: its day, or the Monday of its week."""
        return self.e.entry_date or dates.week_monday(self.e.entry_week)

    @property
    def has_details(self) -> bool:
        return bool(self.body)

    def preview(self, length: int = 160) -> str:
        text = plain_text(self.body)
        return text if len(text) <= length else text[: length - 1].rsplit(" ", 1)[0] + "…"


def _notes(conn, where: str = "", params: tuple = ()) -> list[Note]:
    cats = {c.id: c for c in catmod.all_categories(conn)}
    rows = conn.execute(
        f"""SELECT e.*, d.body, d.bookmarked, d.bookmarked_at, d.category_id, d.updated_at AS details_at
            FROM entries e LEFT JOIN note_details d ON d.entry_id = e.id
            WHERE e.kind = 'note' {where}""",
        params,
    )
    out = []
    for r in rows:
        out.append(Note(
            e=Entry.from_row(r), body=r["body"] or "", bookmarked=bool(r["bookmarked"]),
            bookmarked_at=datetime.fromisoformat(r["bookmarked_at"]) if r["bookmarked_at"] else None,
            category=cats.get(r["category_id"]),
            updated_at=datetime.fromisoformat(r["details_at"]) if r["details_at"] else None,
        ))
    out.sort(key=lambda n: (n.on, n.e.created_at), reverse=True)   # newest first
    return out


def get(conn, entry_id: int) -> Note:
    found = _notes(conn, "AND e.id = ?", (entry_id,))
    if not found:
        raise NoteError("No such note")
    return found[0]


def for_day(conn, d: date) -> list[Note]:
    notes = _notes(conn, "AND e.entry_date = ?", (d.isoformat(),))
    return sorted(notes, key=lambda n: (n.e.position, n.e.id))   # journal order


def for_week(conn, key: str) -> list[Note]:
    days = dates.week_dates(key)
    return _notes(conn, "AND (e.entry_date BETWEEN ? AND ? OR e.entry_week = ?)",
                  (days[0].isoformat(), days[-1].isoformat(), key))


def bookmarks(conn) -> list[Note]:
    return _notes(conn, "AND d.bookmarked = 1")


def all_notes(conn, bookmarked_only: bool = False) -> list[Note]:
    return _notes(conn, "AND d.bookmarked = 1" if bookmarked_only else "")


# --- Writing ----------------------------------------------------------------------

def _ensure(conn, entry_id: int) -> None:
    e = j.get_entry(conn, entry_id)
    if e.kind != "note":
        raise NoteError("Only notes have details")
    conn.execute("INSERT OR IGNORE INTO note_details (entry_id) VALUES (?)", (entry_id,))


def _now() -> str:
    return dates.utc_now().isoformat(timespec="seconds")


def save_body(conn, entry_id: int, raw: str) -> str:
    if len(raw or "") > MAX_BODY:
        raise NoteError("That note is too long to save")
    body = sanitise(raw)
    with transaction(conn):
        _ensure(conn, entry_id)
        conn.execute("UPDATE note_details SET body = ?, updated_at = ? WHERE entry_id = ?", (body, _now(), entry_id))
    return body


def set_bookmark(conn, entry_id: int, on: bool) -> None:
    with transaction(conn):
        _ensure(conn, entry_id)
        conn.execute(
            "UPDATE note_details SET bookmarked = ?, bookmarked_at = ? WHERE entry_id = ?",
            (int(on), _now() if on else None, entry_id),
        )


def set_category(conn, entry_id: int, category_id: int | None) -> None:
    if category_id is not None:
        c = catmod.get(conn, category_id)
        if c.archived:
            raise NoteError(f"{c.name!r} is archived")
    with transaction(conn):
        _ensure(conn, entry_id)
        conn.execute("UPDATE note_details SET category_id = ? WHERE entry_id = ?", (category_id, entry_id))
