"""Integration tests: Weekly Off / Rest Day Shift Assignments -> holiday lists.

Run with:  bench --site <test-site> run-tests --app thinknxg_ess_portal --module thinknxg_ess_portal.tests.test_weekly_off
"""
import unittest

import frappe
from frappe.utils import getdate

from thinknxg_ess_portal.tests.test_checkin_roster import _employee, _settings, _user

try:  # v16
    from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
    from frappe.tests.utils import FrappeTestCase as TestCase

YEAR_START, YEAR_END = getdate("2031-01-01"), getdate("2031-12-31")
NATIONAL_DAY = getdate("2031-11-18")
SHARED = "ESS WO Test Shared 2031"


def _has_hla():
    return bool(frappe.db.exists("DocType", "Holiday List Assignment"))


def _list_for(emp, on):
    from thinknxg_ess_portal.services import weekly_off
    r = weekly_off._ranges(emp, on, on)
    return r[0].holiday_list if r else None


def _rows(hl):
    return {getdate(h.holiday_date): h for h in frappe.get_doc("Holiday List", hl).holidays}


class TestWeeklyOffHolidays(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = frappe.db.get_value("Company", {}, "name")
        if not cls.company:
            raise unittest.SkipTest("needs a Company")
        cls.a = _employee(_user("ess-wo-a@example.com"))
        cls.b = _employee(_user("ess-wo-b@example.com"))
        frappe.db.set_value("Employee", cls.a, "company", cls.company)
        frappe.db.set_value("Employee", cls.b, "company", cls.company)
        if not frappe.db.exists("Holiday List", SHARED):
            frappe.get_doc({"doctype": "Holiday List", "holiday_list_name": SHARED, "from_date": YEAR_START,
                            "to_date": YEAR_END, "holidays": [
                                {"holiday_date": getdate("2031-11-07"), "description": "Friday", "weekly_off": 1},
                                {"holiday_date": NATIONAL_DAY, "description": "National Day", "weekly_off": 0}]}
                           ).insert(ignore_permissions=True)
        if _has_hla():
            if not frappe.db.exists("Holiday List Assignment", {"assigned_to": cls.company, "from_date": YEAR_START,
                                                                "docstatus": 1}):
                hla = frappe.get_doc({"doctype": "Holiday List Assignment", "applicable_for": "Company",
                                      "assigned_to": cls.company, "holiday_list": SHARED, "from_date": YEAR_START})
                hla.insert(ignore_permissions=True)
                hla.submit()
        else:
            for e in (cls.a, cls.b):
                frappe.db.set_value("Employee", e, "holiday_list", SHARED)
        from thinknxg_ess_portal.services import weekly_off
        cls.wo_type = weekly_off.ensure_shift_type("Weekly Off")
        _settings(enable_weekly_off_holidays=1, roster_rest_as_weekly_off=1, weekly_off_shift_type="Weekly Off",
                  weekly_off_missing_list="Stop with an error")
        frappe.db.commit()

    def _sa(self, emp, start, end, submit=True, **kw):
        sa = frappe.get_doc({"doctype": "Shift Assignment", "employee": emp, "company": self.company,
                             "ess_weekly_off": 1, "start_date": start, "end_date": end, "status": "Active", **kw})
        sa.insert(ignore_permissions=True)
        if submit:
            sa.submit()
        return sa

    def test_tick_switches_shift_type_and_needs_end_date(self):
        sa = self._sa(self.a, getdate("2031-03-02"), getdate("2031-03-02"), submit=False)
        self.assertEqual(sa.shift_type, self.wo_type)
        sa2 = frappe.get_doc({"doctype": "Shift Assignment", "employee": self.a, "company": self.company,
                              "ess_weekly_off": 1, "start_date": getdate("2031-03-09"), "status": "Active"})
        with self.assertRaises(frappe.ValidationError):
            sa2.insert(ignore_permissions=True)

    def test_submit_writes_personal_list_and_leaves_shared_list_alone(self):
        before = set(_rows(SHARED))
        sa = self._sa(self.a, getdate("2031-11-16"), NATIONAL_DAY)
        hl = _list_for(self.a, getdate("2031-11-16"))
        self.assertNotEqual(hl, SHARED)
        self.assertEqual(frappe.db.get_value("Holiday List", hl, "ess_base_holiday_list"), SHARED)
        rows = _rows(hl)
        for d in (getdate("2031-11-16"), getdate("2031-11-17")):
            self.assertEqual(rows[d].description, "Weekly Off")
            self.assertEqual(rows[d].weekly_off, 1)
            self.assertEqual(rows[d].ess_shift_assignment, sa.name)
        self.assertFalse(rows[NATIONAL_DAY].get("ess_shift_assignment"))  # already a holiday: untouched
        self.assertEqual(set(_rows(SHARED)), before)
        self.assertEqual(_list_for(self.b, getdate("2031-11-16")), SHARED)
        self.assertIn(hl, frappe.db.get_value("Shift Assignment", sa.name, "ess_holiday_lists"))

    def test_change_cancel_and_delete_only_touch_own_rows(self):
        sa = self._sa(self.a, getdate("2031-05-03"), getdate("2031-05-05"))
        hl = _list_for(self.a, getdate("2031-05-03"))
        manual = frappe.get_doc("Holiday List", hl)
        manual.append("holidays", {"holiday_date": getdate("2031-05-20"), "description": "Manual", "weekly_off": 0})
        manual.save(ignore_permissions=True)

        sa.reload()
        sa.end_date = getdate("2031-05-04")
        sa.save(ignore_permissions=True)
        tagged = {d for d, h in _rows(hl).items() if h.get("ess_shift_assignment") == sa.name}
        self.assertEqual(tagged, {getdate("2031-05-03"), getdate("2031-05-04")})

        sa.reload()
        sa.cancel()
        rows = _rows(hl)
        self.assertFalse([d for d, h in rows.items() if h.get("ess_shift_assignment") == sa.name])
        self.assertIn(getdate("2031-05-20"), rows)
        self.assertIn(NATIONAL_DAY, rows)

        sa2 = self._sa(self.a, getdate("2031-06-07"), getdate("2031-06-08"))
        self.assertIn(getdate("2031-06-07"), _rows(hl))
        sa2.cancel()
        frappe.delete_doc("Shift Assignment", sa2.name, ignore_permissions=True)
        self.assertNotIn(getdate("2031-06-07"), _rows(hl))

    def test_personal_list_follows_shared_list(self):
        self._sa(self.a, getdate("2031-07-05"), getdate("2031-07-05"))
        hl = _list_for(self.a, getdate("2031-07-05"))
        shared = frappe.get_doc("Holiday List", SHARED)
        shared.append("holidays", {"holiday_date": getdate("2031-07-23"), "description": "Renaissance Day",
                                   "weekly_off": 0})
        shared.save(ignore_permissions=True)
        rows = _rows(hl)
        self.assertEqual(rows[getdate("2031-07-23")].description, "Renaissance Day")
        self.assertIn(getdate("2031-07-05"), rows)

    def test_missing_list_blocks_or_skips(self):
        with self.assertRaises(frappe.ValidationError):
            self._sa(self.b, getdate("2031-12-30"), getdate("2032-01-02"))
        _settings(weekly_off_missing_list="Skip those days and note it on the assignment")
        try:
            sa = self._sa(self.b, getdate("2031-12-30"), getdate("2032-01-02"))
            hl = _list_for(self.b, getdate("2031-12-30"))
            tagged = {d for d, h in _rows(hl).items() if h.get("ess_shift_assignment") == sa.name}
            self.assertEqual(tagged, {getdate("2031-12-30"), getdate("2031-12-31")})
            self.assertIn("Not written", frappe.db.get_value("Shift Assignment", sa.name, "ess_holiday_lists"))
        finally:
            _settings(weekly_off_missing_list="Stop with an error")

    def test_later_company_list_still_applies(self):
        if not _has_hla():
            self.skipTest("no Holiday List Assignment in this release")
        self._sa(self.a, getdate("2031-08-02"), getdate("2031-08-02"))
        nxt = "ESS WO Test Shared 2032"
        if not frappe.db.exists("Holiday List", nxt):
            frappe.get_doc({"doctype": "Holiday List", "holiday_list_name": nxt, "from_date": getdate("2032-01-01"),
                            "to_date": getdate("2032-12-31")}).insert(ignore_permissions=True)
        hla = frappe.get_doc({"doctype": "Holiday List Assignment", "applicable_for": "Company",
                              "assigned_to": self.company, "holiday_list": nxt, "from_date": getdate("2032-01-01")})
        hla.insert(ignore_permissions=True)
        hla.submit()
        self.assertEqual(_list_for(self.a, getdate("2032-03-01")), nxt)
