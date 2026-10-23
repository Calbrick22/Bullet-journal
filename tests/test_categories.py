from datetime import datetime, timezone

import pytest

from bujo import categories as cats
from bujo.calendar import Meeting
from bujo.db import connect

UTC = timezone.utc


def mtg(id, subject):
    return Meeting(id, subject, datetime(2026, 10, 22, 9, tzinfo=UTC), datetime(2026, 10, 22, 10, tzinfo=UTC))


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "j.sqlite")
    yield c
    c.close()


def test_add_rename_recolour_archive(conn):
    a = cats.add(conn, "  Project   Atlas ", "mint")
    assert (a.name, a.colour, a.archived) == ("Project Atlas", "mint", False)
    b = cats.update(conn, a.id, "Atlas", "sky")
    assert (b.name, b.colour) == ("Atlas", "sky")
    assert cats.set_archived(conn, a.id, True).archived
    assert cats.all_categories(conn, include_archived=False) == []
    assert cats.set_archived(conn, a.id, False).archived is False


def test_validation(conn):
    cats.add(conn, "Internal", "lime")
    with pytest.raises(cats.CategoryError):
        cats.add(conn, "internal", "sky")           # names are unique, ignoring case
    with pytest.raises(cats.CategoryError):
        cats.add(conn, "   ", "sky")
    with pytest.raises(cats.CategoryError):
        cats.add(conn, "Purple", "violet")          # not in the palette
    with pytest.raises(cats.CategoryError):
        cats.add(conn, "x" * 41, "sky")


def test_remembered_by_meeting_name(conn):
    atlas = cats.add(conn, "Atlas", "mint")
    week1, week2, other = mtg("w1", "Weekly ops stand-up"), mtg("w2", " weekly  OPS stand-up"), mtg("o", "1:1 with Sam")
    cats.tag(conn, week1, atlas.id)
    got = cats.for_meetings(conn, [week1, week2, other])
    assert got["w1"] == atlas and got["w2"] == atlas and got["o"] is None


def test_one_occurrence_can_differ(conn):
    atlas, internal = cats.add(conn, "Atlas", "mint"), cats.add(conn, "Internal", "lime")
    w1, w2, w3 = mtg("w1", "Stand-up"), mtg("w2", "Stand-up"), mtg("w3", "Stand-up")
    cats.tag(conn, w1, atlas.id)
    cats.tag(conn, w2, internal.id, only_this=True)
    cats.tag(conn, w3, None, only_this=True)       # this one: no category
    got = cats.for_meetings(conn, [w1, w2, w3])
    assert (got["w1"], got["w2"], got["w3"]) == (atlas, internal, None)
    # Re-tagging by name clears that occurrence's own setting
    cats.tag(conn, w2, atlas.id)
    assert cats.for_meetings(conn, [w2])["w2"] == atlas


def test_untag_by_name(conn):
    atlas = cats.add(conn, "Atlas", "mint")
    w1 = mtg("w1", "Stand-up")
    cats.tag(conn, w1, atlas.id)
    cats.tag(conn, w1, None)
    assert cats.for_meetings(conn, [w1])["w1"] is None


def test_archived_keeps_colouring_but_cannot_be_picked(conn):
    atlas = cats.add(conn, "Atlas", "mint")
    w1 = mtg("w1", "Stand-up")
    cats.tag(conn, w1, atlas.id)
    cats.set_archived(conn, atlas.id, True)
    assert cats.for_meetings(conn, [w1])["w1"].name == "Atlas"
    with pytest.raises(cats.CategoryError):
        cats.tag(conn, mtg("w2", "Other"), atlas.id)
