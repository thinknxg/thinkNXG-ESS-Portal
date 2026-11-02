"""Roster planning and publishing.

A roster is a plan (ESS Roster + ESS Roster Entry). Publishing turns the plan into native Shift Assignments tagged
with `ess_roster`, from today onward; past days are never rewritten. Manual Shift Assignments are left alone unless
HR explicitly chooses to trim them.
"""
import hashlib
import json
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, cint, date_diff, flt, get_datetime, getdate, now_datetime, today
from thinknxg_ess_portal.services import identity, roster_rules, shifts, shiftwin, weekly_off
from thinknxg_ess_portal.services.audit import log_event
from thinknxg_ess_portal.services.notifications import notify

MAX_DAYS = 63
WEEK_START = {"Sunday": 6, "Monday": 0, "Saturday": 5}
ENTRY_FIELDS = ["name", "employee", "employee_name", "date", "shift_type", "shift_location", "is_rest_day", "is_weekly_off",
                "note"]


# ------------------------------------------------------------------ access
def can_plan(user=None):
    return identity.is_manager(user) or identity.is_hr(user)


def scope(user=None):
    """Employees the user may roster. None means unrestricted (HR Manager / admin)."""
    if identity.is_hr_manager(user):
        return None
    team = set(identity.team_employees(user))
    if identity.is_hr(user):
        hs = identity.hr_scope_employees(user)
        if hs is None:
            return None
        team |= set(hs)
    return team


def backdate_days():
    return max(cint(identity.settings().get("roster_backdate_days")), 0)


def can_backdate(user=None):
    """Past roster days may be changed by System Managers, ESS Portal Admins and the roles listed in settings."""
    user = user or frappe.session.user
    if not backdate_days():
        return False
    if identity.is_admin(user):
        return True
    allowed = {r.strip() for r in (identity.settings().get("roster_backdate_roles") or "").replace(",", "\n").split("\n")
               if r.strip()}
    return bool(identity.roles(user) & allowed)


def backdate_from():
    return add_days(getdate(today()), -backdate_days())


def is_locked(doc, d, user=None):
    """Past days of a published roster are locked unless the user may backdate and the day is within the window."""
    d = getdate(d)
    if doc.status != "Published" or d >= getdate(today()):
        return False
    return not (can_backdate(user) and d >= backdate_from())


def weekly_offs(employees, start, end):
    """{employee: set(dates)} of holiday-list weekly offs."""
    hol = shifts.holidays_for(list(employees), start, end)
    return {e: {d for d, h in days.items() if h.get("weekly_off")} for e, days in hol.items()}


def assert_employees(employees, user=None):
    sc = scope(user)
    if sc is None:
        return
    bad = [e for e in employees if e not in sc]
    if bad:
        frappe.throw(_("You can only roster people in your team ({0}).").format(", ".join(bad[:3])), frappe.PermissionError)


def roster_employees(name):
    return sorted(set(frappe.get_all("ESS Roster Entry", filters={"roster": name}, pluck="employee")))


def get_roster(name, user=None, write=False):
    user = user or frappe.session.user
    if not frappe.db.exists("ESS Roster", name):
        frappe.throw(_("Roster not found"), frappe.DoesNotExistError)
    doc = frappe.get_doc("ESS Roster", name)
    if identity.is_hr_manager(user) or doc.planner == user:
        return doc
    sc = scope(user)
    emps = roster_employees(name)
    if sc is None or (emps and set(emps) <= sc):
        return doc
    frappe.throw(_("Roster not found"), frappe.DoesNotExistError)


# ------------------------------------------------------------------ entries
def _bulk_insert(roster, rows):
    if not rows:
        return
    now = now_datetime()
    user = frappe.session.user
    fields = ["name", "creation", "modified", "owner", "modified_by", "docstatus", "idx", "roster", "employee",
              "employee_name", "date", "shift_type", "shift_location", "is_rest_day", "is_weekly_off", "note"]
    values = [(frappe.generate_hash(length=12), now, now, user, user, 0, 0, roster, r["employee"], r.get("employee_name"),
               r["date"], r.get("shift_type"), r.get("shift_location"), cint(r.get("is_rest_day")),
               cint(r.get("is_weekly_off")) if cint(r.get("is_rest_day")) else 0, r.get("note"))
              for r in rows]
    frappe.db.bulk_insert("ESS Roster Entry", fields, values, ignore_duplicates=True)


def _prefill_rows(employees, start, end, mode):
    names = dict(frappe.get_all("Employee", filters={"name": ["in", employees or [""]]}, fields=["name", "employee_name"],
                                as_list=True))
    rows = []
    sched = shifts.plan(employees, start, end, with_context=True) if mode == "current" else {}
    wo = weekly_offs(employees, start, end) if cint(identity.settings().get("roster_auto_weekly_off")) else {}
    for emp in employees:
        days = {d["date"]: d for d in sched.get(emp, [])}
        for d in shiftwin.day_range(getdate(start), getdate(end)):
            row = {"employee": emp, "employee_name": names.get(emp), "date": d}
            day = days.get(d)
            if d in wo.get(emp, set()):
                row.update(is_rest_day=1, is_weekly_off=1)
            elif day:
                if day["windows"]:
                    row.update(shift_type=day["windows"][0]["shift_type"], shift_location=day["windows"][0]["location"])
                elif day["rest_day"] or (day["holiday"] and day["holiday"]["weekly_off"]):
                    row.update(is_rest_day=1, is_weekly_off=1 if day["holiday"] and day["holiday"]["weekly_off"] else 0)
            rows.append(row)
    return rows


def create(title, from_date, to_date, employees=None, department=None, branch=None, prefill="current", notes=None):
    if not can_plan():
        frappe.throw(_("Rosters are planned by managers and HR."), frappe.PermissionError)
    fd, td = getdate(from_date), getdate(to_date)
    if td < fd or date_diff(td, fd) >= MAX_DAYS:
        frappe.throw(_("Choose a period of 1 to {0} days.").format(MAX_DAYS))
    if not employees:
        flt = {"status": "Active", "name": ["in", sorted(scope() or identity.team_employees()) or [""]]}
        if scope() is None:
            flt.pop("name")
        if department:
            flt["department"] = department
        if branch:
            flt["branch"] = branch
        employees = frappe.get_all("Employee", filters=flt, pluck="name", limit=500)
    employees = list(dict.fromkeys(employees))
    if not employees:
        frappe.throw(_("Choose at least one employee."))
    assert_employees(employees)
    me = identity.get_employee(required=False)
    company = (me.company if me else None) or frappe.db.get_value("Employee", employees[0], "company")
    doc = frappe.get_doc({"doctype": "ESS Roster", "title": (title or "").strip()[:140] or _("Roster"), "company": company,
                          "department": department, "branch": branch, "from_date": fd, "to_date": td, "status": "Draft",
                          "version": 0, "planner": frappe.session.user, "notes": notes})
    doc.insert(ignore_permissions=True)
    source = None
    if prefill and prefill.startswith("copy:"):
        source, prefill = prefill[5:], "empty"
    _bulk_insert(doc.name, _prefill_rows(employees, fd, td, prefill if prefill in ("current", "empty") else "empty"))
    if source:
        copy_period(doc.name, source)
    log_event("Roster", doc.doctype, doc.name, details=f"created {fd}..{td} employees={len(employees)} prefill={prefill}")
    return doc


def _entry_map(name, employees=None, start=None, end=None):
    flt = {"roster": name}
    if employees:
        flt["employee"] = ["in", list(employees)]
    if start and end:
        flt["date"] = ["between", [start, end]]
    return {(r.employee, getdate(r.date)): r for r in frappe.get_all("ESS Roster Entry", filters=flt, fields=ENTRY_FIELDS)}


def save_cells(name, cells):
    doc = get_roster(name)
    if doc.status == "Archived":
        frappe.throw(_("This roster is archived."))
    cells = list(cells or [])[:3000]
    members = set(roster_employees(name))
    valid_types = set(frappe.get_all("Shift Type", pluck="name"))
    valid_locs = set(frappe.get_all("Shift Location", pluck="name")) if frappe.db.exists("DocType", "Shift Location") else set()
    fd, td = getdate(doc.from_date), getdate(doc.to_date)
    keyed = []
    for c in cells:
        emp, d = c.get("employee"), getdate(c.get("date"))
        if emp not in members:
            frappe.throw(_("{0} is not on this roster.").format(emp))
        if not fd <= d <= td:
            frappe.throw(_("{0} is outside the roster period.").format(d))
        st = c.get("shift_type") or None
        if st and st not in valid_types:
            frappe.throw(_("Unknown shift type {0}.").format(st))
        loc = c.get("shift_location") or None
        if loc and loc not in valid_locs:
            frappe.throw(_("Unknown shift location {0}.").format(loc))
        keyed.append((emp, d, st, loc, 1 if c.get("rest") and not st else 0, (c.get("note") or "")[:140] or None))
    existing = _entry_map(name, {k[0] for k in keyed})
    wo = weekly_offs({k[0] for k in keyed}, fd, td) if keyed else {}
    saved = locked = past = 0
    new_rows = []
    backdate = can_backdate()
    for emp, d, st, loc, rest, note in keyed:
        if is_locked(doc, d):
            locked += 1
            continue
        past += 1 if doc.status == "Published" and d < getdate(today()) else 0
        e = existing.get((emp, d))
        values = {"shift_type": st, "shift_location": loc if st else None, "is_rest_day": rest,
                  "is_weekly_off": 1 if rest and d in wo.get(emp, set()) else 0, "note": note}
        if e:
            if (e.shift_type, e.shift_location if e.shift_type else None, cint(e.is_rest_day), cint(e.is_weekly_off), e.note) != (
                    st, values["shift_location"], rest, values["is_weekly_off"], note):
                frappe.db.set_value("ESS Roster Entry", e.name, values)
                saved += 1
        else:
            new_rows.append({"employee": emp, "date": d, **values})
            saved += 1
    if new_rows:
        names = dict(frappe.get_all("Employee", filters={"name": ["in", list({r["employee"] for r in new_rows})]},
                                    fields=["name", "employee_name"], as_list=True))
        for r in new_rows:
            r["employee_name"] = names.get(r["employee"])
        _bulk_insert(name, new_rows)
    if saved and doc.status == "Published":
        doc.db_set("has_unpublished_changes", 1, update_modified=False)
    if past and backdate:
        log_event("Roster", doc.doctype, doc.name, details=f"{past} past day(s) edited (backdate window {backdate_days()} days)")
    return {"saved": saved, "locked": locked, "past_edited": past}


def mark_weekly_offs(name, employees=None, overwrite=False):
    """Set holiday-list weekly offs as rest days. Without overwrite, days that already have a shift are kept."""
    doc = get_roster(name)
    emps = [e for e in (employees or roster_employees(name)) if e]
    wo = weekly_offs(emps, doc.from_date, doc.to_date)
    current = _entry_map(name, emps)
    cells, kept = [], 0
    for emp in emps:
        for d in sorted(wo.get(emp, set())):
            e = current.get((emp, d))
            if e and e.shift_type and not overwrite:
                kept += 1
                continue
            if e and cint(e.is_rest_day) and cint(e.is_weekly_off):
                continue
            cells.append({"employee": emp, "date": d, "rest": 1, "note": e.note if e else None})
    out = save_cells(name, cells) if cells else {"saved": 0, "locked": 0}
    out["kept_shifts"] = kept
    return out


def add_employees(name, employees, prefill="current"):
    doc = get_roster(name)
    employees = [e for e in dict.fromkeys(employees or []) if e]
    assert_employees(employees)
    current = set(roster_employees(name))
    employees = [e for e in employees if e not in current]
    _bulk_insert(name, _prefill_rows(employees, doc.from_date, doc.to_date, prefill))
    if employees and doc.status == "Published":
        doc.db_set("has_unpublished_changes", 1, update_modified=False)
    return {"added": len(employees)}


def remove_employee(name, employee):
    doc = get_roster(name)
    flt = {"roster": name, "employee": employee}
    if doc.status == "Published":
        flt["date"] = [">=", today()]
        doc.db_set("has_unpublished_changes", 1, update_modified=False)
    frappe.db.delete("ESS Roster Entry", flt)
    return {"removed": employee}


def apply_pattern(name, pattern, employees, start_date=None, end_date=None, stagger=0, shift_location=None,
                  keep_weekly_offs=True):
    doc = get_roster(name)
    pat = frappe.get_doc("ESS Shift Pattern", pattern)
    steps = [None if row.is_rest_day else row.shift_type for row in pat.steps]
    fd = max(getdate(start_date or doc.from_date), getdate(doc.from_date))
    td = min(getdate(end_date or doc.to_date), getdate(doc.to_date))
    dates = list(shiftwin.day_range(fd, td))
    cells = []
    wo = weekly_offs(employees or [], fd, td) if cint(keep_weekly_offs) else {}
    for i, emp in enumerate(employees or []):
        mapping = roster_rules.pattern_for(dates, steps, offset=i * cint(stagger))
        for d, st in mapping.items():
            if d in wo.get(emp, set()):
                st = None
            cells.append({"employee": emp, "date": d, "shift_type": st, "rest": st is None, "shift_location": shift_location})
    return save_cells(name, cells)


def copy_period(name, source, keep_weekly_offs=True):
    """Fill this roster from another, repeating the source's whole weeks so weekdays line up."""
    doc = get_roster(name)
    src = get_roster(source)
    span = date_diff(src.to_date, src.from_date) + 1
    period = (span // 7) * 7 or span
    src_entries = _entry_map(source)
    members = set(roster_employees(name))
    cells = []
    for d in shiftwin.day_range(getdate(doc.from_date), getdate(doc.to_date)):
        s_date = add_days(getdate(src.from_date), date_diff(d, src.from_date) % period)
        for emp in members:
            e = src_entries.get((emp, getdate(s_date)))
            if e:
                cells.append({"employee": emp, "date": d, "shift_type": e.shift_type, "shift_location": e.shift_location,
                              "rest": cint(e.is_rest_day)})
    out = save_cells(name, cells)
    if cint(keep_weekly_offs):
        mark_weekly_offs(name, overwrite=True)
    return out


def set_requirements(name, rows):
    doc = get_roster(name)
    doc.set("requirements", [])
    for r in rows or []:
        if r.get("shift_type") and cint(r.get("min_staff")) > 0:
            doc.append("requirements", {"shift_type": r["shift_type"], "weekday": r.get("weekday") or "All days",
                                        "min_staff": cint(r["min_staff"])})
    doc.save(ignore_permissions=True)
    return {"ok": True}


# ------------------------------------------------------------------ grid + validation
def validate(doc, entries=None):
    s = identity.settings()
    entries = entries if entries is not None else list(_entry_map(doc.name).values())
    by_emp, counts, names = defaultdict(list), defaultdict(int), {}
    for e in entries:
        names[e.employee] = e.employee_name or e.employee
        if e.shift_type and not cint(e.is_rest_day):
            st = shifts.shift_type(e.shift_type)
            win = shiftwin.window(getdate(e.date), st["start"], st["end"]) if st else None
            if win:
                by_emp[e.employee].append({"date": getdate(e.date), "start": win["start"], "end": win["end"],
                                           "hours": win["hours"], "shift_type": e.shift_type})
            counts[(getdate(e.date), e.shift_type)] += 1
    violations = roster_rules.check(by_emp, min_rest_hours=flt(s.get("roster_min_rest_hours")),
                                    max_consecutive_days=cint(s.get("roster_max_consecutive_days")),
                                    max_weekly_hours=flt(s.get("roster_max_weekly_hours")),
                                    week_start=WEEK_START.get(s.get("roster_week_start") or "Sunday", 6), names=names)
    dates = list(shiftwin.day_range(getdate(doc.from_date), getdate(doc.to_date)))
    gaps = roster_rules.coverage(counts, [r.as_dict() for r in doc.requirements], dates)

    conflicts = []
    emps = sorted(names)
    lv = shifts.leaves(emps, doc.from_date, doc.to_date)
    for e in entries:
        d = getdate(e.date)
        leave = lv.get(e.employee, {}).get(d)
        if e.shift_type and leave and not leave["half_day"]:
            conflicts.append({"employee": e.employee, "date": str(d), "kind": "leave", "severity": "warning",
                              "message": _("{0} has {1} leave ({2}) on {3}.").format(names[e.employee], leave["status"].lower(),
                                                                                    leave["leave_type"], d)})
    wo = weekly_offs(sorted(names), doc.from_date, doc.to_date) if names else {}
    on_wo = defaultdict(list)
    for e in entries:
        if e.shift_type and not cint(e.is_rest_day) and getdate(e.date) in wo.get(e.employee, set()):
            on_wo[e.employee].append(getdate(e.date))
    for emp, ds in on_wo.items():
        conflicts.append({"employee": emp, "date": str(ds[0]), "kind": "weekly_off_shift", "severity": "info",
                          "message": _("{0} is planned on {1} weekly off(s): {2}. Once attendance is marked they can "
                                       "claim compensatory leave.").format(names[emp], len(ds),
                                                                         ", ".join(d.strftime("%a %d %b") for d in ds[:4]))})
    start = max(getdate(doc.from_date), getdate(today()))
    unplanned = sum(1 for e in entries if getdate(e.date) >= start and not e.shift_type and not cint(e.is_rest_day))
    if unplanned:
        conflicts.append({"kind": "unplanned", "severity": "info",
                          "message": _("{0} upcoming day(s) have no shift or rest day yet.").format(unplanned)})
    defaults = frappe.get_all("Employee", filters={"name": ["in", emps or [""]], "default_shift": ["is", "set"]},
                              fields=["name", "employee_name", "default_shift"])
    rest_emps = {e.employee for e in entries if cint(e.is_rest_day)}
    for d in defaults:
        if d.name in rest_emps:
            conflicts.append({"employee": d.name, "kind": "default_shift", "severity": "warning",
                              "message": _("{0} has a default shift ({1}). On rest days with no Shift Assignment, thinkNXG HR "
                                           "falls back to it and may mark absence. Clear the default shift for rostered staff.").format(
                                  d.employee_name, d.default_shift)})
    if emps and getdate(doc.to_date) >= start:
        manual = frappe.db.sql("""select name, employee, shift_type, start_date, end_date from `tabShift Assignment`
            where employee in %(emps)s and docstatus=1 and status='Active' and ifnull(ess_roster,'')=''
              and start_date<=%(end)s and (end_date is null or end_date>=%(start)s)""" if frappe.get_meta(
            "Shift Assignment").has_field("ess_roster") else """select name, employee, shift_type, start_date, end_date
            from `tabShift Assignment` where employee in %(emps)s and docstatus=1 and status='Active'
              and start_date<=%(end)s and (end_date is null or end_date>=%(start)s)""",
                               {"emps": emps, "start": start, "end": doc.to_date}, as_dict=True)
        for m in manual:
            conflicts.append({"employee": m.employee, "kind": "manual_assignment", "severity": "blocker",
                              "assignment": m.name,
                              "message": _("{0} has a manual Shift Assignment {1} ({2}, from {3}{4}). Publishing skips them "
                                           "unless HR trims it.").format(names.get(m.employee, m.employee), m.name, m.shift_type,
                                                                         m.start_date, f" to {m.end_date}" if m.end_date else _(", open-ended"))})
    others = frappe.db.sql("""select distinct e.employee, e.roster, r.title from `tabESS Roster Entry` e
        join `tabESS Roster` r on r.name=e.roster
        where r.name!=%(name)s and r.status!='Archived' and e.employee in %(emps)s and e.date between %(s)s and %(e)s
          and (ifnull(e.shift_type,'')!='' or e.is_rest_day=1)""",
                           {"name": doc.name, "emps": emps or [""], "s": doc.from_date, "e": doc.to_date}, as_dict=True)
    for o in others:
        conflicts.append({"employee": o.employee, "kind": "other_roster", "severity": "warning",
                          "message": _("{0} is also planned on roster {1} for some of these dates. The last one published wins.").format(
                              names.get(o.employee, o.employee), o.title)})
    errors = sum(1 for v in violations if v["severity"] == "error") + sum(1 for c in conflicts if c["severity"] == "blocker")
    return {"violations": violations, "gaps": gaps, "conflicts": conflicts,
            "summary": {"errors": errors, "warnings": sum(1 for v in violations if v["severity"] == "warning")
                        + sum(1 for c in conflicts if c["severity"] == "warning"), "gaps": len(gaps), "unplanned": unplanned}}


def grid(name):
    doc = get_roster(name)
    entries = list(_entry_map(name).values())
    emps = sorted({e.employee for e in entries})
    info = {r.name: r for r in frappe.get_all("Employee", filters={"name": ["in", emps or [""]]},
                                              fields=["name", "employee_name", "designation", "department", "branch",
                                                      "default_shift", "image"])}
    cells = defaultdict(dict)
    for e in entries:
        cells[e.employee][str(getdate(e.date))] = {"s": e.shift_type, "l": e.shift_location, "r": cint(e.is_rest_day),
                                                    "w": cint(e.is_weekly_off), "n": e.note}
    hol = shifts.holidays_for(emps, doc.from_date, doc.to_date)
    lv = shifts.leaves(emps, doc.from_date, doc.to_date)
    used = {e.shift_type for e in entries if e.shift_type} | {r.shift_type for r in doc.requirements}
    types = [t for t in shifts.all_shift_types() if t and not t.get("weekly_off")]
    patterns = []
    for p in frappe.get_all("ESS Shift Pattern", filters={"is_active": 1}, pluck="name"):
        pd = frappe.get_cached_doc("ESS Shift Pattern", p)
        patterns.append({"name": p, "steps": [None if s.is_rest_day else s.shift_type for s in pd.steps],
                         "description": pd.description})
    locations = frappe.get_all("Shift Location", fields=["name", "location_name"]) if frappe.db.exists("DocType", "Shift Location") else []
    pending = frappe.db.count("ESS Roster Change Request", {"roster": name, "status": ["in", ["Pending Colleague", "Pending Approval"]]})
    return {
        "roster": {k: doc.get(k) for k in ("name", "title", "company", "department", "branch", "from_date", "to_date", "status",
                                           "version", "has_unpublished_changes", "published_on", "published_by", "planner", "notes")},
        "requirements": [{"shift_type": r.shift_type, "weekday": r.weekday, "min_staff": r.min_staff} for r in doc.requirements],
        "employees": [{"name": e, "employee_name": info[e].employee_name if e in info else e,
                       "designation": info[e].designation if e in info else None,
                       "default_shift": info[e].default_shift if e in info else None,
                       "department": info[e].department if e in info else None,
                       "branch": info[e].branch if e in info else None,
                       "image": info[e].image if e in info else None} for e in sorted(emps, key=lambda x: (info[x].employee_name if x in info else x))],
        "dates": [str(d) for d in shiftwin.day_range(getdate(doc.from_date), getdate(doc.to_date))],
        "cells": cells,
        "holidays": {e: {str(d): h for d, h in hol.get(e, {}).items()} for e in emps},
        "leaves": {e: {str(d): x for d, x in lv.get(e, {}).items()} for e in emps},
        "shift_types": types, "used_shift_types": sorted(used), "patterns": patterns, "locations": locations,
        "today": str(getdate(today())), "pending_requests": pending,
        "can_trim_manual": identity.is_hr(), "validation": validate(doc, entries),
        "can_backdate": can_backdate(), "backdate_from": str(backdate_from()) if can_backdate() else None,
        "auto_weekly_off": bool(cint(identity.settings().get("roster_auto_weekly_off"))),
        "rest_as_weekly_off": weekly_off.roster_rest_enabled(),
        "weekend_days": [x.strip() for x in (identity.settings().get("weekend_days") or "").split(",") if x.strip()],
    }


# ------------------------------------------------------------------ publishing
def _assignment_meta():
    return frappe.get_meta("Shift Assignment")


def _end_assignment(name, end):
    doc = frappe.get_doc("Shift Assignment", name)
    if getdate(end) < getdate(doc.start_date):
        return _cancel_assignment(name)
    doc.flags.ignore_permissions = True
    try:
        doc.end_date = getdate(end)
        doc.save()
    except frappe.UpdateAfterSubmitError:
        frappe.db.set_value("Shift Assignment", name, "end_date", getdate(end))
        weekly_off.queue(name)
        doc.add_comment("Info", _("End date set to {0} by ESS roster publishing.").format(end))
    return "ended"


def _cancel_assignment(name):
    doc = frappe.get_doc("Shift Assignment", name)
    doc.flags.ignore_permissions = True
    try:
        doc.cancel()
    except frappe.ValidationError:
        frappe.db.set_value("Shift Assignment", name, "status", "Inactive")
        weekly_off.queue(name)
        doc.add_comment("Info", _("Set inactive by ESS roster publishing."))
    return "cancelled"


def _deactivate(name):
    doc = frappe.get_doc("Shift Assignment", name)
    doc.flags.ignore_permissions = True
    try:
        doc.status = "Inactive"
        doc.save()
    except frappe.ValidationError:
        frappe.db.set_value("Shift Assignment", name, "status", "Inactive")
        weekly_off.queue(name)
    doc.add_comment("Info", _("Set inactive by ESS roster publishing (trim manual assignments)."))


def _create_assignment(employee, company, shift_type, location, start, end, roster):
    meta = _assignment_meta()
    sa = frappe.get_doc({"doctype": "Shift Assignment", "employee": employee, "company": company,
                         "shift_type": shift_type, "start_date": start, "end_date": end, "status": "Active"})
    if location and meta.has_field("shift_location"):
        sa.shift_location = location
    if meta.has_field("ess_roster"):
        sa.ess_roster = roster
    sa.flags.ignore_permissions = True
    sa.insert()
    sa.submit()
    return sa.name


def _keyer():
    """Roster entry -> assignment key. Rest days become Weekly Off assignments when that setting is on."""
    rest = (weekly_off.default_type(), "") if weekly_off.roster_rest_enabled() else None

    def key(e):
        if e.shift_type and not cint(e.is_rest_day):
            return (e.shift_type, e.shift_location or "")
        return rest if cint(e.is_rest_day) else None
    return key


def _digest(entries):
    raw = json.dumps(sorted((str(getdate(e.date)), e.shift_type or "", e.shift_location or "", cint(e.is_rest_day))
                            for e in entries))
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def publish(name, trim_manual=False, backfill=False):
    doc = get_roster(name)
    if trim_manual and not identity.is_hr():
        frappe.throw(_("Only HR can trim manual shift assignments."), frappe.PermissionError)
    if cint(backfill) and not can_backdate():
        frappe.throw(_("You aren't allowed to change past roster days."), frappe.PermissionError)
    report = _publish(doc, trim_manual=bool(cint(trim_manual)))
    if cint(backfill):
        report["past"] = _backfill(doc)
    return report


def _carve(emp, company, a, b):
    """Free [a, b] of roster-made assignments, keeping their parts before a and after b."""
    ended = cancelled = 0
    loc = "shift_location" if _assignment_meta().has_field("shift_location") else "null"
    for g in frappe.db.sql(f"""select name, shift_type, start_date, end_date, ess_roster, {loc} as shift_location
            from `tabShift Assignment` where employee=%s and docstatus=1 and status='Active' and ifnull(ess_roster,'')!=''
              and start_date<=%s and (end_date is null or end_date>=%s)""", (emp, b, a), as_dict=True):
        tail_end = g.end_date
        if getdate(g.start_date) < getdate(a):
            _end_assignment(g.name, add_days(a, -1))
            ended += 1
        else:
            _cancel_assignment(g.name)
            cancelled += 1
        if tail_end is None or getdate(tail_end) > getdate(b):
            _create_assignment(emp, company, g.shift_type, g.shift_location, add_days(b, 1), tail_end, g.ess_roster)
    return ended, cancelled


def _backfill(doc):
    """Apply past roster days within the backdate window.

    Days with submitted attendance are never touched; manual (untagged) assignments are never changed.
    Unplanned past cells are ignored, so this only fills or corrects days the planner actually set.
    """
    out = {"from": None, "to": None, "created": 0, "ended": 0, "cancelled": 0, "unchanged": 0,
           "skipped_attendance": 0, "skipped_manual": [], "errors": []}
    a = max(getdate(doc.from_date), backdate_from())
    b = min(getdate(doc.to_date), add_days(getdate(today()), -1))
    if a > b:
        return out
    out.update({"from": str(a), "to": str(b)})
    entries = frappe.get_all("ESS Roster Entry", filters={"roster": doc.name, "date": ["between", [a, b]]},
                             fields=ENTRY_FIELDS)
    by_emp = defaultdict(list)
    for e in entries:
        if e.shift_type or cint(e.is_rest_day):
            by_emp[e.employee].append(e)
    companies = dict(frappe.get_all("Employee", filters={"name": ["in", list(by_emp) or [""]]},
                                    fields=["name", "company"], as_list=True))
    loc = "shift_location" if _assignment_meta().has_field("shift_location") else "null"
    keyer = _keyer()
    for emp, rows in by_emp.items():
        marked = {getdate(x) for x in frappe.get_all("Attendance", filters={"employee": emp, "docstatus": 1,
                                                                            "attendance_date": ["between", [a, b]]},
                                                     pluck="attendance_date")}
        out["skipped_attendance"] += sum(1 for r in rows if getdate(r.date) in marked)
        keyed = [(getdate(r.date), keyer(r)) for r in rows]
        for seg in roster_rules.segments(keyed, blocked=marked):
            frappe.db.savepoint("ess_roster_backfill")
            try:
                existing = frappe.db.sql(f"""select name, shift_type, ifnull(ess_roster,'') ess_roster, {loc} as shift_location,
                        start_date, end_date from `tabShift Assignment`
                    where employee=%s and docstatus=1 and status='Active' and start_date<=%s
                      and (end_date is null or end_date>=%s)""", (emp, seg["end"], seg["start"]), as_dict=True)
                manual = [x for x in existing if not x.ess_roster]
                if manual:
                    out["skipped_manual"].append({"employee": emp, "from": str(seg["start"]), "to": str(seg["end"]),
                                                  "assignments": [m.name for m in manual]})
                    continue
                key = seg["key"]
                covers = (len(existing) == 1 and key and existing[0].shift_type == key[0]
                          and (existing[0].shift_location or "") == key[1]
                          and getdate(existing[0].start_date) <= seg["start"]
                          and (not existing[0].end_date or getdate(existing[0].end_date) >= seg["end"]))
                if covers or (key is None and not existing):
                    out["unchanged"] += 1
                    continue
                ended, cancelled = _carve(emp, companies.get(emp), seg["start"], seg["end"])
                out["ended"] += ended
                out["cancelled"] += cancelled
                if key:
                    _create_assignment(emp, companies.get(emp), key[0], key[1] or None, seg["start"], seg["end"], doc.name)
                    out["created"] += 1
            except Exception as ex:
                frappe.db.rollback(save_point="ess_roster_backfill")
                frappe.local.message_log = []
                out["errors"].append({"employee": emp, "from": str(seg["start"]), "error": str(ex)[:300]})
    log_event("Roster", doc.doctype, doc.name,
              details=f"past days {out['from']}..{out['to']} created={out['created']} ended={out['ended']} "
                      f"cancelled={out['cancelled']} skipped_attendance={out['skipped_attendance']} "
                      f"skipped_manual={len(out['skipped_manual'])} errors={len(out['errors'])}")
    return out


def _publish(doc, trim_manual=False, employees=None, window=None, notify_people=True):
    if doc.status == "Archived":
        frappe.throw(_("This roster is archived."))
    start = max(getdate(doc.from_date), getdate(today()))
    end = getdate(doc.to_date)
    if window:
        start, end = max(start, getdate(window[0])), min(end, getdate(window[1]))
    report = {"created": 0, "ended": 0, "cancelled": 0, "employees": 0, "conflicts": [], "trimmed": [], "errors": [],
              "from": str(start), "to": str(end)}
    has_tag = _assignment_meta().has_field("ess_roster")
    if not has_tag:
        frappe.throw(_("Shift Assignment is missing the ESS roster field. Run bench migrate."))
    entries = []
    if start <= end:
        flt = {"roster": doc.name, "date": ["between", [start, end]]}
        if employees:
            flt["employee"] = ["in", list(employees)]
        entries = frappe.get_all("ESS Roster Entry", filters=flt, fields=ENTRY_FIELDS)
    by_emp = defaultdict(list)
    for e in entries:
        by_emp[e.employee].append(e)
    if start <= end:
        tagged = frappe.get_all("Shift Assignment", filters={"ess_roster": doc.name, "docstatus": 1, "status": "Active",
                                                             "start_date": ["<=", end]}, pluck="employee")
        for emp in tagged:
            if not employees or emp in employees:
                by_emp.setdefault(emp, [])
    companies = dict(frappe.get_all("Employee", filters={"name": ["in", list(by_emp) or [""]]},
                                    fields=["name", "company"], as_list=True))
    keyer = _keyer()
    wo_report = weekly_off.reset_report()

    for emp in sorted(by_emp):
        if start > end:
            break
        frappe.db.savepoint("ess_roster_publish")
        try:
            with weekly_off.deferred():
                manual = frappe.db.sql("""select name, start_date, end_date, shift_type from `tabShift Assignment`
                    where employee=%s and docstatus=1 and status='Active' and ifnull(ess_roster,'')=''
                      and start_date<=%s and (end_date is null or end_date>=%s)""", (emp, end, start), as_dict=True)
                if manual:
                    if not trim_manual:
                        report["conflicts"].append({"employee": emp, "assignments": [m.name for m in manual]})
                        continue
                    for m in manual:
                        if getdate(m.start_date) < start:
                            _end_assignment(m.name, add_days(start, -1))
                        else:
                            _deactivate(m.name)
                        report["trimmed"].append(m.name)
                generated = frappe.db.sql("""select name, shift_type, start_date, end_date, ess_roster,
                        {loc} as shift_location from `tabShift Assignment`
                    where employee=%s and docstatus=1 and status='Active' and ifnull(ess_roster,'')!=''
                      and start_date<=%s and (end_date is null or end_date>=%s)""".format(
                    loc="shift_location" if _assignment_meta().has_field("shift_location") else "null"),
                    (emp, end, start), as_dict=True)
                for g in generated:
                    tail_end = g.end_date
                    if getdate(g.start_date) < start:
                        _end_assignment(g.name, add_days(start, -1))
                        report["ended"] += 1
                    else:
                        _cancel_assignment(g.name)
                        report["cancelled"] += 1
                    if tail_end is None or getdate(tail_end) > end:
                        _create_assignment(emp, companies.get(emp), g.shift_type, g.shift_location, add_days(end, 1),
                                           tail_end, g.ess_roster)
                keyed = [(getdate(e.date), keyer(e)) for e in by_emp[emp]]
                for run in roster_rules.runs(keyed):
                    _create_assignment(emp, companies.get(emp), run["key"][0], run["key"][1] or None, run["start"], run["end"],
                                       doc.name)
                    report["created"] += 1
                report["employees"] += 1
        except Exception as ex:
            frappe.db.rollback(save_point="ess_roster_publish")
            frappe.local.message_log = []
            report["errors"].append({"employee": emp, "error": str(ex)[:300]})

    # notifications + digest
    old = json.loads(doc.published_digest or "{}")
    new = dict(old)
    changed = []
    all_entries = frappe.get_all("ESS Roster Entry", filters={"roster": doc.name, "date": [">=", start]}, fields=ENTRY_FIELDS)
    grouped = defaultdict(list)
    for e in all_entries:
        grouped[e.employee].append(e)
    for emp, rows in grouped.items():
        if employees and emp not in employees:
            continue
        dg = _digest(rows)
        if old.get(emp) != dg:
            changed.append(emp)
        new[emp] = dg
    full = not employees and not window
    values = {"published_digest": json.dumps(new), "published_on": now_datetime(), "published_by": frappe.session.user,
              "status": "Published", "version": cint(doc.version) + 1}
    if full:
        values["has_unpublished_changes"] = 1 if (report["conflicts"] or report["errors"]) else 0
    doc.db_set(values, update_modified=True)
    if notify_people and cint(identity.settings().get("roster_notify_on_publish")):
        users = dict(frappe.get_all("Employee", filters={"name": ["in", changed or [""]]}, fields=["name", "user_id"],
                                    as_list=True))
        first = not old
        for emp in changed:
            notify(users.get(emp), "Attendance",
                   _("Your roster is published") if first or emp not in old else _("Your roster has changed"),
                   _("{0}: {1} to {2}").format(doc.title, doc.from_date, doc.to_date), "/ess/roster", doc.doctype, doc.name)
    report["notified"] = len(changed)
    report["weekly_off"] = wo_report
    log_event("Roster", doc.doctype, doc.name,
              details=f"publish v{values['version']} {report['from']}..{report['to']} created={report['created']} "
                      f"ended={report['ended']} cancelled={report['cancelled']} conflicts={len(report['conflicts'])} "
                      f"errors={len(report['errors'])} trimmed={len(report['trimmed'])}")
    return report


def archive(name):
    doc = get_roster(name)
    doc.db_set("status", "Archived")
    log_event("Roster", doc.doctype, doc.name, details="archived (published Shift Assignments are kept)")
    return {"status": "Archived"}


# ------------------------------------------------------------------ change requests and swaps
def _published_entries(employee, fd, td):
    return frappe.db.sql("""select e.name, e.roster, e.date, e.shift_type, e.shift_location, e.is_rest_day
        from `tabESS Roster Entry` e join `tabESS Roster` r on r.name=e.roster
        where r.status='Published' and e.employee=%s and e.date between %s and %s order by e.date""",
                         (employee, fd, td), as_dict=True)


def _approver_for(roster_doc, emp):
    my_user = frappe.db.get_value("Employee", emp, "user_id")
    if roster_doc.planner and roster_doc.planner != my_user:
        return roster_doc.planner
    rt = frappe.db.get_value("Employee", emp, "reports_to")
    return frappe.db.get_value("Employee", rt, "user_id") if rt else None


def create_change(emp, request_type, from_date, to_date, reason, requested_shift_type=None, swap_with=None):
    s = identity.settings()
    if not cint(s.get("allow_roster_change_requests")):
        frappe.throw(_("Roster change requests are turned off. Talk to your manager."))
    if request_type == "Swap with colleague" and not cint(s.get("allow_shift_swaps")):
        frappe.throw(_("Shift swaps are turned off."))
    if request_type not in ("Change shift", "Request rest day", "Swap with colleague"):
        frappe.throw(_("Unknown request type."))
    fd, td = getdate(from_date), getdate(to_date)
    if td < fd or date_diff(td, fd) > 13:
        frappe.throw(_("Requests can cover up to 14 days."))
    mine = _published_entries(emp.name, fd, td)
    if len(mine) != date_diff(td, fd) + 1:
        frappe.throw(_("These dates aren't all on a published roster. Ask your manager directly."))
    rosters = {e.roster for e in mine}
    if len(rosters) != 1:
        frappe.throw(_("These dates span more than one roster. Request each period separately."))
    roster_name = rosters.pop()
    first = shifts.plan([emp.name], fd, fd, with_context=False)[emp.name][0]["windows"]
    first_start = first[0]["start"] if first else get_datetime(f"{fd} 00:00:00")
    notice = cint(s.get("roster_change_notice_hours"))
    if notice and first_start < add_to_date(now_datetime(), hours=notice):
        frappe.throw(_("Changes need at least {0} hours' notice. Contact your manager for urgent changes.").format(notice))
    if request_type == "Swap with colleague":
        if not swap_with or swap_with == emp.name:
            frappe.throw(_("Choose the colleague to swap with."))
        theirs = [e for e in _published_entries(swap_with, fd, td) if e.roster == roster_name]
        if len(theirs) != len(mine):
            frappe.throw(_("Your colleague isn't on the same roster for these dates."))
        if all((a.shift_type, cint(a.is_rest_day)) == (b.shift_type, cint(b.is_rest_day)) for a, b in zip(mine, theirs)):
            frappe.throw(_("You and your colleague have the same shifts on these dates."))
    if requested_shift_type and not frappe.db.exists("Shift Type", requested_shift_type):
        frappe.throw(_("Unknown shift type."))
    if frappe.db.exists("ESS Roster Change Request", {"employee": emp.name, "status": ["in", ["Pending Colleague", "Pending Approval"]],
                                                      "from_date": ["<=", td], "to_date": [">=", fd]}):
        frappe.throw(_("You already have a pending request for these dates."))
    roster_doc = frappe.get_doc("ESS Roster", roster_name)
    doc = frappe.get_doc({"doctype": "ESS Roster Change Request", "employee": emp.name, "request_type": request_type,
                          "from_date": fd, "to_date": td, "reason": (reason or "").strip()[:500],
                          "requested_shift_type": requested_shift_type if request_type == "Change shift" else None,
                          "swap_with": swap_with if request_type == "Swap with colleague" else None,
                          "roster": roster_name, "approver": _approver_for(roster_doc, emp.name),
                          "status": "Pending Colleague" if request_type == "Swap with colleague" else "Pending Approval"})
    doc.insert(ignore_permissions=True)
    if doc.status == "Pending Colleague":
        notify(frappe.db.get_value("Employee", swap_with, "user_id"), "Approvals",
               _("{0} asked to swap shifts with you").format(emp.employee_name), f"{fd} → {td}",
               f"/ess/roster?swap={doc.name}", doc.doctype, doc.name)
    else:
        notify(doc.approver, "Approvals", _("Roster change request from {0}").format(emp.employee_name),
               f"{request_type}: {fd} → {td}", "/ess/team/approvals", doc.doctype, doc.name)
    return doc


def respond_swap(name, accept, emp):
    doc = frappe.get_doc("ESS Roster Change Request", name)
    if doc.swap_with != emp.name or doc.status != "Pending Colleague":
        frappe.throw(_("This swap request isn't waiting for you."), frappe.PermissionError)
    doc.colleague_response = "Accepted" if accept else "Declined"
    doc.colleague_responded_on = now_datetime()
    doc.status = "Pending Approval" if accept else "Rejected"
    doc.save(ignore_permissions=True)
    requester = frappe.db.get_value("Employee", doc.employee, "user_id")
    if accept:
        notify(doc.approver, "Approvals", _("Shift swap to approve: {0} and {1}").format(doc.employee_name, doc.swap_with_name),
               f"{doc.from_date} → {doc.to_date}", "/ess/team/approvals", doc.doctype, doc.name)
        notify(requester, "Attendance", _("{0} accepted your swap. It now needs manager approval.").format(doc.swap_with_name),
               "", "/ess/roster", doc.doctype, doc.name)
    else:
        notify(requester, "Attendance", _("{0} declined your swap request").format(doc.swap_with_name), "", "/ess/roster",
               doc.doctype, doc.name)
    return {"status": doc.status}


def decide_change(doc, approved, comment=None):
    if doc.status != "Pending Approval":
        frappe.throw(_("This request is not awaiting approval."))
    if approved:
        apply_change(doc)
    doc.db_set({"status": "Approved" if approved else "Rejected", "reviewed_by": frappe.session.user,
                "reviewed_on": now_datetime(), "review_comment": comment})
    for emp in filter(None, [doc.employee, doc.swap_with]):
        notify(frappe.db.get_value("Employee", emp, "user_id"), "Attendance",
               _("Roster change {0}").format(_("approved") if approved else _("rejected")),
               comment or f"{doc.from_date} → {doc.to_date}", "/ess/roster", doc.doctype, doc.name)


def apply_change(doc):
    roster_doc = frappe.get_doc("ESS Roster", doc.roster)
    fd, td = getdate(doc.from_date), getdate(doc.to_date)
    if fd < getdate(today()):
        frappe.throw(_("This request starts in the past and can no longer be applied."))
    emps = [doc.employee] + ([doc.swap_with] if doc.request_type == "Swap with colleague" else [])
    current = _entry_map(doc.roster, emps, fd, td)
    for d in shiftwin.day_range(fd, td):
        mine = current.get((doc.employee, d))
        if not mine:
            frappe.throw(_("{0} is not on the roster for {1}.").format(doc.employee_name, d))
        if doc.request_type == "Swap with colleague":
            theirs = current.get((doc.swap_with, d))
            if not theirs:
                frappe.throw(_("{0} is not on the roster for {1}.").format(doc.swap_with_name, d))
            for a, b in ((mine, theirs), (theirs, mine)):
                frappe.db.set_value("ESS Roster Entry", a.name, {"shift_type": b.shift_type, "shift_location": b.shift_location,
                                                                 "is_rest_day": cint(b.is_rest_day),
                                                                 "note": _("Swap {0}").format(doc.name)})
        elif doc.request_type == "Request rest day":
            frappe.db.set_value("ESS Roster Entry", mine.name, {"shift_type": None, "shift_location": None, "is_rest_day": 1,
                                                                "note": _("Change {0}").format(doc.name)})
        else:
            frappe.db.set_value("ESS Roster Entry", mine.name, {"shift_type": doc.requested_shift_type, "is_rest_day": 0,
                                                                "note": _("Change {0}").format(doc.name)})
    report = _publish(roster_doc, employees=emps, window=(fd, td), notify_people=False)
    if report["conflicts"] or report["errors"]:
        frappe.throw(_("The change was saved but could not be published: {0}").format(
            (report["errors"] or [{"error": _("manual Shift Assignment in the way")}])[0]["error"]))
    log_event("Roster", doc.doctype, doc.name, details=f"applied to roster {doc.roster}: {report}")
