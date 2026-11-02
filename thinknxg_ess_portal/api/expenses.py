import frappe
from frappe import _
from frappe.utils import today, flt, getdate, cint
from thinknxg_ess_portal.api._guard import guard, parse, page
from thinknxg_ess_portal.services.idempotency import run_once

MAX_ATTACH = 10


@frappe.whitelist(methods=["GET"])
def overview():
    emp = guard("enable_expenses")
    claims = frappe.get_all("Expense Claim", filters={"employee": emp.name},
                            fields=["name", "posting_date", "total_claimed_amount", "total_sanctioned_amount",
                                    "approval_status", "status", "docstatus", "remark", "expense_approver"]
                            + (["currency"] if frappe.get_meta("Expense Claim").has_field("currency") else []),
                            order_by="creation desc", limit=50)
    advances = frappe.get_all("Employee Advance", filters={"employee": emp.name},
                              fields=["name", "posting_date", "advance_amount", "paid_amount", "claimed_amount",
                                      "status", "purpose", "currency"], order_by="creation desc", limit=20)
    types = frappe.get_all("Expense Claim Type", pluck="name", order_by="name")
    currency = frappe.db.get_value("Company", emp.company, "default_currency")
    for c in claims:
        c.currency = c.get("currency") or currency  # Expense Claim has no currency field in v15
    return {"claims": claims, "advances": advances, "types": types, "currency": currency,
            "totals": {"pending": flt(sum(c.total_claimed_amount or 0 for c in claims if c.docstatus == 0
                                          and c.approval_status == "Draft"), 2),
                       "approved_unpaid": flt(sum((c.total_sanctioned_amount or 0) for c in claims
                                                  if c.approval_status == "Approved" and c.status != "Paid"), 2)}}


def _attach(files, doctype, name):
    for url in (files or [])[:MAX_ATTACH]:
        f = frappe.db.get_value("File", {"file_url": url, "owner": frappe.session.user}, "name")
        if not f:
            frappe.throw(_("Attachment not found or not yours"))
        frappe.db.set_value("File", f, {"attached_to_doctype": doctype, "attached_to_name": name, "is_private": 1})


@frappe.whitelist(methods=["POST"])
def create_claim(expenses, remark=None, attachments=None, client_request_id=None):
    emp = guard("enable_expenses")
    rows = parse(expenses, [])
    files = parse(attachments, [])
    if not rows:
        frappe.throw(_("Add at least one expense line"))
    types = set(frappe.get_all("Expense Claim Type", pluck="name"))
    clean = []
    for r in rows[:50]:
        if r.get("expense_type") not in types:
            frappe.throw(_("Invalid expense type {0}").format(r.get("expense_type")))
        amount = flt(r.get("amount"), 3)
        if amount <= 0:
            frappe.throw(_("Amounts must be positive"))
        if getdate(r.get("expense_date")) > getdate(today()):
            frappe.throw(_("Expense date cannot be in the future"))
        clean.append({"expense_date": r.get("expense_date"), "expense_type": r["expense_type"],
                      "description": (r.get("description") or "")[:500], "amount": amount})

    def do():
        approver = frappe.db.get_value("Employee", emp.name, "expense_approver")
        if not approver and emp.department:
            approver = frappe.db.get_value("Department Approver", {"parent": emp.department,
                                                                   "parentfield": "expense_approvers"}, "approver")
        payable = frappe.db.get_value("Company", emp.company, "default_expense_claim_payable_account")
        doc = frappe.get_doc({"doctype": "Expense Claim", "employee": emp.name, "company": emp.company,
                              "expense_approver": approver, "approval_status": "Draft", "posting_date": today(),
                              "payable_account": payable, "remark": (remark or "")[:1000], "expenses": clean})
        doc.insert(ignore_permissions=True)
        _attach(files, doc.doctype, doc.name)
        return {"doctype": doc.doctype, "name": doc.name, "total": doc.total_claimed_amount}

    return run_once(client_request_id, "expense_claim", do)


@frappe.whitelist(methods=["GET"])
def claim_detail(name):
    emp = guard("enable_expenses")
    doc = frappe.get_doc("Expense Claim", name)
    if doc.employee != emp.name:
        frappe.throw(_("Not found"), frappe.DoesNotExistError)
    files = frappe.get_all("File", filters={"attached_to_doctype": "Expense Claim", "attached_to_name": name},
                           fields=["file_name", "file_url"])
    return {"name": doc.name, "posting_date": doc.posting_date, "approval_status": doc.approval_status,
            "status": doc.status, "docstatus": doc.docstatus, "currency": doc.get("currency") or frappe.get_cached_value("Company", doc.company, "default_currency"), "remark": doc.remark,
            "total_claimed_amount": doc.total_claimed_amount, "total_sanctioned_amount": doc.total_sanctioned_amount,
            "expense_approver": frappe.utils.get_fullname(doc.expense_approver) if doc.expense_approver else None,
            "expenses": [{"expense_date": r.expense_date, "expense_type": r.expense_type, "description": r.description,
                          "amount": r.amount, "sanctioned_amount": r.sanctioned_amount} for r in doc.expenses],
            "attachments": files,
            "timeline": frappe.get_all("Comment", filters={"reference_doctype": "Expense Claim",
                                                           "reference_name": name, "comment_type": "Comment"},
                                       fields=["content", "comment_by", "creation"], order_by="creation asc")}


@frappe.whitelist(methods=["POST"])
def request_advance(purpose, advance_amount, client_request_id=None):
    emp = guard("enable_expenses")
    amount = flt(advance_amount, 3)
    if amount <= 0:
        frappe.throw(_("Amount must be positive"))

    def do():
        account = frappe.db.get_value("Company", emp.company, "default_employee_advance_account")
        doc = frappe.get_doc({"doctype": "Employee Advance", "employee": emp.name, "company": emp.company,
                              "posting_date": today(), "purpose": purpose[:500], "advance_amount": amount,
                              "advance_account": account,
                              "exchange_rate": 1})
        doc.insert(ignore_permissions=True)
        return {"doctype": doc.doctype, "name": doc.name}

    return run_once(client_request_id, "employee_advance", do)
