"""Compensatory leave through native Compensatory Leave Request.

Employees create a draft request for eligible worked days off; the approver submits it (native allocation) or
rejects it. thinkNXG HR's own validation (holidays, attendance, overlap, leave period) runs on save and on submit.
"""
import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, today
from thinknxg_ess_portal.api._guard import guard, parse
from thinknxg_ess_portal.services import compoff_rules, hrms, identity, shifts
from thinknxg_ess_portal.services.idempotency import run_once
from thinknxg_ess_portal.services.notifications import notify


def _approver(emp):
    a = hrms.leave_approver(emp.name)
    if not a and emp.reports_to:
        a = frappe.db.get_value("Employee", emp.reports_to, "user_id")
    return a


def _types():
    return frappe.get_all("Leave Type", filters={"is_compensatory": 1}, pluck="name", order_by="name")


def _claimed(employee, fd, td):
    out = {}
    for r in frappe.get_all("Compensatory Leave Request",
                            filters={"employee": employee, "docstatus": ["<", 2], "work_from_date": ["<=", td],
                                     "work_end_date": [">=", fd]},
                            fields=["name", "work_from_date", "work_end_date", "docstatus"]
                            + (["ess_status"] if frappe.get_meta("Compensatory Leave Request").has_field("ess_status") else [])):
        if r.get("ess_status") == "Rejected" and r.docstatus == 0:
            continue
        d = getdate(r.work_from_date)
        while d <= getdate(r.work_end_date):
            out[d] = r.name
            d = add_days(d, 1)
    return out


@frappe.whitelist(methods=["GET"])
def eligible_days():
    emp = guard("enable_comp_off")
    s = identity.settings()
    td = add_days(getdate(today()), -1)
    fd = add_days(td, -max(cint(s.get("comp_off_window_days")) or 60, 1) + 1)
    plan = shifts.plan([emp.name], fd, td)[emp.name]
    att = {getdate(a.attendance_date): a for a in frappe.get_all(
        "Attendance", filters={"employee": emp.name, "docstatus": 1, "attendance_date": ["between", [fd, td]]},
        fields=["attendance_date", "status", "working_hours"])}
    claimed = _claimed(emp.name, fd, td)
    days = []
    for day in reversed(plan):
        a = att.get(day["date"])
        c = compoff_rules.classify({"date": day["date"], "holiday": day["holiday"], "roster_rest": day["rest_day"],
                                    "attendance": {"status": a.status, "working_hours": a.working_hours} if a else None,
                                    "claimed": claimed.get(day["date"])},
                                   allow_roster_rest=bool(cint(s.get("comp_off_allow_roster_rest_days"))),
                                   min_hours=flt(s.get("comp_off_min_hours")))
        if c:
            c["date"] = str(c["date"])
            days.append(c)
    types = _types()
    return {"from": str(fd), "to": str(td), "days": days, "leave_types": types,
            "approver": frappe.utils.get_fullname(_approver(emp)) if _approver(emp) else None,
            "setup_problem": None if types else _("No compensatory leave type is set up. Ask HR to mark a Leave Type as compensatory.")}


@frappe.whitelist(methods=["POST"])
def create_request(dates, reason, leave_type=None, client_request_id=None):
    emp = guard("enable_comp_off")
    picked = sorted({getdate(d) for d in parse(dates, [])})
    if not picked:
        frappe.throw(_("Choose at least one day."))
    if not (reason or "").strip():
        frappe.throw(_("Please give a reason."))
    types = _types()
    leave_type = leave_type or (types[0] if len(types) == 1 else None)
    if leave_type not in types:
        frappe.throw(_("Choose a compensatory leave type."))
    info = {d["date"]: d for d in eligible_days()["days"]}
    bad = [str(d) for d in picked if not info.get(str(d), {}).get("eligible")]
    if bad:
        frappe.throw(_("These days aren't eligible: {0}").format(", ".join(bad)))
    approver = _approver(emp)

    def do():
        names = []
        # A native request carries at most one half day and credits the rest of its range as full days,
        # so full days are grouped into ranges and every half day gets its own request.
        halves = [x for x in picked if info[str(x)]["half_day"]]
        full = [x for x in picked if x not in halves]
        batches = [(a, b, None) for a, b in compoff_rules.group_ranges(full)] + [(h, h, h) for h in halves]
        for a, b, half in sorted(batches):
            doc = frappe.get_doc({"doctype": "Compensatory Leave Request", "employee": emp.name, "leave_type": leave_type,
                                  "work_from_date": a, "work_end_date": b, "reason": reason.strip()[:1000],
                                  "half_day": 1 if half else 0, "half_day_date": half})
            meta = frappe.get_meta("Compensatory Leave Request")
            if meta.has_field("ess_approver"):
                doc.ess_approver = approver
                doc.ess_status = "Pending"
            doc.insert(ignore_permissions=True)
            names.append(doc.name)
        if approver:
            notify(approver, "Approvals", _("Compensatory leave request from {0}").format(emp.employee_name),
                   ", ".join(str(d) for d in picked[:5]), "/ess/team/approvals", "Compensatory Leave Request", names[0])
        return {"doctype": "Compensatory Leave Request", "name": names[0], "names": names}

    return run_once(client_request_id, "comp_off_request", do)


@frappe.whitelist(methods=["GET"])
def my_requests():
    emp = guard("enable_comp_off")
    meta = frappe.get_meta("Compensatory Leave Request")
    extra = [f for f in ("ess_status", "ess_review_comment") if meta.has_field(f)]
    rows = frappe.get_all("Compensatory Leave Request", filters={"employee": emp.name},
                          fields=["name", "leave_type", "work_from_date", "work_end_date", "half_day", "reason",
                                  "docstatus", "leave_allocation", "creation"] + extra,
                          order_by="creation desc", limit=50)
    for r in rows:
        r["status"] = ("Approved" if r.docstatus == 1 else "Cancelled" if r.docstatus == 2 else
                       "Rejected" if r.get("ess_status") == "Rejected" else "Pending")
        r["days"] = (getdate(r.work_end_date) - getdate(r.work_from_date)).days + 1 - (0.5 if r.half_day else 0)
    return rows


@frappe.whitelist(methods=["POST"])
def withdraw(name):
    emp = guard("enable_comp_off")
    doc = frappe.get_doc("Compensatory Leave Request", name)
    if doc.employee != emp.name or doc.docstatus != 0 or doc.get("ess_status") == "Rejected":
        frappe.throw(_("Only pending requests can be withdrawn."))
    frappe.delete_doc("Compensatory Leave Request", name, ignore_permissions=True)
    return {"name": name, "withdrawn": True}
