"""Approval engine for the manager workspace.

Authorisation is resolved per document on the server: native approver fields, the reporting line,
HR roles and active delegations. If a thinkNXG Workflow is configured for the DocType, the portal applies
the matching workflow action instead of setting status directly, so organisational workflows stay authoritative.
"""
import frappe
from frappe import _
from frappe.utils import today, date_diff, now_datetime, cint
from thinknxg_ess_portal.services import identity
from thinknxg_ess_portal.services.audit import log_event

TYPES = {
    "Leave Application": {"key": "leave", "flag": "include_leave", "approver": "leave_approver"},
    "Expense Claim": {"key": "expense", "flag": "include_expense", "approver": "expense_approver"},
    "Attendance Request": {"key": "attendance", "flag": "include_attendance", "approver": None},
    "Shift Request": {"key": "shift", "flag": "include_attendance", "approver": "approver"},
    "ESS Profile Change Request": {"key": "profile", "flag": None, "approver": None},
    "ESS Document Request": {"key": "document", "flag": None, "approver": None},
    "ESS Roster Change Request": {"key": "roster", "flag": "include_attendance", "approver": "approver"},
    "Compensatory Leave Request": {"key": "comp_off", "flag": "include_leave", "approver": "ess_approver"},
}


def delegators(user, flag):
    if not flag:
        return []
    return frappe.get_all("ESS Approval Delegation", pluck="delegator", filters={
        "delegate": user, "is_active": 1, flag: 1, "from_date": ["<=", today()], "to_date": [">=", today()]})


def approvers(user, flag):
    return [user] + delegators(user, flag)


def _team_of(users):
    team = set()
    for u in users:
        team.update(identity.team_employees(u))
    return sorted(team)


def _item(doctype, row, title, details, employee, employee_name, submitted, via=None):
    return {
        "id": f"{TYPES[doctype]['key']}:{row.name}", "doctype": doctype, "name": row.name,
        "type": TYPES[doctype]["key"], "title": title, "employee": employee, "employee_name": employee_name,
        "submitted_on": str(submitted), "age_days": date_diff(today(), submitted) if submitted else 0,
        "details": details, "delegated_from": via,
    }


def pending(user=None, types=None):
    user = user or frappe.session.user
    me = identity.get_employee(user, required=False)
    my_emp = me.name if me else None
    types = set(types or [t["key"] for t in TYPES.values()])
    out = []

    if "leave" in types:
        appr = approvers(user, "include_leave")
        for r in frappe.get_all("Leave Application", filters={"docstatus": 0, "status": "Open",
                                                              "leave_approver": ["in", appr]},
                                fields=["name", "employee", "employee_name", "leave_type", "from_date", "to_date",
                                        "total_leave_days", "half_day", "description", "posting_date",
                                        "leave_approver"], order_by="posting_date asc", limit=200):
            if r.employee == my_emp:
                continue
            out.append(_item("Leave Application", r, _("{0} · {1} day(s)").format(r.leave_type, r.total_leave_days),
                             {"leave_type": r.leave_type, "from_date": str(r.from_date), "to_date": str(r.to_date),
                              "days": r.total_leave_days, "half_day": r.half_day, "reason": r.description},
                             r.employee, r.employee_name, r.posting_date,
                             r.leave_approver if r.leave_approver != user else None))

    if "expense" in types:
        appr = approvers(user, "include_expense")
        for r in frappe.get_all("Expense Claim", filters={"docstatus": 0, "approval_status": "Draft",
                                                          "expense_approver": ["in", appr]},
                                fields=["name", "employee", "employee_name", "total_claimed_amount",
                                        "posting_date", "expense_approver", "remark", "company"]
                                + (["currency"] if frappe.get_meta("Expense Claim").has_field("currency") else []),
                                order_by="posting_date asc", limit=200):
            if r.employee == my_emp:
                continue
            out.append(_item("Expense Claim", r, _("Expense claim {0}").format(r.name),
                             {"amount": r.total_claimed_amount, "remark": r.remark,
                              "currency": r.get("currency") or frappe.get_cached_value("Company", r.company, "default_currency")},
                             r.employee, r.employee_name, r.posting_date,
                             r.expense_approver if r.expense_approver != user else None))

    if "attendance" in types:
        team = _team_of(approvers(user, "include_attendance"))
        if team:
            flt = {"docstatus": 0, "employee": ["in", team]}
            if frappe.get_meta("Attendance Request").has_field("ess_status"):
                flt["ess_status"] = ["!=", "Rejected"]
            for r in frappe.get_all("Attendance Request", filters=flt,
                                    fields=["name", "employee", "employee_name", "from_date", "to_date", "reason",
                                            "explanation", "creation"], order_by="creation asc", limit=200):
                out.append(_item("Attendance Request", r, _("Attendance correction · {0}").format(_(r.reason)),
                                 {"from_date": str(r.from_date), "to_date": str(r.to_date), "reason": r.reason,
                                  "explanation": r.explanation}, r.employee, r.employee_name, r.creation.date()))

    if "shift" in types and frappe.db.exists("DocType", "Shift Request"):
        appr = approvers(user, "include_attendance")
        for r in frappe.get_all("Shift Request", filters={"docstatus": 0, "status": "Draft", "approver": ["in", appr]},
                                fields=["name", "employee", "employee_name", "shift_type", "from_date", "to_date",
                                        "creation"], limit=200):
            out.append(_item("Shift Request", r, _("Shift change · {0}").format(r.shift_type),
                             {"shift_type": r.shift_type, "from_date": str(r.from_date), "to_date": str(r.to_date)},
                             r.employee, r.employee_name, r.creation.date()))

    if "profile" in types and identity.is_hr(user):
        scope = identity.hr_scope_employees(user)
        flt = {"status": "Pending"}
        if scope is not None:
            flt["employee"] = ["in", scope or [""]]
        for r in frappe.get_all("ESS Profile Change Request", filters=flt,
                                fields=["name", "employee", "employee_name", "reason", "contains_bank_details",
                                        "creation"], limit=200):
            items = frappe.get_all("ESS Profile Change Item", filters={"parent": r.name},
                                   fields=["field_label", "new_value"])
            details = {"reason": r.reason, "bank": r.contains_bank_details,
                       "changes": [{"label": i.field_label, "new": "••••" if r.contains_bank_details else i.new_value}
                                   for i in items]}
            out.append(_item("ESS Profile Change Request", r, _("Profile update"), details,
                             r.employee, r.employee_name, r.creation.date()))

    if "document" in types:
        my_roles = identity.roles(user)
        tpl_roles = {t.name: t.approver_role for t in frappe.get_all(
            "ESS Document Template", fields=["name", "approver_role"], filters={"requires_approval": 1})}
        allowed = [t for t, role in tpl_roles.items() if (role or "HR Manager") in my_roles or identity.is_admin(user)]
        if allowed:
            for r in frappe.get_all("ESS Document Request", filters={"status": "Pending Approval",
                                                                     "template": ["in", allowed]},
                                    fields=["name", "employee", "employee_name", "template", "purpose", "creation"],
                                    limit=200):
                if r.employee == my_emp:
                    continue
                out.append(_item("ESS Document Request", r, r.template, {"purpose": r.purpose},
                                 r.employee, r.employee_name, r.creation.date()))

    if "roster" in types:
        appr = approvers(user, "include_attendance")
        flt = {"status": "Pending Approval"}
        if not identity.is_hr_manager(user):
            flt["approver"] = ["in", appr]
        for r in frappe.get_all("ESS Roster Change Request", filters=flt,
                                fields=["name", "employee", "employee_name", "request_type", "from_date", "to_date",
                                        "requested_shift_type", "swap_with_name", "reason", "approver", "creation"],
                                limit=200):
            if r.employee == my_emp:
                continue
            title = (_("Swap with {0}").format(r.swap_with_name) if r.request_type == "Swap with colleague" else
                     _("Change to {0}").format(r.requested_shift_type) if r.request_type == "Change shift" else
                     _("Rest day request"))
            out.append(_item("ESS Roster Change Request", r, title,
                             {"from_date": str(r.from_date), "to_date": str(r.to_date), "reason": r.reason,
                              "request_type": r.request_type, "requested_shift_type": r.requested_shift_type,
                              "swap_with_name": r.swap_with_name}, r.employee, r.employee_name, r.creation.date(),
                             r.approver if r.approver and r.approver != user else None))

    if "comp_off" in types and frappe.db.exists("DocType", "Compensatory Leave Request") and \
            frappe.get_meta("Compensatory Leave Request").has_field("ess_approver"):
        appr = approvers(user, "include_leave")
        flt = [["docstatus", "=", 0], ["ess_status", "!=", "Rejected"]]
        if not identity.is_hr_manager(user):
            flt.append(["ess_approver", "in", appr])
        for r in frappe.get_all("Compensatory Leave Request", filters=flt,
                                fields=["name", "employee", "employee_name", "leave_type", "work_from_date", "work_end_date",
                                        "half_day", "reason", "ess_approver", "creation"], limit=200):
            if r.employee == my_emp:
                continue
            days = date_diff(r.work_end_date, r.work_from_date) + 1 - (0.5 if r.half_day else 0)
            out.append(_item("Compensatory Leave Request", r, _("Compensatory leave · {0} day(s)").format(days),
                             {"from_date": str(r.work_from_date), "to_date": str(r.work_end_date), "reason": r.reason,
                              "leave_type": r.leave_type, "days": days, "half_day": r.half_day},
                             r.employee, r.employee_name, r.creation.date(),
                             r.ess_approver if r.ess_approver and r.ess_approver != user else None))

    out.sort(key=lambda x: x["submitted_on"])
    return out


def _authorise(doctype, name, user):
    if doctype not in TYPES:
        frappe.throw(_("Unsupported document type"), frappe.PermissionError)
    allowed = {(i["doctype"], i["name"]) for i in pending(user, [TYPES[doctype]["key"]])}
    if (doctype, name) not in allowed:
        frappe.throw(_("This request is not awaiting your approval."), frappe.PermissionError)
    return frappe.get_doc(doctype, name)


def _workflow_action(doc, action):
    from frappe.model.workflow import get_workflow_name, get_transitions, apply_workflow
    wf = get_workflow_name(doc.doctype)
    if not wf:
        return False
    wanted = "approve" if action == "approve" else "reject"
    for t in get_transitions(doc):
        if wanted in t.get("action", "").lower():
            apply_workflow(doc, t["action"])
            return True
    frappe.throw(_("No '{0}' transition is available to you in workflow {1}").format(wanted.title(), wf),
                 frappe.PermissionError)


def act(doctype, name, action, comment=None, user=None):
    user = user or frappe.session.user
    if action not in ("approve", "reject"):
        frappe.throw(_("Invalid action"))
    if action == "reject" and not (comment or "").strip():
        frappe.throw(_("Please give a reason for rejecting."))
    doc = _authorise(doctype, name, user)
    approved = action == "approve"

    if doctype in ("Leave Application", "Expense Claim", "Shift Request") and _workflow_action(doc, action):
        pass
    elif doctype == "Leave Application":
        doc.status = "Approved" if approved else "Rejected"
        doc.flags.ignore_permissions = True
        doc.save()
        doc.submit()
    elif doctype == "Expense Claim":
        doc.approval_status = "Approved" if approved else "Rejected"
        if approved:
            for row in doc.expenses:
                if not row.sanctioned_amount:
                    row.sanctioned_amount = row.amount
        doc.flags.ignore_permissions = True
        doc.save()
        if approved and cint(identity.settings().get("auto_submit_approved_expenses")):
            doc.submit()
    elif doctype == "Shift Request":
        doc.status = "Approved" if approved else "Rejected"
        doc.flags.ignore_permissions = True
        doc.save()
        doc.submit()
    elif doctype == "Attendance Request":
        doc.flags.ignore_permissions = True
        if approved:
            doc.submit()
        else:
            doc.db_set({"ess_status": "Rejected", "ess_review_comment": comment})
            from thinknxg_ess_portal.services.notifications import notify
            notify(frappe.db.get_value("Employee", doc.employee, "user_id"), "Attendance",
                   _("Attendance correction rejected"), comment, "/ess/attendance/corrections", doctype, name)
    elif doctype == "ESS Profile Change Request":
        if approved:
            from thinknxg_ess_portal.services.profile import apply
            apply(name)
        else:
            doc.db_set({"status": "Rejected", "reviewed_by": user, "reviewed_on": now_datetime(),
                        "review_comment": comment})
        from thinknxg_ess_portal.services.notifications import notify
        notify(frappe.db.get_value("Employee", doc.employee, "user_id"), "Approvals",
               _("Profile update {0}").format(_("approved") if approved else _("rejected")), comment or "",
               "/ess/profile", doctype, name)
    elif doctype == "ESS Document Request":
        from thinknxg_ess_portal.services import documents
        documents.review(doc, approved, comment)
    elif doctype == "ESS Roster Change Request":
        from thinknxg_ess_portal.services.roster import decide_change
        decide_change(doc, approved, comment)
    elif doctype == "Compensatory Leave Request":
        doc.flags.ignore_permissions = True
        if approved:
            if not _workflow_action(doc, action):
                doc.submit()  # native on_submit creates or extends the compensatory Leave Allocation
        else:
            doc.db_set({"ess_status": "Rejected", "ess_review_comment": comment})
        from thinknxg_ess_portal.services.notifications import notify
        notify(frappe.db.get_value("Employee", doc.employee, "user_id"), "Leave",
               _("Compensatory leave {0}").format(_("approved") if approved else _("rejected")),
               comment or f"{doc.work_from_date} → {doc.work_end_date}", "/ess/leave/comp-off", doctype, name)

    if comment and doctype not in ("ESS Document Request", "ESS Roster Change Request"):
        try:
            doc.add_comment("Comment", _("{0} via ESS: {1}").format(_("Approved") if approved else _("Rejected"),
                                                                  frappe.utils.escape_html(comment)))
        except Exception:
            pass
    log_event("Approval", doctype, name, employee=doc.get("employee"),
              details=f"{action} by {user}" + (f" | {comment[:200]}" if comment else ""))
    return {"doctype": doctype, "name": name, "result": action}
