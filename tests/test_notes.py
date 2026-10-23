from datetime import date

import pytest

from bujo import categories as cats, journal as j, notes
from bujo.db import connect


def d(s):
    return date.fromisoformat(s)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "j.sqlite")
    yield c
    c.close()


# --- Sanitising -------------------------------------------------------------------

@pytest.mark.parametrize("raw,clean", [
    ("<b>bold</b> <i>it</i> <u>u</u>", "<strong>bold</strong> <em>it</em> <u>u</u>"),
    ("<ul><li>one</li><li>two</li></ul><ol><li>1</li></ol>", "<ul><li>one</li><li>two</li></ul><ol><li>1</li></ol>"),
    ("<div>line</div><div>next<br></div>", "<p>line</p><p>next<br></p>"),
    ('<p style="color:red" onclick="x()">styled</p>', "<p>styled</p>"),
    ('<a href="javascript:alert(1)">link</a>', "link"),
    ("<script>alert(1)</script>after", "after"),
    ("<style>p{}</style><p>kept</p>", "<p>kept</p>"),
    ('<img src=x onerror="alert(1)">', ""),
    ("<strong>unclosed", "<strong>unclosed</strong>"),
    ("<em><strong>mis</em>nested</strong>", "<em><strong>mis</strong></em>nested"),
    ("1 < 2 &amp; 3 > 2", "1 &lt; 2 &amp; 3 &gt; 2"),
    ("<p><br></p>", ""),
    ("Agreed<p></p><ul><li>x</li></ul><p></p>", "Agreed<ul><li>x</li></ul>"),
    ('<span style="font-weight:700">Word paste</span>', "Word paste"),
])
def test_sanitise(raw, clean):
    assert notes.sanitise(raw) == clean


def test_plain_text_preview():
    body = "<p>First <strong>bit</strong></p><ul><li>one</li><li>two</li></ul>"
    assert notes.plain_text(body) == "First bit · one · two"


# --- Details ----------------------------------------------------------------------

def test_a_note_is_a_title_until_it_has_details(conn):
    e = j.add_entry(conn, "note", "Ops review notes", on=d("2026-10-22"))
    n = notes.get(conn, e.id)
    assert (n.body, n.bookmarked, n.category) == ("", False, None) and not n.has_details
    notes.save_body(conn, e.id, "<p>Agreed <b>three</b> actions</p>")
    n = notes.get(conn, e.id)
    assert n.body == "<p>Agreed <strong>three</strong> actions</p>" and n.preview() == "Agreed three actions"


def test_only_notes_have_details(conn):
    t = j.add_entry(conn, "task", "A task", on=d("2026-10-22"))
    with pytest.raises(notes.NoteError):
        notes.save_body(conn, t.id, "x")
    with pytest.raises(notes.NoteError):
        notes.get(conn, t.id)


def test_bookmarks_newest_note_first(conn):
    old = j.add_entry(conn, "note", "Old", on=d("2026-09-01"))
    new = j.add_entry(conn, "note", "New", on=d("2026-10-22"))
    mid = j.add_entry(conn, "note", "Week note", week="2026-W40")   # Mon 28 Sep
    j.add_entry(conn, "note", "Not bookmarked", on=d("2026-10-23"))
    for e in (old, new, mid):
        notes.set_bookmark(conn, e.id, True)
    assert [n.e.text for n in notes.bookmarks(conn)] == ["New", "Week note", "Old"]
    notes.set_bookmark(conn, new.id, False)
    assert [n.e.text for n in notes.bookmarks(conn)] == ["Week note", "Old"]
    assert len(notes.all_notes(conn)) == 4


def test_category_shared_with_meetings(conn):
    e = j.add_entry(conn, "note", "Atlas kick-off", on=d("2026-10-22"))
    atlas = cats.add(conn, "Atlas", "mint")
    notes.set_category(conn, e.id, atlas.id)
    assert notes.get(conn, e.id).category == atlas
    notes.set_category(conn, e.id, None)
    assert notes.get(conn, e.id).category is None
    cats.set_archived(conn, atlas.id, True)
    with pytest.raises(notes.NoteError):
        notes.set_category(conn, e.id, atlas.id)


def test_day_and_week_lists(conn):
    a = j.add_entry(conn, "note", "First", on=d("2026-10-22"))
    b = j.add_entry(conn, "note", "Second", on=d("2026-10-22"))
    j.add_entry(conn, "task", "Not a note", on=d("2026-10-22"))
    j.add_entry(conn, "note", "Week only", week="2026-W43")
    assert [n.e.text for n in notes.for_day(conn, d("2026-10-22"))] == ["First", "Second"]
    assert {n.e.text for n in notes.for_week(conn, "2026-W43")} == {"First", "Second", "Week only"}


def test_too_long(conn):
    e = j.add_entry(conn, "note", "Huge", on=d("2026-10-22"))
    with pytest.raises(notes.NoteError):
        notes.save_body(conn, e.id, "x" * (notes.MAX_BODY + 1))
