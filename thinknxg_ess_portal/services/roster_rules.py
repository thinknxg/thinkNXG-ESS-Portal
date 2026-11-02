"""Roster compliance and coverage checks. Pure functions: no frappe imports.

Defaults are configurable in ESS Portal Settings; they are working-time guard rails for planners,
not a statement of any jurisdiction's law. Set them to your own policy.
"""
from collections import defaultdict
from datetime import timedelta

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def week_key(d, week_start=6):
    """Week bucket starting on `week_start` (Python weekday; 6 = Sunday, the GCC working week)."""
    offset = (d.weekday() - week_start) % 7
    return d - timedelta(days=offset)


def check(shifts_by_employee, *, min_rest_hours=11, max_consecutive_days=6, max_weekly_hours=45, week_start=6,
          names=None):
    """shifts_by_employee: {employee: [{"date", "start", "end", "hours", "shift_type"}]}.
    Returns violations: {"employee", "date", "rule", "severity", "message", "value", "limit"}."""
    names = names or {}
    out = []
    for emp, shifts in shifts_by_employee.items():
        who = names.get(emp, emp)
        rows = sorted(shifts, key=lambda s: s["start"])
        if min_rest_hours:
            for prev, nxt in zip(rows, rows[1:]):
                rest = (nxt["start"] - prev["end"]).total_seconds() / 3600
                if rest < 0:
                    out.append({"employee": emp, "date": str(nxt["date"]), "rule": "overlap", "severity": "error",
                                "value": round(rest, 1), "limit": 0,
                                "message": f"{who}: {nxt['shift_type']} on {nxt['date']} overlaps the previous shift."})
                elif rest < min_rest_hours:
                    out.append({"employee": emp, "date": str(nxt["date"]), "rule": "min_rest", "severity": "warning",
                                "value": round(rest, 1), "limit": min_rest_hours,
                                "message": f"{who}: only {rest:.1f} h rest before {nxt['date']} (minimum {min_rest_hours:g} h)."})
        if max_consecutive_days:
            days = sorted({r["date"] for r in rows})
            streak, start = 0, None
            for i, d in enumerate(days):
                if i and (d - days[i - 1]).days == 1:
                    streak += 1
                else:
                    streak, start = 1, d
                if streak == max_consecutive_days + 1:
                    out.append({"employee": emp, "date": str(d), "rule": "consecutive_days", "severity": "warning",
                                "value": streak, "limit": max_consecutive_days,
                                "message": f"{who}: {streak} working days in a row from {start} (maximum {max_consecutive_days})."})
        if max_weekly_hours:
            weeks = defaultdict(float)
            for r in rows:
                weeks[week_key(r["date"], week_start)] += float(r["hours"] or 0)
            for wk, hrs in sorted(weeks.items()):
                if hrs > max_weekly_hours + 1e-6:
                    out.append({"employee": emp, "date": str(wk), "rule": "weekly_hours", "severity": "warning",
                                "value": round(hrs, 1), "limit": max_weekly_hours,
                                "message": f"{who}: {hrs:.1f} h in the week of {wk} (maximum {max_weekly_hours:g} h)."})
    return out


def coverage(counts, requirements, dates):
    """counts: {(date, shift_type): n}; requirements: [{"shift_type", "weekday", "min_staff"}].
    weekday is a name from WEEKDAYS or "All days". Returns gaps: {"date", "shift_type", "have", "need"}."""
    gaps = []
    for d in dates:
        wd = WEEKDAYS[d.weekday()]
        need = {}
        for r in requirements:
            if r.get("weekday") in (None, "", "All days", wd):
                # A weekday-specific rule overrides "All days" for that shift.
                key = r["shift_type"]
                specific = r.get("weekday") == wd
                if key not in need or specific:
                    need[key] = (int(r.get("min_staff") or 0), specific)
        for st, (n, _specific) in need.items():
            have = counts.get((d, st), 0)
            if have < n:
                gaps.append({"date": str(d), "shift_type": st, "have": have, "need": n})
    return gaps


def runs(entries):
    """Group per-day entries [(date, key)] into contiguous runs of the same key. Rest days (key None) break runs."""
    out = []
    for d, key in sorted(entries, key=lambda x: x[0]):
        if key is None:
            continue
        if out and out[-1]["key"] == key and (d - out[-1]["end"]).days == 1:
            out[-1]["end"] = d
        else:
            out.append({"key": key, "start": d, "end": d})
    return out


def segments(entries, blocked=()):
    """Contiguous runs of the same key, INCLUDING rest (key None), split at blocked dates.
    entries: [(date, key)]; blocked: dates that must not be touched (e.g. attendance already marked)."""
    blocked = set(blocked)
    out = []
    for d, key in sorted(entries, key=lambda x: x[0]):
        if d in blocked:
            continue
        if out and out[-1]["key"] == key and (d - out[-1]["end"]).days == 1:
            out[-1]["end"] = d
        else:
            out.append({"key": key, "start": d, "end": d})
    return out


def pattern_for(dates, steps, offset=0):
    """Map each date to a pattern step, cycling. steps: list of shift_type or None (rest)."""
    if not steps:
        return {}
    return {d: steps[(i + offset) % len(steps)] for i, d in enumerate(dates)}
