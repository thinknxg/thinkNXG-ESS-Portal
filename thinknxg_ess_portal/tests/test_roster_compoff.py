"""Integration tests for past-date rostering, weekly offs, check-in record visibility and comp-off.

Run with:  bench --site <test-site> run-tests --app thinknxg_ess_portal --module thinknxg_ess_portal.tests.test_roster_compoff
"""
import unittest

import frappe
from frappe.utils import add_days, add_years, getdate, today

from thinknxg_ess_portal.tests.test_checkin_roster import _employee, _settings, _shift, _user

try:  # v16
    from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
    from frappe.tests.utils import FrappeTestCase as TestCase


def _holiday_list(name, start, end, weekly_off_dates, holidays=()):
    if frappe.db.exists("Holiday List", name):
        frappe.delete_doc("Holiday List", name, force=True, ignore_permissions=True)
    rows = [{"holiday_date": d, "description": "Weekly off", "weekly_off": 1} for d in weekly_off_dates]
    rows += [{"holiday_date": d, "description": desc, "weekly_off": 0} for d, desc in holidays]
    return frappe.get_doc({"doctype": "Holiday List", "holiday_list_name": name, "from_date": start, "to_date": end,
                           "holidays": rows}).insert(ignore_permissions=True).name


class TestRosterCompOff(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not frappe.db.get_value("Company", {}, "name"):
            raise unittest.SkipTest("needs a Company")
        cls.mgr = _user("ess-rc-mgr@example.com")
        cls.a = _user("ess-rc-a@example.com")
        cls.b = _user("ess-rc-b@example.com")
        cls.mgr_emp = _employee(cls.mgr)
        cls.a_emp = _employee(cls.a, cls.mgr_emp)
        cls.b_emp = _employee(cls.b, cls.mgr_emp)
        cls.day = _shift("ESS Test Day", "00:00:00", "23:59:00")
        start, end = add_years(today(), -1), add_years(today(), 1)
        cls.past_wo = getdate(add_days(today(), -3))
        cls.future_wo = getdate(add_days(today(), 4))
        cls.hol = _holiday_list("ESS Test Weekly Offs", start, end, [cls.past_wo, cls.future_wo])
        for e in (cls.a_emp, cls.b_emp):
            frappe.db.set_value("Employee", e, {"holiday_list": cls.hol, "department": None, "branch": None})
        _settings(enable_roster=1, roster_change_notice_hours=0, roster_auto_weekly_off=1, roster_backdate_days=31,
                  roster_backdate_roles="ESS Roster Backdate", show_own_checkins=1,
                  manager_checkin_visibility="Direct and indirect reports", checkin_coordinates_visible_to="HR only",
                  checkin_records_max_days=31, enable_comp_off=1, comp_off_window_days=60,
                  comp_off_allow_roster_rest_days=1, comp_off_min_hours=0)
        frappe.db.commit()

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.get_doc("User", self.mgr).remove_roles("ESS Roster Backdate")

    def _as(self, user):
        frappe.set_user(user)
        frappe.local.ess_team_cache = {}
        frappe.local.ess_employee_cache = {}

    def _published(self, start, end):
        from thinknxg_ess_portal.services import roster
        self._as("Administrator")
        doc = roster.create("Past roster", start, end, [self.a_emp, self.b_emp], prefill="empty")
        frappe.db.set_value("ESS Roster", doc.name, "status", "Published")
        return frappe.get_doc("ESS Roster", doc.name)

    # ---------------------------------------------------------------- weekly offs
    def test_weekly_offs_prefilled_and_marked(self):
        from thinknxg_ess_portal.services import roster
        self._as(self.mgr)
        start = getdate(add_days(today(), 1))
        doc = roster.create("Weekly offs", start, add_days(start, 6), [self.a_emp], prefill="empty")
        e = frappe.db.get_value("ESS Roster Entry", {"roster": doc.name, "employee": self.a_emp, "date": self.future_wo},
                                ["is_rest_day", "is_weekly_off"], as_dict=True)
        self.assertEqual((e.is_rest_day, e.is_weekly_off), (1, 1))
        roster.save_cells(doc.name, [{"employee": self.a_emp, "date": self.future_wo, "shift_type": self.day}])
        kept = roster.mark_weekly_offs(doc.name)
        self.assertEqual(kept["kept_shifts"], 1)
        roster.mark_weekly_offs(doc.name, overwrite=True)
        self.assertEqual(frappe.db.get_value("ESS Roster Entry", {"roster": doc.name, "employee": self.a_emp,
                                                                  "date": self.future_wo}, "is_weekly_off"), 1)

    # ---------------------------------------------------------------- past dates
    def test_past_days_locked_without_backdate_role(self):
        from thinknxg_ess_portal.services import roster
        doc = self._published(add_days(today(), -5), add_days(today(), 1))
        self._as(self.mgr)
        self.assertFalse(roster.can_backdate())
        r = roster.save_cells(doc.name, [{"employee": self.a_emp, "date": add_days(today(), -2), "shift_type": self.day}])
        self.assertEqual((r["saved"], r["locked"]), (0, 1))

    def test_backdate_role_fills_missing_past_assignment(self):
        from thinknxg_ess_portal.services import roster
        doc = self._published(add_days(today(), -5), add_days(today(), 1))
        frappe.set_user("Administrator")
        frappe.get_doc("User", self.mgr).add_roles("ESS Roster Backdate")
        self._as(self.mgr)
        self.assertTrue(roster.can_backdate())
        d = getdate(add_days(today(), -2))
        r = roster.save_cells(doc.name, [{"employee": self.b_emp, "date": d, "shift_type": self.day}])
        self.assertEqual((r["saved"], r["past_edited"]), (1, 1))
        report = roster.publish(doc.name, backfill=True)
        self.assertGreaterEqual(report["past"]["created"], 1, report)
        self.assertTrue(frappe.db.exists("Shift Assignment", {"employee": self.b_emp, "docstatus": 1, "status": "Active",
                                                              "start_date": ["<=", d], "end_date": [">=", d]}))

    def test_backfill_skips_days_with_attendance(self):
        from thinknxg_ess_portal.services import roster
        doc = self._published(add_days(today(), -5), add_days(today(), 1))
        d = getdate(add_days(today(), -1))
        att = frappe.get_doc({"doctype": "Attendance", "employee": self.a_emp, "attendance_date": d,
                              "status": "Present", "company": frappe.db.get_value("Employee", self.a_emp, "company")})
        att.insert(ignore_permissions=True)
        att.submit()
        roster.save_cells(doc.name, [{"employee": self.a_emp, "date": d, "shift_type": self.day}])
        report = roster.publish(doc.name, backfill=True)
        self.assertGreaterEqual(report["past"]["skipped_attendance"], 1, report)

    def test_backdate_disabled_by_zero_days(self):
        from thinknxg_ess_portal.services import roster
        _settings(roster_backdate_days=0)
        try:
            self._as("Administrator")
            self.assertFalse(roster.can_backdate())
        finally:
            _settings(roster_backdate_days=31)

    # ---------------------------------------------------------------- check-in records
    def test_checkin_visibility(self):
        from thinknxg_ess_portal.api import checkin_records
        self._as(self.a)
        emps, coords, role = checkin_records.visible_employees()
        self.assertEqual(role, "none")
        with self.assertRaises(frappe.PermissionError):
            checkin_records.team_checkins(today(), today())
        self._as(self.mgr)
        emps, coords, role = checkin_records.visible_employees()
        self.assertEqual(role, "manager")
        self.assertIn(self.a_emp, emps)
        self.assertFalse(coords)
        frappe.get_doc({"doctype": "Employee Checkin", "employee": self.a_emp, "log_type": "IN",
                        "time": f"{today()} 08:00:00", "latitude": 23.5, "longitude": 58.3}).insert(ignore_permissions=True)
        data = checkin_records.team_checkins(today(), today(), employee=self.a_emp)
        punch = data["days"][0]["punches"][0]
        self.assertNotIn("latitude", punch)
        _settings(manager_checkin_visibility="None")
        try:
            self._as(self.mgr)
            self.assertEqual(checkin_records.visible_employees()[2], "none")
        finally:
            _settings(manager_checkin_visibility="Direct and indirect reports")

    def test_range_is_capped(self):
        from thinknxg_ess_portal.api import checkin_records
        with self.assertRaises(frappe.ValidationError):
            checkin_records._range(add_days(today(), -200), today())
        fd, td = checkin_records._range(add_days(today(), -6), today())
        self.assertEqual((getdate(td) - getdate(fd)).days, 6)

    # ---------------------------------------------------------------- comp-off
    def _comp_type(self):
        if not frappe.db.exists("Leave Type", "ESS Test Comp Off"):
            frappe.get_doc({"doctype": "Leave Type", "leave_type_name": "ESS Test Comp Off", "is_compensatory": 1,
                            "max_leaves_allowed": 30}).insert(ignore_permissions=True)
        return "ESS Test Comp Off"

    def test_comp_off_request_and_reject(self):
        lt = self._comp_type()
        frappe.set_user("Administrator")
        att = frappe.get_doc({"doctype": "Attendance", "employee": self.b_emp, "attendance_date": self.past_wo,
                              "status": "Present", "company": frappe.db.get_value("Employee", self.b_emp, "company")})
        att.insert(ignore_permissions=True)
        att.submit()
        from thinknxg_ess_portal.api import comp_off
        from thinknxg_ess_portal.services import workflow
        self._as(self.b)
        days = {d["date"]: d for d in comp_off.eligible_days()["days"]}
        self.assertTrue(days[str(self.past_wo)]["eligible"], days.get(str(self.past_wo)))
        res = comp_off.create_request([str(self.past_wo)], "covered the weekend", leave_type=lt)
        name = res["name"]
        self.assertEqual(frappe.db.get_value("Compensatory Leave Request", name, "ess_status"), "Pending")
        # the same day can't be claimed twice
        self.assertFalse({d["date"]: d for d in comp_off.eligible_days()["days"]}[str(self.past_wo)]["eligible"])
        self._as(self.mgr)
        self.assertIn(name, [i["name"] for i in workflow.pending(types=["comp_off"])])
        workflow.act("Compensatory Leave Request", name, "reject", comment="not approved overtime")
        self.assertEqual(frappe.db.get_value("Compensatory Leave Request", name, "ess_status"), "Rejected")
        self._as(self.b)
        mine = {r["name"]: r for r in comp_off.my_requests()}
        self.assertEqual(mine[name]["status"], "Rejected")

    def test_comp_off_rejects_working_day(self):
        self._comp_type()
        from thinknxg_ess_portal.api import comp_off
        self._as(self.b)
        working = getdate(add_days(today(), -1 if getdate(add_days(today(), -1)) != self.past_wo else -2))
        with self.assertRaises(frappe.ValidationError):
            comp_off.create_request([str(working)], "not a holiday")
