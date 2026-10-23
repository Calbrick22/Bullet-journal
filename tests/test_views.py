from datetime import date, datetime, timezone

from bujo import views
from bujo.calendar import Meeting

UTC = timezone.utc
D = date(2026, 10, 22)  # BST: local = UTC + 1


def m(id, start, end, all_day=False):
    s = datetime(2026, 10, 22, *start, tzinfo=UTC)
    e = datetime(2026, 10, 22, *end, tzinfo=UTC)
    return Meeting(id, id, s, e, all_day=all_day)


def rows(*meetings):
    return views.meeting_rows(list(meetings), D, datetime(2026, 10, 22, 7, 0, tzinfo=UTC))


def test_positions_in_pixels_from_first_hour():
    rs = rows(m("a", (8, 30), (9, 0)))          # 09:30-10:00 local
    views.lay_out(rs, D, 8, 18)
    assert rs[0].time == "09:30–10:00"
    assert rs[0].top == 84 and rs[0].height == 26   # 1.5 h x 56, 30 min x 56/60 - 2


def test_clashes_share_lanes_and_back_to_back_does_not():
    a, b, c, d = rows(m("a", (9, 0), (10, 0)), m("b", (9, 30), (10, 30)),
                      m("c", (10, 30), (11, 0)), m("d", (9, 45), (10, 15)))
    views.lay_out([a, b, c, d], D, 8, 18)
    assert (a.lanes, b.lanes, d.lanes) == (3, 3, 3)
    assert {a.lane, b.lane, d.lane} == {0, 1, 2}
    assert (c.lane, c.lanes) == (0, 1)              # starts as b ends: its own cluster


def test_short_meetings_keep_a_minimum_height():
    [r] = rows(m("a", (9, 0), (9, 5)))
    views.lay_out([r], D, 8, 18)
    assert r.height == views.MIN_BLOCK_PX


def test_grid_widens_for_early_and_late_meetings():
    assert views.grid_hours(rows(m("a", (9, 0), (10, 0)))) == (8, 18)
    assert views.grid_hours(rows(m("a", (6, 0), (7, 0)), m("b", (17, 30), (18, 15)))) == (7, 20)


def test_all_day_meetings_are_not_placed():
    [r] = rows(m("a", (0, 0), (23, 0), all_day=True))
    views.lay_out([r], D, 8, 18)
    assert r.time == "All day" and r.height == 0


def test_duration_labels():
    assert [views.duration(x) for x in (45, 60, 90, 510)] == ["45 m", "1 h", "1 h 30 m", "8 h 30 m"]
