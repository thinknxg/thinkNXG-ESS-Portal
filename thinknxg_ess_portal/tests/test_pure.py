"""Unit tests for the pure cores. Run without a bench:  python -m pytest thinknxg_ess_portal/tests/test_pure.py"""
import importlib.util
import os
import sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(__file__)


def _load(name):
    path = os.path.join(HERE, "..", "services", f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"ess_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


geo = _load("geo")
shiftwin = _load("shiftwin")
rules = _load("roster_rules")
compoff = _load("compoff_rules")

HQ = {"name": "Ruwi HQ", "latitude": 23.5880, "longitude": 58.3829, "radius": 150}
SITE = {"name": "Duqm Site", "latitude": 19.6575, "longitude": 57.7060, "radius": 400}


def test_haversine_known_distance():
    # Muscat to Duqm is roughly 450 km
    d = geo.haversine_m(23.5880, 58.3829, 19.6575, 57.7060)
    assert 430_000 < d < 470_000


def test_inside_geofence_matches_closest():
    r = geo.evaluate_location(23.5884, 58.3830, 20, required=True, enforce=True, max_accuracy=50, candidates=[HQ, SITE])
    assert r["ok"] and r["code"] == geo.OK_MATCHED and r["matched"]["name"] == "Ruwi HQ"
    assert r["distance"] < 60


def test_outside_geofence_reports_nearest():
    r = geo.evaluate_location(23.5950, 58.3829, 10, required=True, enforce=True, max_accuracy=50, candidates=[HQ])
    assert not r["ok"] and r["code"] == geo.OUTSIDE_GEOFENCE
    assert r["nearest"]["name"] == "Ruwi HQ" and 700 < r["nearest_distance"] < 850


def test_poor_accuracy_rejected_even_when_inside():
    r = geo.evaluate_location(23.5880, 58.3829, 180, required=True, enforce=True, max_accuracy=50, candidates=[HQ])
    assert not r["ok"] and r["code"] == geo.LOCATION_INACCURATE


def test_missing_location_when_required():
    r = geo.evaluate_location(None, None, None, required=True, enforce=True, max_accuracy=50, candidates=[HQ])
    assert r["code"] == geo.LOCATION_REQUIRED


def test_null_island_is_invalid():
    r = geo.evaluate_location(0, 0, 5, required=True, enforce=True, max_accuracy=50, candidates=[HQ])
    assert r["code"] == geo.INVALID_LOCATION


def test_record_only_mode_accepts_anywhere():
    r = geo.evaluate_location(24.0, 56.0, 30, required=True, enforce=False, max_accuracy=50, candidates=[HQ])
    assert r["ok"] and r["code"] == geo.OK_RECORDED and r["nearest"]["name"] == "Ruwi HQ"


def test_no_locations_configured():
    r = geo.evaluate_location(23.5880, 58.3829, 10, required=True, enforce=True, max_accuracy=50, candidates=[])
    assert r["code"] == geo.NO_LOCATIONS


def test_not_required_passes_without_fix():
    r = geo.evaluate_location(None, None, None, required=False, enforce=True, max_accuracy=50, candidates=[HQ])
    assert r["ok"] and r["code"] == geo.OK_NOT_REQUIRED


def test_risk_flags():
    now = datetime(2026, 11, 2, 9, 0)
    prev = (19.6575, 57.7060, now - timedelta(minutes=30))  # Duqm 30 minutes ago
    flags = geo.risk_flags(23.5880, 58.3829, 0.0, now, previous=prev, seen_elsewhere={(23.588, 58.3829)})
    assert set(flags) == {"unrealistic_accuracy", "impossible_travel", "identical_coordinates"}
    assert geo.risk_level(flags) == "High"
    assert geo.risk_level([]) == "None"


def test_window_day_shift_with_buffers():
    w = shiftwin.window(date(2026, 11, 2), "09:00:00", "18:00:00", 60, 30)
    assert w["open"] == datetime(2026, 11, 2, 8, 0) and w["close"] == datetime(2026, 11, 2, 18, 30)
    assert not w["overnight"] and w["hours"] == 9


def test_window_overnight_and_timedelta_input():
    w = shiftwin.window(date(2026, 11, 2), timedelta(hours=22), timedelta(hours=6), 30, 60)
    assert w["overnight"] and w["end"] == datetime(2026, 11, 3, 6, 0) and w["close"] == datetime(2026, 11, 3, 7, 0)


def test_current_and_upcoming():
    d = date(2026, 11, 2)
    ws = [shiftwin.window(d - timedelta(days=1), "22:00", "06:00", 30, 60), shiftwin.window(d, "14:00", "22:00", 60, 60)]
    assert shiftwin.current(ws, datetime(2026, 11, 2, 6, 40))["start"].day == 1   # still in last night's window
    assert shiftwin.current(ws, datetime(2026, 11, 2, 10, 0)) is None
    assert shiftwin.upcoming(ws, datetime(2026, 11, 2, 10, 0))["open"] == datetime(2026, 11, 2, 13, 0)


def _shift(d, s, e, st="G"):
    w = shiftwin.window(d, s, e)
    return {"date": d, "start": w["start"], "end": w["end"], "hours": w["hours"], "shift_type": st}


def test_min_rest_violation():
    d = date(2026, 11, 2)
    v = rules.check({"E1": [_shift(d, "14:00", "22:00", "E"), _shift(d + timedelta(days=1), "06:00", "14:00", "M")]},
                    min_rest_hours=11, max_consecutive_days=0, max_weekly_hours=0)
    assert [x["rule"] for x in v] == ["min_rest"] and v[0]["value"] == 8.0


def test_consecutive_days_and_weekly_hours():
    start = date(2026, 11, 1)  # Sunday
    shifts = [_shift(start + timedelta(days=i), "08:00", "17:00") for i in range(7)]
    v = rules.check({"E1": shifts}, min_rest_hours=11, max_consecutive_days=6, max_weekly_hours=45)
    kinds = sorted(x["rule"] for x in v)
    assert kinds == ["consecutive_days", "weekly_hours"]
    assert next(x for x in v if x["rule"] == "weekly_hours")["value"] == 63.0


def test_coverage_weekday_override():
    d = date(2026, 11, 6)  # Friday
    reqs = [{"shift_type": "G", "weekday": "All days", "min_staff": 3}, {"shift_type": "G", "weekday": "Friday", "min_staff": 1}]
    assert rules.coverage({(d, "G"): 1}, reqs, [d]) == []
    assert rules.coverage({(d + timedelta(days=1), "G"): 2}, reqs, [d + timedelta(days=1)])[0]["need"] == 3


def test_segments_keep_rest_and_skip_blocked():
    d = date(2026, 10, 1)
    entries = [(d + timedelta(days=i), k) for i, k in enumerate(["G", "G", None, None, "G", "G"])]
    segs = rules.segments(entries, blocked={d + timedelta(days=4)})
    assert [(s["key"], s["start"].day, s["end"].day) for s in segs] == [("G", 1, 2), (None, 3, 4), ("G", 6, 6)]


def test_compoff_classification():
    d = date(2026, 10, 30)
    wo = {"description": "Weekly off", "weekly_off": True}
    ok = compoff.classify({"date": d, "holiday": wo, "attendance": {"status": "Present", "working_hours": 8}})
    assert ok["eligible"] and ok["kind"] == "Weekly off" and not ok["half_day"]
    half = compoff.classify({"date": d, "holiday": wo, "attendance": {"status": "Half Day", "working_hours": 4}})
    assert half["eligible"] and half["half_day"]
    assert not compoff.classify({"date": d, "holiday": wo, "attendance": None})["eligible"]
    assert not compoff.classify({"date": d, "holiday": wo, "attendance": {"status": "Present"}, "claimed": "HR-CLR-1"})["eligible"]
    short = compoff.classify({"date": d, "holiday": wo, "attendance": {"status": "Present", "working_hours": 2}}, min_hours=4)
    assert not short["eligible"] and "2.0 h" in short["reason"]
    rest = {"date": d, "holiday": None, "roster_rest": True, "attendance": {"status": "Present"}}
    assert compoff.classify(rest)["eligible"]
    assert not compoff.classify(rest, allow_roster_rest=False)["eligible"]
    assert compoff.classify({"date": d, "holiday": None, "attendance": {"status": "Present"}}) is None


def test_compoff_group_ranges():
    d = date(2026, 10, 1)
    days = [d, d + timedelta(days=1), d + timedelta(days=5)]
    assert compoff.group_ranges(days) == [(d, d + timedelta(days=1)), (d + timedelta(days=5), d + timedelta(days=5))]


def test_runs_and_patterns():
    d = date(2026, 11, 1)
    days = [d + timedelta(days=i) for i in range(8)]
    mapping = rules.pattern_for(days, ["D", "D", None, "N", "N", None], offset=0)
    assert [mapping[x] for x in days] == ["D", "D", None, "N", "N", None, "D", "D"]
    r = rules.runs(list(mapping.items()))
    assert [(x["key"], x["start"].day, x["end"].day) for x in r] == [("D", 1, 2), ("N", 4, 5), ("D", 7, 8)]
