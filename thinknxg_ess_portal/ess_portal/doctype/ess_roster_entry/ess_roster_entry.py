# Copyright (c) 2026, Kreatao and contributors
# License: MIT

import frappe
from frappe import _
from frappe.model.document import Document

class ESSRosterEntry(Document):
    def validate(self):
        if self.is_rest_day:
            self.shift_type = None
            self.shift_location = None
        else:
            self.is_weekly_off = 0
        self.employee_name = self.employee_name or frappe.db.get_value("Employee", self.employee, "employee_name")


def on_doctype_update():
    frappe.db.add_unique("ESS Roster Entry", ["roster", "employee", "date"], constraint_name="unique_roster_emp_date")
    frappe.db.add_index("ESS Roster Entry", ["employee", "date"])
