"""Extends thinkNXG HR's Compensatory Leave Request so published ESS roster rest days count as days off.

Only validate_holidays is extended, and only when "Roster rest days are eligible" is on. Every other rule
(attendance, overlap, leave period, allocation) is the native behaviour.
"""
import frappe
from frappe.utils import cint, getdate
from hrms.hr.utils import get_holiday_dates_for_employee


class ESSCompensatoryLeaveMixin:
    """Mixed in front of the native Compensatory Leave Request class (hooks.extend_doctype_class)."""

    def validate_holidays(self):
        if not cint(frappe.db.get_single_value("ESS Portal Settings", "comp_off_allow_roster_rest_days")):
            return super().validate_holidays()
        from thinknxg_ess_portal.services import shiftwin, shifts
        fd, td = getdate(self.work_from_date), getdate(self.work_end_date)
        off = {getdate(d) for d in get_holiday_dates_for_employee(self.employee, fd, td)}
        off |= shifts.published_rest_days([self.employee], fd, td).get(self.employee, set())
        if all(d in off for d in shiftwin.day_range(fd, td)):
            return
        return super().validate_holidays()
