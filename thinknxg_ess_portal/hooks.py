app_name = "thinknxg_ess_portal"
app_title = "thinkNXG ESS Portal"
app_publisher = "Kreatao"
app_description = "Enterprise Employee Self-Service portal for thinkNXG HR v15"
app_email = "hello@kreatao.com"
app_license = "MIT"
required_apps = ["frappe", "erpnext", "hrms"]

add_to_apps_screen = [
    {
        "name": "thinknxg_ess_portal",
        "logo": "/assets/thinknxg_ess_portal/ess/icons/icon-192.png",
        "title": "ESS Portal",
        "route": "/ess",
        "has_permission": "thinknxg_ess_portal.services.identity.has_app_permission",
    }
]

# SPA: /ess and every nested client route render www/ess.html
website_route_rules = [
    {"from_route": "/ess/<path:app_path>", "to_route": "ess"},
]

after_install = "thinknxg_ess_portal.install.after_install"

# Lets published ESS roster rest days count as days off for compensatory leave (setting-controlled).
# thinkNXG v15 has no extend_doctype_class, so the native class is subclassed. If another app also overrides
# Compensatory Leave Request, only the last one installed applies (bench warns on install).
doctype_js = {"Shift Assignment": "public/js/shift_assignment.js"}

override_doctype_class = {
    "Compensatory Leave Request": "thinknxg_ess_portal.overrides.compensatory_leave_request.ESSCompensatoryLeaveRequest",
}
after_migrate = "thinknxg_ess_portal.install.after_migrate"

# ---------------------------------------------------------------- record-level security
_P = "thinknxg_ess_portal.permissions"
_SCOPED = {
    "ESS HR Ticket": "ticket",
    "ESS HR Ticket Comment": "ticket_comment",
    "ESS Document Request": "document_request",
    "ESS Employee Document": "employee_document",
    "ESS Recognition": "recognition",
    "ESS AI Conversation": "own_user",
    "ESS AI Message Audit": "own_user",
    "ESS Profile Change Request": "profile_change",
    "ESS Policy Acknowledgement": "policy_ack",
    "ESS Notification Preference": "own_user",
    "ESS Push Subscription": "own_user",
    "ESS Approval Delegation": "delegation",
    "ESS Badge Award": "badge_award",
    "ESS Checkin Log": "checkin_log",
    "ESS Roster Change Request": "roster_change",
}
permission_query_conditions = {dt: f"{_P}.{fn}_query" for dt, fn in _SCOPED.items()}
has_permission = {dt: f"{_P}.{fn}_has_permission" for dt, fn in _SCOPED.items()}

# ---------------------------------------------------------------- native thinkNXG HR events -> portal notifications
doc_events = {
    "Leave Application": {
        "on_update": "thinknxg_ess_portal.services.events.on_leave_update",
        "on_submit": "thinknxg_ess_portal.services.events.on_leave_update",
    },
    "Expense Claim": {"on_update": "thinknxg_ess_portal.services.events.on_expense_update"},
    "Attendance Request": {"on_update": "thinknxg_ess_portal.services.events.on_attendance_request_update",
                           "on_submit": "thinknxg_ess_portal.services.events.on_attendance_request_update"},
    "Salary Slip": {"on_submit": "thinknxg_ess_portal.services.events.on_salary_slip_submit"},
    "ESS Announcement": {"on_update": "thinknxg_ess_portal.services.events.on_announcement_update"},
    # cache invalidation only - the portal never changes how these native doctypes behave
    "Shift Type": {"on_update": "thinknxg_ess_portal.services.shifts.clear_cache"},
    # Weekly Off / Rest Day Shift Assignments are written to the employee's holiday list (services/weekly_off.py).
    "Shift Assignment": {
        "before_validate": "thinknxg_ess_portal.services.weekly_off.before_validate",
        "on_submit": "thinknxg_ess_portal.services.weekly_off.on_change",
        "on_update_after_submit": "thinknxg_ess_portal.services.weekly_off.on_change",
        "on_cancel": "thinknxg_ess_portal.services.weekly_off.on_change",
        "on_trash": "thinknxg_ess_portal.services.weekly_off.on_trash",
    },
    "Holiday List": {"on_update": "thinknxg_ess_portal.services.weekly_off.on_holiday_list_update"},
    "Holiday List Assignment": {"on_submit": "thinknxg_ess_portal.services.weekly_off.on_hla_submit",
                                "on_cancel": "thinknxg_ess_portal.services.weekly_off.on_hla_cancel"},
    "ESS Checkin Location": {"on_trash": "thinknxg_ess_portal.services.checkin_policy.clear_location_cache"},
}

scheduler_events = {
    "cron": {
        "*/15 * * * *": ["thinknxg_ess_portal.tasks.escalate_tickets"],
    },
    "hourly": ["thinknxg_ess_portal.tasks.sync_delegation_shares"],
    "daily": [
        "thinknxg_ess_portal.tasks.auto_close_resolved_tickets",
        "thinknxg_ess_portal.tasks.document_expiry_reminders",
        "thinknxg_ess_portal.tasks.policy_ack_reminders",
        "thinknxg_ess_portal.tasks.award_rule_badges",
        "thinknxg_ess_portal.tasks.purge_ai_history",
        "thinknxg_ess_portal.tasks.build_analytics_snapshots",
    ],
}

# The SPA is a website page; keep its HTML out of the website cache.
website_context = {"favicon": "/assets/thinknxg_ess_portal/ess/icons/icon-192.png"}
