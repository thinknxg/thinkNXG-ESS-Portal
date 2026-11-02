import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

ROLES = {
    "ESS Portal Admin": "Configures the ESS portal, AI sources and templates",
    "ESS HR Agent": "Works HR helpdesk tickets",
    "ESS Payroll Officer": "Handles payroll-related tickets and confidential categories",
    "ESS Department Head": "Approves and sees aggregates for departments they head",
    "ESS Roster Backdate": "May change and publish past roster days within the configured window",
}

TICKET_CATEGORIES = [
    ("Leave & Attendance", "🗓️", 4, 24, 0), ("Payroll & Salary", "💰", 4, 48, 1),
    ("Benefits & Insurance", "🩺", 8, 72, 0), ("Documents & Letters", "📄", 4, 24, 0),
    ("Visa & Residency", "🛂", 8, 72, 0), ("IT Access", "💻", 2, 8, 0), ("Other", "💬", 8, 72, 0),
]
RECOGNITION = [
    ("Customer First", "🤝", 10), ("Teamwork", "🙌", 10), ("Innovation", "💡", 15),
    ("Ownership", "🎯", 10), ("Going the Extra Mile", "🚀", 15),
]
BADGES = [
    ("First Year", "🎂", "Work Anniversary", 1), ("Five Years", "🏆", "Work Anniversary", 5),
    ("Team Player", "🙌", "Recognitions Received", 5), ("Appreciator", "💐", "Recognitions Given", 10),
    ("Lifelong Learner", "📚", "Training Completed", 3), ("Policy Champion", "🛡️", "Policies Acknowledged", 3),
    ("Onboarded", "✅", "Onboarding Completed", 1),
]

EMPLOYMENT_LETTER = """<div style="font-family: Inter, Arial, sans-serif; font-size: 13px; line-height: 1.6;">
<p style="text-align:right">{{ frappe.utils.formatdate(today) }}</p>
{% if addressed_to %}<p>To: {{ addressed_to }}</p>{% else %}<p>To whom it may concern,</p>{% endif %}
<h3 style="text-align:center">EMPLOYMENT VERIFICATION</h3>
<p>This is to certify that <b>{{ employee.salutation or "" }} {{ employee.employee_name }}</b>
(Employee ID {{ employee.name }}) has been employed with <b>{{ company.company_name }}</b>
since {{ frappe.utils.formatdate(employee.date_of_joining) }} and currently holds the position of
<b>{{ employee.designation or "-" }}</b> in the {{ employee.department or "-" }} department.</p>
{% if salary %}<p>Monthly gross salary: <b>{{ salary.currency }} {{ frappe.utils.fmt_money(salary.gross_pay) }}</b>.</p>{% endif %}
{% if purpose %}<p>This letter is issued at the employee's request for the purpose of: {{ purpose }}.</p>{% endif %}
<p>This letter carries no liability on the part of the company.</p>
<br><p>{{ signatory.name or "" }}<br>{{ signatory.designation or "" }}</p>
<p style="font-size:10px;color:#666">Verification code: {{ verification_code }}{% if verify_url %} - verify at {{ verify_url }}{% endif %}</p>
</div>"""


def after_install():
    after_migrate()


def after_migrate():
    _roles()
    _custom_fields()
    try:
        _weekly_off_type()
    except Exception:
        # never block install or migrate; the type can be created later from ESS Portal Settings
        frappe.log_error(title="ESS: could not create the Weekly Off shift type")
    _settings()
    _seed()
    frappe.db.commit()


def _roles():
    for role, desc in ROLES.items():
        if not frappe.db.exists("Role", role):
            frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1,
                            "description": desc}).insert(ignore_permissions=True)


def _custom_fields():
    create_custom_fields({
        "Department": [{
            "fieldname": "ess_department_head", "label": "ESS Department Head", "fieldtype": "Link",
            "options": "User", "insert_after": "department_name",
            "description": "Gets manager-level visibility of this department (and sub-departments) in the ESS portal",
        }],
        # Roster publishing tags the Shift Assignments it owns, so republishing never touches manual ones.
        "Shift Assignment": [
            {"fieldname": "ess_roster", "label": "ESS Roster", "fieldtype": "Link", "options": "ESS Roster",
             "insert_after": "shift_type", "read_only": 1, "in_standard_filter": 1, "search_index": 1,
             "description": "Set when this assignment was created by publishing an ESS roster."},
            {"fieldname": "ess_weekly_off", "label": "Weekly Off / Rest Day", "fieldtype": "Check",
             "insert_after": "ess_roster", "in_standard_filter": 1,
             "description": "Every date from Start Date to End Date is added to the employee's holiday list as "
                            "\"Weekly Off\". Uses the Weekly Off shift type from ESS Portal Settings."},
            {"fieldname": "ess_holiday_lists", "label": "Holiday List Entries", "fieldtype": "Small Text",
             "insert_after": "ess_weekly_off", "read_only": 1, "no_copy": 1, "depends_on": "ess_weekly_off"},
        ],
        "Shift Type": [
            {"fieldname": "ess_code", "label": "ESS Short Code", "fieldtype": "Data", "length": 3,
             "insert_after": "end_time", "description": "1-3 characters shown on roster grids, e.g. G, E, N."},
            {"fieldname": "ess_color", "label": "ESS Roster Colour", "fieldtype": "Color", "insert_after": "ess_code"},
            {"fieldname": "ess_weekly_off", "label": "Weekly Off / Rest Day", "fieldtype": "Check",
             "insert_after": "ess_color",
             "description": "Assignments of this shift type are days off: their dates are added to the employee's "
                            "holiday list as \"Weekly Off\"."},
        ],
        # Rows written by weekly-off Shift Assignments carry the assignment's name, so only they are ever removed.
        # Data rather than Link: rows must stay saveable after their assignment is cancelled or deleted.
        "Holiday": [
            {"fieldname": "ess_shift_assignment", "label": "ESS Shift Assignment", "fieldtype": "Data",
             "insert_after": "weekly_off", "read_only": 1, "no_copy": 1, "search_index": 1},
            {"fieldname": "ess_from_base", "label": "Copied from shared list", "fieldtype": "Check",
             "insert_after": "ess_shift_assignment", "read_only": 1, "hidden": 1},
        ],
        "Holiday List": [
            {"fieldname": "ess_employee", "label": "ESS Personal List For", "fieldtype": "Link", "options": "Employee",
             "insert_after": "to_date", "read_only": 1, "no_copy": 1, "search_index": 1},
            {"fieldname": "ess_base_holiday_list", "label": "ESS Copied From", "fieldtype": "Link",
             "options": "Holiday List", "insert_after": "ess_employee", "read_only": 1, "no_copy": 1,
             "description": "Holidays from this list are kept in step automatically."},
        ],
        # Audit context for portal punches. Device and Desk check-ins leave these empty.
        "Employee Checkin": [
            {"fieldname": "ess_section", "label": "ESS Portal", "fieldtype": "Section Break", "insert_after": "device_id",
             "collapsible": 1},
            {"fieldname": "ess_source", "label": "ESS Source", "fieldtype": "Data", "insert_after": "ess_section", "read_only": 1},
            {"fieldname": "ess_accuracy", "label": "GPS Accuracy (m)", "fieldtype": "Float", "insert_after": "ess_source",
             "read_only": 1},
            {"fieldname": "ess_location", "label": "Matched Location", "fieldtype": "Data", "insert_after": "ess_accuracy",
             "read_only": 1},
            {"fieldname": "ess_distance", "label": "Distance (m)", "fieldtype": "Float", "insert_after": "ess_location",
             "read_only": 1},
            {"fieldname": "ess_log", "label": "ESS Check-in Log", "fieldtype": "Link", "options": "ESS Checkin Log",
             "insert_after": "ess_distance", "read_only": 1},
        ],
        # Like Attendance Request, a draft Compensatory Leave Request has no rejected state or approver.
        "Compensatory Leave Request": [
            {"fieldname": "ess_status", "label": "ESS Review Status", "fieldtype": "Select", "options": "Pending\nRejected",
             "default": "Pending", "insert_after": "reason", "read_only": 1, "in_standard_filter": 1},
            {"fieldname": "ess_approver", "label": "ESS Approver", "fieldtype": "Link", "options": "User",
             "insert_after": "ess_status", "read_only": 1},
            {"fieldname": "ess_review_comment", "label": "ESS Review Comment", "fieldtype": "Small Text",
             "insert_after": "ess_approver", "read_only": 1},
        ],
        # Attendance Request has no native rejection state; the portal records it here.
        "Attendance Request": [
            {"fieldname": "ess_status", "label": "ESS Review Status", "fieldtype": "Select",
             "options": "Pending\nRejected", "default": "Pending", "insert_after": "explanation",
             "read_only": 1, "in_standard_filter": 1},
            {"fieldname": "ess_review_comment", "label": "ESS Review Comment", "fieldtype": "Small Text",
             "insert_after": "ess_status", "read_only": 1},
        ],
        **_hla_fields(),
    }, ignore_validate=True, update=True)


def _weekly_off_type():
    from thinknxg_ess_portal.services import weekly_off
    try:
        name = frappe.db.get_single_value("ESS Portal Settings", "weekly_off_shift_type") or "Weekly Off"
    except Exception:
        name = "Weekly Off"
    weekly_off.ensure_shift_type(name)


def _hla_fields():
    if not frappe.db.exists("DocType", "Holiday List Assignment"):
        return {}
    return {"Holiday List Assignment": [
        {"fieldname": "ess_generated", "label": "Created by ESS (weekly offs)", "fieldtype": "Check",
         "insert_after": "from_date", "read_only": 1, "no_copy": 1},
        {"fieldname": "ess_source", "label": "ESS Replaces", "fieldtype": "Data", "insert_after": "ess_generated",
         "read_only": 1, "no_copy": 1, "depends_on": "ess_generated"},
        {"fieldname": "ess_base_assignment", "label": "ESS Based On", "fieldtype": "Data", "insert_after": "ess_source",
         "read_only": 1, "no_copy": 1, "depends_on": "ess_generated"},
    ]}


def _settings_defaults():
    """Fill defaults for settings fields added after install (Singles don't backfill defaults)."""
    meta = frappe.get_meta("ESS Portal Settings")
    present = set(frappe.db.sql_list("select field from `tabSingles` where doctype='ESS Portal Settings'"))
    for df in meta.fields:
        if df.default not in (None, "") and df.fieldname not in present and df.fieldtype not in ("Section Break", "Column Break"):
            frappe.db.set_single_value("ESS Portal Settings", df.fieldname, df.default)
    frappe.cache.delete_value("ess_portal_settings")


def _settings():
    _settings_defaults()
    s = frappe.get_single("ESS Portal Settings")
    if not s.portal_title:
        s.portal_title = "thinkNXG ESS Portal"
        s.flags.ignore_mandatory = True
        s.save(ignore_permissions=True)


def _seed():
    for name, icon, fr, res, conf in TICKET_CATEGORIES:
        if not frappe.db.exists("ESS HR Ticket Category", name):
            frappe.get_doc({"doctype": "ESS HR Ticket Category", "category_name": name, "icon": icon,
                            "first_response_hours": fr, "resolution_hours": res,
                            "is_confidential": conf, "visible_to_employees": 1}).insert(ignore_permissions=True)
    for name, icon, pts in RECOGNITION:
        if not frappe.db.exists("ESS Recognition Category", name):
            frappe.get_doc({"doctype": "ESS Recognition Category", "category_name": name, "icon": icon,
                            "default_points": pts, "is_active": 1}).insert(ignore_permissions=True)
    for name, icon, rule, threshold in BADGES:
        if not frappe.db.exists("ESS Badge", name):
            frappe.get_doc({"doctype": "ESS Badge", "badge_name": name, "icon": icon, "rule_type": rule,
                            "threshold": threshold, "is_active": 1}).insert(ignore_permissions=True)
    if not frappe.db.exists("ESS Document Template", "Employment Verification Letter"):
        frappe.get_doc({"doctype": "ESS Document Template", "template_name": "Employment Verification Letter",
                        "template_key": "employment_verification", "document_type": "Employment Verification",
                        "is_active": 1, "visible_to_employees": 1, "requires_purpose": 1,
                        "max_per_month": 3, "template_html": EMPLOYMENT_LETTER}).insert(ignore_permissions=True)
    if not frappe.db.exists("ESS Document Template", "Salary Certificate"):
        frappe.get_doc({"doctype": "ESS Document Template", "template_name": "Salary Certificate",
                        "template_key": "salary_certificate", "document_type": "Salary Certificate",
                        "is_active": 1, "visible_to_employees": 1, "requires_purpose": 1, "requires_approval": 1,
                        "approver_role": "HR Manager", "include_salary": 1, "addressee_required": 1,
                        "max_per_month": 2, "min_service_months": 3,
                        "template_html": EMPLOYMENT_LETTER.replace("EMPLOYMENT VERIFICATION", "SALARY CERTIFICATE")
                        }).insert(ignore_permissions=True)
