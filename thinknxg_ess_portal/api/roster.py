import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, getdate, now_datetime, today
from thinknxg_ess_portal.api._guard import guard, parse
from thinknxg_ess_portal.services import hrms, identity, roster, shifts
from thinknxg_ess_portal.services.idempotency import run_once


# ------------------------------------------------------------------ employee
@frappe.whitelist(methods=["GET"])
def my_schedule(from_date=None, to_date=None):
    emp = guard("enable_roster")
    fd = getdate(from_date or today())
    td = getdate(to_date or add_days(fd, 34))
    if date_diff(td, fd) > 92 or td < fd:
        frappe.throw(_("Choose up to 93 days."))
    days = shifts.schedule(emp.name, fd, td)
    reqs = frappe.get_all("ESS Roster Change Request", filters={"employee": emp.name, "to_date": [">=", add_days(today(), -30)]},
                          fields=["name", "request_type", "status", "from_date", "to_date", "requested_shift_type",
                                  "swap_with_name", "reason", "review_comment", "creation"], order_by="creation desc")
    incoming = frappe.get_all("ESS Roster Change Request", filters={"swap_with": emp.name, "status": "Pending Colleague"},
                              fields=["name", "employee_name", "from_date", "to_date", "reason", "creation"])
    s = identity.settings()
    return {"days": days, "requests": reqs, "incoming_swaps": incoming,
            "allow_requests": bool(cint(s.get("allow_roster_change_requests"))),
            "allow_swaps": bool(cint(s.get("allow_shift_swaps"))),
            "notice_hours": cint(s.get("roster_change_notice_hours")),
            "shift_types": [t for t in shifts.all_shift_types() if t]}


@frappe.whitelist(methods=["GET"])
def swap_candidates(from_date, to_date):
    emp = guard("enable_roster")
    mine = roster._published_entries(emp.name, getdate(from_date), getdate(to_date))
    if not mine:
        return []
    rosters = list({e.roster for e in mine})
    rows = frappe.db.sql("""select e.employee, e.employee_name, count(*) n from `tabESS Roster Entry` e
        where e.roster in %(r)s and e.employee!=%(me)s and e.date between %(f)s and %(t)s
        group by e.employee, e.employee_name having n=%(n)s order by e.employee_name""",
                         {"r": rosters, "me": emp.name, "f": from_date, "t": to_date, "n": len(mine)}, as_dict=True)
    sched = shifts.plan([r.employee for r in rows], from_date, to_date, with_context=False) if rows else {}
    return [{"employee": r.employee, "employee_name": r.employee_name,
             "shifts": [", ".join(w["code"] for w in d["windows"]) or ("Rest" if d["rest_day"] else "—")
                        for d in sched.get(r.employee, [])]} for r in rows]


@frappe.whitelist(methods=["POST"])
def request_change(request_type, from_date, to_date, reason, requested_shift_type=None, swap_with=None,
                   client_request_id=None):
    emp = guard("enable_roster")

    def do():
        doc = roster.create_change(emp, request_type, from_date, to_date, reason, requested_shift_type, swap_with)
        return {"doctype": doc.doctype, "name": doc.name, "status": doc.status}

    return run_once(client_request_id, "roster_change", do)


@frappe.whitelist(methods=["POST"])
def respond_swap(name, accept):
    emp = guard("enable_roster")
    return roster.respond_swap(name, bool(cint(accept)), emp)


@frappe.whitelist(methods=["POST"])
def cancel_request(name):
    emp = guard("enable_roster")
    doc = frappe.get_doc("ESS Roster Change Request", name)
    if doc.employee != emp.name or doc.status not in ("Pending Colleague", "Pending Approval"):
        frappe.throw(_("This request can't be cancelled."))
    doc.db_set("status", "Cancelled")
    return {"name": name, "status": "Cancelled"}


@frappe.whitelist(methods=["GET"])
def holidays(year=None):
    emp = guard()
    y = cint(year) or getdate().year
    hl = hrms.holiday_list(emp.name)
    rows = frappe.get_all("Holiday", filters={"parent": hl, "holiday_date": ["between", [f"{y}-01-01", f"{y}-12-31"]]},
                          fields=["holiday_date", "description", "weekly_off"], order_by="holiday_date asc") if hl else []
    weekly = {}
    for r in rows:
        if r.weekly_off:
            wd = getdate(r.holiday_date).strftime("%A")
            weekly[wd] = weekly.get(wd, 0) + 1
    rest = frappe.db.sql("""select count(*) from `tabESS Roster Entry` e join `tabESS Roster` r on r.name=e.roster
        where r.status='Published' and e.employee=%s and e.is_rest_day=1 and year(e.date)=%s""", (emp.name, y))[0][0]
    return {"year": y, "holiday_list": hl, "holidays": [r for r in rows if not r.weekly_off],
            "weekly_offs": weekly, "weekly_off_count": sum(weekly.values()), "roster_rest_days": rest,
            "years": [y - 1, y, y + 1]}


def _ics_escape(s):
    return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


@frappe.whitelist(methods=["GET"])
def calendar_ics(from_date=None, to_date=None):
    emp = guard()
    fd = getdate(from_date or today())
    td = getdate(to_date or add_days(fd, 90))
    if date_diff(td, fd) > 366:
        td = add_days(fd, 366)
    stamp = now_datetime().strftime("%Y%m%dT%H%M%S")
    host = frappe.local.site or "thinknxg"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//thinkNXG//ESS Portal//EN", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{_ics_escape(emp.employee_name)} – work calendar"]
    for day in shifts.plan([emp.name], fd, td)[emp.name]:
        d = day["date"]
        if day["holiday"] and not day["holiday"]["weekly_off"]:
            lines += ["BEGIN:VEVENT", f"UID:hol-{d}-{emp.name}@{host}", f"DTSTAMP:{stamp}",
                      f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}", f"DTEND;VALUE=DATE:{add_days(d, 1).strftime('%Y%m%d')}",
                      f"SUMMARY:{_ics_escape(day['holiday']['description'])}", "TRANSP:TRANSPARENT", "END:VEVENT"]
        for wn in day["windows"]:
            lines += ["BEGIN:VEVENT", f"UID:shift-{d}-{_ics_escape(wn['shift_type'])}-{emp.name}@{host}", f"DTSTAMP:{stamp}",
                      f"DTSTART:{wn['start'].strftime('%Y%m%dT%H%M%S')}", f"DTEND:{wn['end'].strftime('%Y%m%dT%H%M%S')}",
                      f"SUMMARY:{_ics_escape(wn['shift_type'])}"]
            if wn["location"]:
                lines.append(f"LOCATION:{_ics_escape(wn['location'])}")
            lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    frappe.local.response.filename = f"work-calendar-{fd}.ics"
    frappe.local.response.filecontent = "\r\n".join(lines) + "\r\n"
    frappe.local.response.type = "download"


# ------------------------------------------------------------------ planner (managers + HR)
def _planner():
    guard("enable_roster", employee=False)
    if not roster.can_plan():
        frappe.throw(_("Rosters are planned by managers and HR."), frappe.PermissionError)


@frappe.whitelist(methods=["GET"])
def list_rosters(status=None, department=None, branch=None):
    _planner()
    flt = {}
    if status:
        flt["status"] = status
    if department:
        flt["department"] = department
    if branch:
        flt["branch"] = branch
    if not identity.is_hr_manager():
        flt["planner"] = frappe.session.user
    rows = frappe.get_all("ESS Roster", filters=flt, order_by="from_date desc", limit=100,
                          fields=["name", "title", "from_date", "to_date", "status", "version", "has_unpublished_changes",
                                  "published_on", "department", "branch", "planner", "modified"])
    for r in rows:
        r["employees"] = len(roster.roster_employees(r.name))
        r["pending_requests"] = frappe.db.count("ESS Roster Change Request", {"roster": r.name,
                                                                              "status": "Pending Approval"})
    return rows


@frappe.whitelist(methods=["GET"])
def team_members(department=None, branch=None):
    _planner()
    sc = roster.scope()
    flt = {"status": "Active"}
    if sc is not None:
        flt["name"] = ["in", list(sc) or [""]]
    if department:
        flt["department"] = department
    if branch:
        flt["branch"] = branch
    return frappe.get_all("Employee", filters=flt, fields=["name", "employee_name", "designation", "department", "branch",
                                                           "image"], order_by="employee_name asc", limit=1000)


@frappe.whitelist(methods=["POST"])
def create_roster(title, from_date, to_date, employees=None, department=None, branch=None, prefill="current", notes=None):
    _planner()
    doc = roster.create(title, from_date, to_date, parse(employees, []), department, branch, prefill, notes)
    return {"name": doc.name}


@frappe.whitelist(methods=["GET"])
def get_roster(name):
    _planner()
    return roster.grid(name)


@frappe.whitelist(methods=["POST"])
def save_cells(name, cells):
    _planner()
    out = roster.save_cells(name, parse(cells, []))
    out["validation"] = roster.validate(roster.get_roster(name))
    return out


@frappe.whitelist(methods=["POST"])
def add_employees(name, employees, prefill="current"):
    _planner()
    return roster.add_employees(name, parse(employees, []), prefill)


@frappe.whitelist(methods=["POST"])
def remove_employee(name, employee):
    _planner()
    return roster.remove_employee(name, employee)


@frappe.whitelist(methods=["POST"])
def apply_pattern(name, pattern, employees, start_date=None, end_date=None, stagger=0, shift_location=None,
                  keep_weekly_offs=1):
    _planner()
    roster.apply_pattern(name, pattern, parse(employees, []), start_date, end_date, stagger, shift_location,
                         cint(keep_weekly_offs))
    return roster.grid(name)


@frappe.whitelist(methods=["POST"])
def copy_from(name, source, keep_weekly_offs=1):
    _planner()
    roster.copy_period(name, source, cint(keep_weekly_offs))
    return roster.grid(name)


@frappe.whitelist(methods=["POST"])
def mark_weekly_offs(name, employees=None, overwrite=0):
    _planner()
    out = roster.mark_weekly_offs(name, parse(employees, None), bool(cint(overwrite)))
    return {**out, "grid": roster.grid(name)}


@frappe.whitelist(methods=["POST"])
def set_requirements(name, rows):
    _planner()
    roster.set_requirements(name, parse(rows, []))
    return roster.grid(name)


@frappe.whitelist(methods=["GET"])
def validate_roster(name):
    _planner()
    return roster.validate(roster.get_roster(name))


@frappe.whitelist(methods=["POST"])
def publish(name, trim_manual=0, backfill=0):
    _planner()
    return roster.publish(name, trim_manual, backfill)


@frappe.whitelist(methods=["POST"])
def archive(name):
    _planner()
    return roster.archive(name)


@frappe.whitelist(methods=["GET"])
def patterns():
    _planner()
    out = []
    for p in frappe.get_all("ESS Shift Pattern", fields=["name", "description", "is_active"], order_by="name"):
        d = frappe.get_cached_doc("ESS Shift Pattern", p.name)
        out.append({**p, "steps": [None if s.is_rest_day else s.shift_type for s in d.steps]})
    return out


@frappe.whitelist(methods=["POST"])
def save_pattern(pattern_name, steps, description=None):
    _planner()
    steps = parse(steps, [])
    if not steps or len(steps) > 56:
        frappe.throw(_("A pattern needs 1 to 56 days."))
    name = frappe.db.get_value("ESS Shift Pattern", {"pattern_name": pattern_name})
    doc = frappe.get_doc("ESS Shift Pattern", name) if name else frappe.new_doc("ESS Shift Pattern")
    doc.pattern_name = pattern_name
    doc.description = description
    doc.is_active = 1
    doc.set("steps", [{"shift_type": s, "is_rest_day": 0 if s else 1} for s in steps])
    doc.save(ignore_permissions=True)
    return {"name": doc.name}
