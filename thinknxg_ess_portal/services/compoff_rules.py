"""Compensatory-leave eligibility. Pure functions: no frappe imports.

A day qualifies when it was a day off (holiday-list weekly off or holiday, or a published roster rest day if
allowed) AND attendance was submitted as Present / Work From Home / Half Day, AND it isn't already claimed.
thinkNXG HR re-validates holidays and attendance when the request is saved, so this list is advisory.
"""

WORKED = ("Present", "Work From Home", "Half Day")


def classify(day, *, allow_roster_rest=True, min_hours=0.0):
    """day: {"date", "holiday": None|{"description","weekly_off"}, "roster_rest": bool,
    "attendance": None|{"status","working_hours"}, "claimed": None|request name}"""
    h = day.get("holiday")
    if h:
        kind = "Weekly off" if h.get("weekly_off") else "Holiday"
        label = h.get("description") or kind
    elif day.get("roster_rest") and allow_roster_rest:
        kind, label = "Rest day", "Roster rest day"
    elif day.get("roster_rest"):
        return {**day, "eligible": False, "kind": "Rest day", "label": "Roster rest day",
                "reason": "Roster rest days aren't eligible under your company's settings."}
    else:
        return None  # a normal working day: not shown at all
    out = {**day, "kind": kind, "label": label, "eligible": False, "half_day": False}
    att = day.get("attendance")
    if day.get("claimed"):
        out["reason"] = f"Already claimed in {day['claimed']}."
    elif not att:
        out["reason"] = "No attendance is marked for this day yet."
    elif att.get("status") not in WORKED:
        out["reason"] = f"Attendance is {att.get('status')}, not worked."
    elif min_hours and (att.get("working_hours") or 0) and float(att["working_hours"]) < float(min_hours):
        out["reason"] = f"Worked {float(att['working_hours']):.1f} h; at least {float(min_hours):g} h is needed."
    else:
        out["eligible"] = True
        out["half_day"] = att.get("status") == "Half Day"
        out["reason"] = None
    return out


def group_ranges(dates):
    """Contiguous date ranges from a set of dates: [(start, end)]."""
    ranges = []
    for d in sorted(set(dates)):
        if ranges and (d - ranges[-1][1]).days == 1:
            ranges[-1][1] = d
        else:
            ranges.append([d, d])
    return [tuple(r) for r in ranges]
