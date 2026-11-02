"""Unit tests for weekly_off_rules. Run without a bench:  python -m pytest thinknxg_ess_portal/tests/test_weekly_off_rules.py"""
import importlib.util
import os
from datetime import date

_p = os.path.join(os.path.dirname(__file__), "..", "services", "weekly_off_rules.py")
_s = importlib.util.spec_from_file_location("ess_weekly_off_rules", _p)
wo = importlib.util.module_from_spec(_s)
_s.loader.exec_module(wo)

D = lambda n: date(2026, 11, n)


def test_dates_between_inclusive():
    assert wo.dates_between(D(1), D(3)) == [D(1), D(2), D(3)]
    assert wo.dates_between(D(3), D(1)) == []


def test_plan_adds_only_free_dates_and_never_touches_others():
    rows = [{"date": D(6), "tag": None},            # base weekly off (Friday)
            {"date": D(18), "tag": None},           # National Day
            {"date": D(9), "tag": "HR-SHA-2"}]      # another assignment's weekly off
    p = wo.plan_rows(rows, [D(6), D(7), D(9), D(18)], "HR-SHA-1")
    assert p["add"] == [D(7)]
    assert p["existing"] == [D(6), D(9), D(18)]
    assert p["remove"] == []


def test_plan_on_change_removes_only_own_stale_rows():
    rows = [{"date": D(7), "tag": "HR-SHA-1"}, {"date": D(8), "tag": "HR-SHA-1"},
            {"date": D(8), "tag": None}, {"date": D(14), "tag": "HR-SHA-2"}]
    p = wo.plan_rows(rows, [D(8), D(15)], "HR-SHA-1")
    assert p["remove"] == [D(7)]
    assert p["keep"] == [D(8)]
    assert p["add"] == [D(15)]


def test_plan_on_delete_removes_everything_it_owns():
    rows = [{"date": D(7), "tag": "HR-SHA-1"}, {"date": D(18), "tag": None}, {"date": D(9), "tag": "HR-SHA-2"}]
    p = wo.plan_rows(rows, [], "HR-SHA-1")
    assert p["remove"] == [D(7)] and p["add"] == []


def test_plan_reports_dates_outside_list_period():
    p = wo.plan_rows([], [D(29), D(30), date(2026, 12, 1)], "X", D(1), D(30))
    assert p["add"] == [D(29), D(30)]
    assert p["outside"] == [date(2026, 12, 1)]


def test_mirror_follows_base_and_keeps_own_rows():
    base = [{"date": D(6), "description": "Friday"}, {"date": D(18), "description": "National Day"},
            {"date": D(19), "description": "National Day holiday"}]
    personal = [{"date": D(6), "from_base": True}, {"date": D(13), "from_base": True},   # 13 removed from base
                {"date": D(18), "tag": "HR-SHA-1"},                                       # clashes with new base row
                {"date": D(19), "tag": None},                                              # manual, wins
                {"date": D(21), "tag": "HR-SHA-1"}]
    rows, dropped = wo.mirror(base, personal)
    dates = [(r["date"], bool(r.get("from_base")), r.get("tag")) for r in rows]
    assert dates == [(D(6), True, None), (D(18), True, None), (D(19), False, None), (D(21), False, "HR-SHA-1")]
    assert [r["date"] for r in dropped] == [D(18)]


def test_mirrors_needed_stops_at_next_employee_assignment():
    co = [{"name": "C1", "holiday_list": "Oman 2026", "from_date": date(2026, 1, 1)},
          {"name": "C2", "holiday_list": "Oman 2027", "from_date": date(2027, 1, 1)},
          {"name": "C3", "holiday_list": "Oman 2028", "from_date": date(2028, 1, 1)}]
    assert [c["name"] for c in wo.mirrors_needed(date(2026, 1, 1), [], co)] == ["C2", "C3"]
    assert [c["name"] for c in wo.mirrors_needed(date(2026, 1, 1), [date(2027, 6, 1)], co)] == ["C2"]
    assert wo.mirrors_needed(date(2026, 1, 1), [date(2026, 12, 1)], co) == []


def test_personal_name_is_unique_and_bounded():
    assert wo.personal_name("Oman 2026", "HR-EMP-00042") == "Oman 2026 · HR-EMP-00042"
    assert wo.personal_name("Oman 2026", "E1", {"Oman 2026 · E1"}) == "Oman 2026 · E1 (2)"
    assert len(wo.personal_name("x" * 200, "HR-EMP-00042")) <= 140
