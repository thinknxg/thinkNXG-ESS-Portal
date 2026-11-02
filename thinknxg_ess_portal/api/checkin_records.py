"""Employee Checkin records (all channels) with role-based visibility.

- Employees: their own records, when "Employees can see their own check-in records" is on.
- Managers: direct and indirect reports, direct reports only, or none (setting).
- HR: their HR scope (HR Manager: everyone).
Raw coordinates are shown to HR, and to managers only when settings allow it. Native Employee Checkin permissions
in Desk are untouched; this is an API-level view.
"""
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, get_datetime, getdate, today
from thinknxg_ess_portal.api._guard import guard
from thinknxg_ess_portal.services import identity

FIELDS = ["name", "employee", "employee_name", "time", "log_type", "device_id", "shift", "skip_auto_attendance",
          "attendance", "latitude", "longitude", "offshift", "ess_source", "ess_accuracy", "ess_location", "ess_distance"]


def _range(from_date, to_date):
    td = getdate(to_date or today())
    fd = getdate(from_date or add_days(td, -6))
    limit = cint(identity.settings().get("checkin_records_max_days")) or 31
    if fd > td:
        frappe.throw(_("From date must be on or before to date."))
    if date_diff(td, fd) + 1 > limit:
        frappe.throw(_("Choose up to {0} days at a time.").format(limit))
    return fd, td


def _source(r):
    if r.get("ess_source") or r.get("device_id") == "thinkNXG ESS Portal":
        return "Portal"
    if r.get("device_id"):
        return "Device"
    return "Desk / API"


def fetch(employees, from_date, to_date, coordinates=False):
    fd, td = _range(from_date, to_date)
    meta = frappe.get_meta("Employee Checkin")
    fields = [f for f in FIELDS if f == "name" or meta.has_field(f)]
    rows = frappe.get_all("Employee Checkin", filters={"employee": ["in", list(employees) or [""]],
                                                       "time": ["between", [f"{fd} 00:00:00", f"{td} 23:59:59"]]},
                          fields=fields, order_by="employee asc, time asc", limit=5000)
    days = defaultdict(lambda: {"punches": []})
    for r in rows:
        r["source"] = _source(r)
        if not coordinates:
            r.pop("latitude", None)
            r.pop("longitude", None)
        key = (r.employee, str(getdate(r.time)))
        d = days[key]
        d.update(employee=r.employee, employee_name=r.employee_name, date=key[1])
        d["punches"].append(r)
    att = {(a.employee, str(a.attendance_date)): a for a in frappe.get_all(
        "Attendance", filters={"employee": ["in", list(employees) or [""]], "docstatus": 1,
                               "attendance_date": ["between", [fd, td]]},
        fields=["employee", "attendance_date", "status", "working_hours", "late_entry", "early_exit"])}
    out = []
    for key, d in days.items():
        typed = [p for p in d["punches"] if p.log_type in ("IN", "OUT")]
        ins = [p for p in d["punches"] if p.log_type == "IN"]
        outs = [p for p in d["punches"] if p.log_type == "OUT"]
        a = att.get(key)
        out.append({**d, "first_in": str(ins[0].time) if ins else None, "last_out": str(outs[-1].time) if outs else None,
                    "count": len(d["punches"]),
                    "open": bool(typed) and typed[-1].log_type == "IN" and key[1] < str(getdate(today())),
                    "untyped": len(d["punches"]) - len(typed),
                    "attendance": {"status": a.status, "working_hours": a.working_hours, "late": a.late_entry,
                                   "early_exit": a.early_exit} if a else None})
    out.sort(key=lambda x: (x["date"], x["employee_name"] or ""), reverse=True)
    return {"from": str(fd), "to": str(td), "days": out, "total": len(rows), "truncated": len(rows) >= 5000,
            "coordinates": bool(coordinates)}


def visible_employees(user=None):
    """(employees or None for unrestricted, coordinates_allowed, role label)."""
    user = user or frappe.session.user
    s = identity.settings()
    if identity.is_hr(user):
        return identity.hr_scope_employees(user), True, "hr"
    mode = s.get("manager_checkin_visibility") or "Direct and indirect reports"
    if mode == "None" or not identity.is_manager(user):
        return [], False, "none"
    team = identity.team_employees(user, recursive=(mode == "Direct and indirect reports"))
    return team, s.get("checkin_coordinates_visible_to") == "HR and managers", "manager"


@frappe.whitelist(methods=["GET"])
def team_checkins(from_date=None, to_date=None, employee=None, department=None, branch=None):
    guard("enable_attendance", employee=False)
    emps, coords, role = visible_employees()
    if role == "none":
        frappe.throw(_("Team check-in records aren't available to you."), frappe.PermissionError)
    flt = {"status": "Active"}
    if emps is not None:
        flt["name"] = ["in", list(emps) or [""]]
    if department:
        flt["department"] = department
    if branch:
        flt["branch"] = branch
    if employee:
        if emps is not None and employee not in emps:
            frappe.throw(_("Not permitted"), frappe.PermissionError)
        flt["name"] = employee
    people = frappe.get_all("Employee", filters=flt, fields=["name", "employee_name", "department", "branch"], limit=2000)
    data = fetch([p.name for p in people], from_date, to_date, coordinates=coords)
    info = {p.name: p for p in people}
    for d in data["days"]:
        p = info.get(d["employee"])
        d["department"], d["branch"] = (p.department, p.branch) if p else (None, None)
    # filter options come from everyone the user may see, not just the current filter
    base = {"status": "Active"}
    if emps is not None:
        base["name"] = ["in", list(emps) or [""]]
    data["departments"] = sorted({x for x in frappe.get_all("Employee", filters=base, pluck="department") if x})
    data["branches"] = sorted({x for x in frappe.get_all("Employee", filters=base, pluck="branch") if x})
    data["employees"] = frappe.get_all("Employee", filters=base, fields=["name", "employee_name"], order_by="employee_name",
                                       limit=2000)
    data["scope"] = role
    return data
