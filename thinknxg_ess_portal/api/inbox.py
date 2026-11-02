import base64
import frappe
from frappe import _
from frappe.utils import today, add_days, getdate
from thinknxg_ess_portal.api._guard import guard
from thinknxg_ess_portal.services import identity


def _i(id_, type_, title, status, due, route, ref=None, meta=None, priority="normal"):
    return {"id": id_, "type": type_, "title": title, "status": status, "due_date": str(due) if due else None,
            "route": route, "reference": ref, "meta": meta or {}, "priority": priority}


def _collect(emp):
    user = frappe.session.user
    items = []
    for r in frappe.get_all("Leave Application", filters={"employee": emp.name, "docstatus": 0, "status": "Open"},
                            fields=["name", "leave_type", "from_date"]):
        items.append(_i(f"leave:{r.name}", "leave_pending", _("{0} awaiting approval").format(r.leave_type),
                        "pending", r.from_date, "/ess/leave", r.name))
    for r in frappe.get_all("Expense Claim", filters={"employee": emp.name, "docstatus": 0, "approval_status": "Rejected"},
                            fields=["name", "posting_date"]):
        items.append(_i(f"expense:{r.name}", "expense_rejected", _("Expense claim needs attention"), "rejected",
                        r.posting_date, f"/ess/finances/expenses?claim={r.name}", r.name, priority="high"))
    for r in frappe.get_all("ESS HR Ticket", filters={"employee": emp.name, "status": "Waiting for Employee"},
                            fields=["name", "subject", "resolution_due"]):
        items.append(_i(f"ticket:{r.name}", "ticket_reply", _("HR is waiting for your reply: {0}").format(r.subject),
                        "action", r.resolution_due, f"/ess/support/{r.name}", r.name, priority="high"))
    for r in frappe.get_all("ESS HR Ticket", filters={"employee": emp.name, "status": "Resolved", "rating": ["in", [0, None]]},
                            fields=["name", "subject"], limit=5):
        items.append(_i(f"rate:{r.name}", "ticket_rate", _("Rate the resolution: {0}").format(r.subject), "action",
                        None, f"/ess/support/{r.name}", r.name, priority="low"))
    for r in frappe.get_all("ESS Document Request", filters={"employee": emp.name, "status": "Generated",
                                                             "generated_on": [">=", add_days(today(), -7)]},
                            fields=["name", "template"]):
        items.append(_i(f"doc:{r.name}", "document_ready", _("{0} is ready to download").format(r.template), "ready",
                        None, "/ess/documents", r.name))
    for r in frappe.get_all("ESS Roster Change Request", filters={"swap_with": emp.name, "status": "Pending Colleague"},
                            fields=["name", "employee_name", "from_date", "to_date"]):
        items.append(_i(f"swap:{r.name}", "swap_request", _("{0} asked to swap shifts with you").format(r.employee_name),
                        "action", r.from_date, f"/ess/roster?swap={r.name}", r.name, priority="high"))
    for r in frappe.get_all("ESS Roster Change Request", filters={"employee": emp.name,
                                                                  "status": ["in", ["Pending Colleague", "Pending Approval"]]},
                            fields=["name", "request_type", "from_date", "status"]):
        items.append(_i(f"rcr:{r.name}", "roster_change_pending", _("{0}: {1}").format(_(r.request_type), _(r.status)),
                        "pending", r.from_date, "/ess/roster", r.name, priority="low"))
    if frappe.get_meta("Compensatory Leave Request").has_field("ess_status"):
        for r in frappe.get_all("Compensatory Leave Request", filters={"employee": emp.name, "docstatus": 0,
                                                                       "ess_status": ["!=", "Rejected"]},
                                fields=["name", "work_from_date"]):
            items.append(_i(f"clr:{r.name}", "comp_off_pending", _("Compensatory leave awaiting approval"), "pending",
                            r.work_from_date, "/ess/leave/comp-off", r.name, priority="low"))
    from thinknxg_ess_portal.api.policies import _pending_for
    for p in _pending_for(emp):
        items.append(_i(f"policy:{p['name']}", "policy_ack", _("Acknowledge policy: {0}").format(p["policy_title"]),
                        "overdue" if p.get("overdue") else "action", p.get("due_date"),
                        f"/ess/documents?tab=policies&policy={p['name']}", p["name"],
                        priority="high" if p.get("overdue") else "normal"))
    for r in frappe.get_all("ESS Employee Document", filters={"employee": emp.name,
                                                              "expiry_date": ["between", [today(), add_days(today(), 30)]]},
                            fields=["name", "document_type", "expiry_date"]):
        items.append(_i(f"edoc:{r.name}", "document_expiry", _("{0} expires soon").format(_(r.document_type)), "action",
                        r.expiry_date, "/ess/profile?tab=documents", r.name, priority="high"))
    for r in frappe.get_all("ToDo", filters={"allocated_to": user, "status": "Open"},
                            fields=["name", "description", "date", "reference_type", "reference_name", "priority"],
                            limit=30):
        title = frappe.utils.strip_html(r.description or "")[:120]
        items.append(_i(f"todo:{r.name}", "task", title or _("Task"), "open", r.date, "/ess/inbox", r.name,
                        {"reference_type": r.reference_type, "reference_name": r.reference_name},
                        priority="high" if r.priority == "High" else "normal"))
    if frappe.db.exists("DocType", "Training Event Employee"):
        for r in frappe.db.sql("""select te.name, te.event_name, te.start_time from `tabTraining Event` te
                join `tabTraining Event Employee` tee on tee.parent=te.name
                where tee.employee=%s and te.start_time>=%s and te.docstatus<2 order by te.start_time limit 5""",
                               (emp.name, today()), as_dict=True):
            items.append(_i(f"training:{r.name}", "training", _("Training: {0}").format(r.event_name), "upcoming",
                            getdate(r.start_time), "/ess/goals?tab=learning", r.name))
    if identity.is_manager() or identity.is_hr():
        from thinknxg_ess_portal.services.workflow import pending
        for p in pending():
            items.append(_i(f"approve:{p['id']}", f"{p['type']}_approval",
                            _("{0}: {1}").format(p["employee_name"], p["title"]), "pending",
                            add_days(p["submitted_on"], 2), f"/ess/team/approvals?open={p['doctype']}::{p['name']}",
                            p["name"], {"doctype": p["doctype"]}, priority="high" if p["age_days"] > 3 else "normal"))
    order = {"high": 0, "normal": 1, "low": 2}
    items.sort(key=lambda x: (order[x["priority"]], x["due_date"] or "9999-12-31", x["id"]))
    return items


@frappe.whitelist(methods=["GET"])
def get_items(cursor=None, limit=20, type=None):
    emp = guard()
    items = _collect(emp)
    if type:
        items = [i for i in items if i["type"].startswith(type)]
    offset = int(base64.urlsafe_b64decode(cursor).decode()) if cursor else 0
    limit = max(1, min(int(limit or 20), 100))
    chunk = items[offset: offset + limit]
    nxt = offset + limit
    return {"items": chunk, "total": len(items),
            "next_cursor": base64.urlsafe_b64encode(str(nxt).encode()).decode() if nxt < len(items) else None}
