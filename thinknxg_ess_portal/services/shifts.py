"""Who works when: native Shift Assignments, default shifts, published roster rest days, holidays and leave.

Native thinkNXG HR stays authoritative. Rosters reach attendance only through the Shift Assignments they publish.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta

import frappe
from frappe.utils import add_days, cint, getdate
from thinknxg_ess_portal.services import hrms, identity, shiftwin

NATIVE_COLORS = {"Blue": "#2F6FD1", "Cyan": "#1C8FA6", "Fuchsia": "#B0389E", "Green": "#2E8B57", "Lime": "#6E9C1C",
                 "Orange": "#D9771E", "Pink": "#D1477A", "Red": "#C0392B", "Violet": "#6D4BC2", "Yellow": "#B8901A",
                 "Gray": "#6E7E78", "Purple": "#7B4FB5"}
AUTO = ["#0F6E5A", "#2F6FD1", "#D9771E", "#6D4BC2", "#B0389E", "#1C8FA6", "#6E9C1C", "#C0392B"]


def clear_cache(doc=None, method=None):
    frappe.cache.delete_keys("ess_shift_type:")


def _code(name):
    words = [w for w in name.replace("-", " ").split() if w.lower() not in ("shift", "the")]
    code = "".join(w[0] for w in words)[:2].upper()
    return code or name[:2].upper()


def shift_type(name):
    if not name:
        return None
    key = f"ess_shift_type:{name}"
    data = frappe.cache.get_value(key)
    if data is None:
        meta = frappe.get_meta("Shift Type")
        opt = [f for f in ("begin_check_in_before_shift_start_time", "allow_check_out_after_shift_end_time", "color",
                           "ess_code", "ess_color", "ess_weekly_off") if meta.has_field(f)]
        row = frappe.db.get_value("Shift Type", name, ["name", "start_time", "end_time"] + opt, as_dict=True)
        if not row:
            return None
        s = identity.settings()
        early = cint(row.get("begin_check_in_before_shift_start_time")) or cint(s.get("shift_window_early_minutes"))
        late = cint(row.get("allow_check_out_after_shift_end_time")) or cint(s.get("shift_window_late_minutes"))
        win = shiftwin.window(date(2000, 1, 3), row.start_time, row.end_time)
        data = {
            "name": name,
            "start": shiftwin.to_time(row.start_time).strftime("%H:%M") if row.start_time is not None else None,
            "end": shiftwin.to_time(row.end_time).strftime("%H:%M") if row.end_time is not None else None,
            "early": early, "late": late, "hours": win["hours"] if win else 0, "overnight": bool(win and win["overnight"]),
            "code": (row.get("ess_code") or _code(name))[:3],
            "color": row.get("ess_color") or NATIVE_COLORS.get(row.get("color")) or AUTO[sum(map(ord, name)) % len(AUTO)],
            "weekly_off": bool(cint(row.get("ess_weekly_off"))),
        }
        frappe.cache.set_value(key, data, expires_in_sec=600)
    return data


def all_shift_types():
    return [shift_type(n) for n in frappe.get_all("Shift Type", pluck="name", order_by="start_time asc")]


def _assignment_fields():
    meta = frappe.get_meta("Shift Assignment")
    loc = "shift_location" if meta.has_field("shift_location") else "null as shift_location"
    ros = "ess_roster" if meta.has_field("ess_roster") else "null as ess_roster"
    return f"name, employee, shift_type, start_date, end_date, {loc}, {ros}"


def assignments(employees, start, end):
    """Active, submitted Shift Assignments overlapping [start, end], grouped by employee."""
    if not employees:
        return {}
    rows = frappe.db.sql(f"""select {_assignment_fields()} from `tabShift Assignment`
        where employee in %(emps)s and docstatus=1 and status='Active' and start_date<=%(end)s
          and (end_date is null or end_date>=%(start)s) order by start_date""",
                         {"emps": list(employees), "start": start, "end": end}, as_dict=True)
    out = defaultdict(list)
    for r in rows:
        out[r.employee].append(r)
    return out


def published_rest_days(employees, start, end):
    if not employees:
        return {}
    rows = frappe.db.sql("""select e.employee, e.date from `tabESS Roster Entry` e
        join `tabESS Roster` r on r.name=e.roster
        where r.status='Published' and e.is_rest_day=1 and e.employee in %(emps)s and e.date between %(s)s and %(e)s""",
                         {"emps": list(employees), "s": start, "e": end}, as_dict=True)
    out = defaultdict(set)
    for r in rows:
        out[r.employee].add(getdate(r.date))
    return out


def leaves(employees, start, end):
    if not employees:
        return {}
    rows = frappe.get_all("Leave Application", filters={"employee": ["in", list(employees)], "docstatus": ["<", 2],
                                                        "status": ["in", ["Open", "Approved"]],
                                                        "from_date": ["<=", end], "to_date": [">=", start]},
                          fields=["employee", "leave_type", "from_date", "to_date", "status", "half_day", "half_day_date"])
    out = defaultdict(dict)
    for r in rows:
        for d in shiftwin.day_range(max(getdate(r.from_date), getdate(start)), min(getdate(r.to_date), getdate(end))):
            out[r.employee][d] = {"leave_type": r.leave_type, "status": r.status,
                                  "half_day": bool(r.half_day and (not r.half_day_date or getdate(r.half_day_date) == d))}
    return out


def holidays_for(employees, start, end):
    """{employee: {date: {"description", "weekly_off"}}}, honouring holiday lists that change within the range."""
    try:
        from hrms.utils.holiday_list import get_holiday_list_ranges_for_employees, get_holidays_in_ranges_map
    except ImportError:
        return _holidays_for_single_list(employees, start, end)
    employees = list(employees)
    companies = dict(frappe.get_all("Employee", filters={"name": ["in", employees or [""]]}, fields=["name", "company"],
                                    as_list=True))
    ranges = get_holiday_list_ranges_for_employees({e: companies.get(e) for e in employees}, start, end,
                                                   raise_exception=False)
    found = get_holidays_in_ranges_map(ranges)
    return {e: {getdate(h.holiday_date): {"description": h.description, "weekly_off": bool(h.weekly_off)}
                for h in found.get(e, [])} for e in employees}


def _holidays_for_single_list(employees, start, end):
    lists, out = {}, {}
    for emp in employees:
        hl = hrms.holiday_list(emp)
        if hl not in lists:
            lists[hl] = {getdate(h.holiday_date): {"description": h.description, "weekly_off": bool(h.weekly_off)}
                         for h in (frappe.get_all("Holiday", filters={"parent": hl, "holiday_date": ["between", [start, end]]},
                                                  fields=["holiday_date", "description", "weekly_off"]) if hl else [])}
        out[emp] = lists[hl]
    return out


def plan(employees, start, end, with_context=True):
    """Day-by-day schedule for employees: {employee: [day]}. A day carries raw datetime windows.

    Order of precedence per day: published roster rest day > active Shift Assignments > employee default shift.
    A default shift is not applied on holidays or weekly offs.
    """
    start, end = getdate(start), getdate(end)
    employees = list(employees)
    asg = assignments(employees, start, end)
    rest = published_rest_days(employees, start, end)
    defaults = dict(frappe.get_all("Employee", filters={"name": ["in", employees or [""]]},
                                   fields=["name", "default_shift"], as_list=True))
    hol = holidays_for(employees, start, end) if with_context else {}
    lv = leaves(employees, start, end) if with_context else {}
    out = {}
    for emp in employees:
        days = []
        for d in shiftwin.day_range(start, end):
            rows = [a for a in asg.get(emp, []) if getdate(a.start_date) <= d and (not a.end_date or getdate(a.end_date) >= d)]
            h = hol.get(emp, {}).get(d)
            source = "assignment"
            if d in rest.get(emp, set()):
                rows, source = [], "roster"
            elif not rows and defaults.get(emp) and not h:
                rows, source = [frappe._dict(shift_type=defaults[emp], shift_location=None, name=None, ess_roster=None)], "default"
            windows = []
            off = False
            for a in rows:
                st = shift_type(a.shift_type)
                if not st:
                    continue
                if st.get("weekly_off"):
                    off = True  # a Weekly Off / Rest Day assignment: no working window
                    continue
                win = shiftwin.window(d, st["start"], st["end"], st["early"], st["late"])
                if not win:
                    continue
                win.update(shift_type=a.shift_type, code=st["code"], color=st["color"], location=a.shift_location,
                           assignment=a.name, source="roster" if a.get("ess_roster") else source)
                windows.append(win)
            windows.sort(key=lambda x: x["start"])
            days.append({"date": d, "windows": windows, "rest_day": off or d in rest.get(emp, set()), "holiday": h,
                         "leave": lv.get(emp, {}).get(d)})
        out[emp] = days
    return out


def _fmt_window(wn):
    return {"shift_type": wn["shift_type"], "code": wn["code"], "color": wn["color"],
            "start": wn["start"].strftime("%H:%M"), "end": wn["end"].strftime("%H:%M"),
            "start_dt": str(wn["start"]), "end_dt": str(wn["end"]), "open": str(wn["open"]), "close": str(wn["close"]),
            "overnight": wn["overnight"], "hours": wn["hours"], "location": wn["location"], "source": wn["source"]}


def serialize_day(day):
    return {"date": str(day["date"]), "weekday": day["date"].strftime("%a"), "shifts": [_fmt_window(x) for x in day["windows"]],
            "rest_day": day["rest_day"], "holiday": day["holiday"], "leave": day["leave"]}


def schedule(employee, start, end):
    return [serialize_day(d) for d in plan([employee], start, end)[employee]]


def _windows_near(employee, ts, back=1, ahead=1):
    d = ts.date()
    days = plan([employee], add_days(d, -back), add_days(d, ahead), with_context=False)[employee]
    return [wn for day in days for wn in day["windows"]]


def current_window(employee, ts):
    return shiftwin.current(_windows_near(employee, ts), ts)


def next_window(employee, ts, horizon_days=7):
    return shiftwin.upcoming(_windows_near(employee, ts, back=0, ahead=horizon_days), ts)


def format_window(wn):
    return _fmt_window(wn) if wn else None
