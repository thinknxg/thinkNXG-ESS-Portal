"""Pure rules for writing weekly-off Shift Assignments into holiday lists (no frappe imports, unit-tested)."""
from datetime import date, timedelta

DESCRIPTION = "Weekly Off"


def dates_between(a, b):
    """Every date from a to b inclusive."""
    out, d = [], a
    while d <= b:
        out.append(d)
        d += timedelta(days=1)
    return out


def plan_rows(rows, wanted, tag, list_from=None, list_to=None):
    """Work out the change to one holiday list for one assignment.

    rows:    existing holidays [{"date": date, "tag": assignment name or None}]
    wanted:  dates this assignment should hold in this list
    tag:     the assignment's name

    Only rows carrying ``tag`` are ever removed. A wanted date that is already a holiday (public holiday, a base
    weekly off, a manual entry or another assignment's row) is left as it is and reported as ``existing``, so
    removing this assignment later can't delete it. Dates outside the list's own period are ``outside``.
    """
    wanted = set(wanted)
    mine = {r["date"] for r in rows if r.get("tag") == tag}
    others = {r["date"] for r in rows if r.get("tag") != tag}
    outside = sorted(d for d in wanted if (list_from and d < list_from) or (list_to and d > list_to))
    inside = wanted - set(outside)
    return {
        "remove": sorted(mine - inside),
        "add": sorted(inside - others - mine),
        "keep": sorted(inside & mine),
        "existing": sorted(inside & others),
        "outside": outside,
    }


def mirror(base_rows, personal_rows):
    """Bring a personal holiday list in step with the shared list it was copied from.

    base_rows:     [{"date", "description", "weekly_off", ...}] rows of the shared list
    personal_rows: [{"date", "tag", "from_base", ...}] rows of the personal copy

    Rows copied from the base are replaced by the base's current rows. Rows added by hand to the personal list and
    rows written by weekly-off assignments are kept, except that a base holiday wins over a weekly-off row on the same
    date (the weekly-off row is returned in ``dropped``). A hand-added row wins over a base row on the same date.
    Returns (rows, dropped).
    """
    own = [r for r in personal_rows if not r.get("from_base")]
    base_dates = {r["date"] for r in base_rows}
    dropped = [r for r in own if r.get("tag") and r["date"] in base_dates]
    own = [r for r in own if not (r.get("tag") and r["date"] in base_dates)]
    manual = {r["date"] for r in own if not r.get("tag")}
    taken = {r["date"] for r in own}
    copied = [dict(r, from_base=True, tag=None) for r in base_rows if r["date"] not in manual and r["date"] not in taken]
    return sorted(own + copied, key=lambda r: r["date"]), dropped


def mirrors_needed(start, employee_from_dates, company_assignments):
    """Company holiday-list assignments a new employee-level assignment starting on ``start`` would hide.

    thinkNXG HR resolves an employee's holiday list from their own assignments first and only falls back to the
    company's. A personal list assigned from ``start`` therefore hides every later company assignment until the
    employee's next own assignment. Those are mirrored onto the employee so nothing changes for those dates.

    employee_from_dates: from_dates of the employee's other submitted assignments
    company_assignments: [{"name", "holiday_list", "from_date"}]
    """
    later = sorted(d for d in employee_from_dates if d > start)
    until = later[0] if later else None
    return [c for c in sorted(company_assignments, key=lambda c: c["from_date"])
            if c["from_date"] > start and (until is None or c["from_date"] < until)]


def personal_name(base, employee, taken=()):
    """Name for an employee's personal copy of ``base`` (Holiday List names are limited to 140 characters)."""
    stem = f"{base[:120]} · {employee}"[:140]
    name, n = stem, 2
    while name in taken:
        name = f"{stem[:134]} ({n})"
        n += 1
    return name


def summary(per_list):
    """Human summary for the assignment: {list: {"added", "existing", "outside"}} -> text."""
    parts = []
    for hl, c in sorted(per_list.items()):
        bits = [f"{c.get('added', 0) + c.get('kept', 0)} day(s) held"]
        if c.get("existing"):
            bits.append(f"{c['existing']} already a holiday")
        if c.get("outside"):
            bits.append(f"{c['outside']} outside the list")
        parts.append(f"{hl}: " + ", ".join(bits))
    return "\n".join(parts)
