"""Integration tests for check-in policy and rostering.

Run with:  bench --site <test-site> run-tests --app thinknxg_ess_portal --module thinknxg_ess_portal.tests.test_checkin_roster
"""
import unittest
from datetime import timedelta

import frappe
from frappe.utils import add_days, add_years, getdate, now_datetime, today

try:  # v16
    from frappe.tests import IntegrationTestCase as TestCase
except ImportError:  # v15
    from frappe.tests.utils import FrappeTestCase as TestCase

HQ = (23.5880, 58.3829)


def _user(email, roles=("Employee",)):
    if not frappe.db.exists("User", email):
        frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0,
                        "roles": [{"role": r} for r in roles]}).insert(ignore_permissions=True)
    return email


def _employee(email, reports_to=None):
    name = frappe.db.get_value("Employee", {"user_id": email})
    if name:
        return name
    company = frappe.db.get_value("Company", {}, "name")
    return frappe.get_doc({"doctype": "Employee", "first_name": email.split("@")[0], "gender": "Male",
                           "date_of_birth": add_years(today(), -30), "date_of_joining": add_years(today(), -2),
                           "company": company, "status": "Active", "user_id": email, "reports_to": reports_to,
                           "default_shift": None}).insert(ignore_permissions=True).name


def _shift(name, start, end, buffer=None):
    """thinkNXG HR rejects shifts whose length plus buffers reaches 24 h, so all-day shifts get no buffers."""
    if not frappe.db.exists("Shift Type", name):
        if buffer is None:
            buffer = 0 if (start, end) == ("00:00:00", "23:59:00") else 60
        frappe.get_doc({"doctype": "Shift Type", "name": name, "start_time": start, "end_time": end,
                        "begin_check_in_before_shift_start_time": buffer,
                        "allow_check_out_after_shift_end_time": buffer}).insert(ignore_permissions=True)
    return name


def _settings(**values):
    s = frappe.get_single("ESS Portal Settings")
    s.update(values)
    s.flags.ignore_mandatory = True
    s.save(ignore_permissions=True)
    frappe.cache.delete_value("ess_portal_settings")


class TestCheckinRoster(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not frappe.db.get_value("Company", {}, "name"):
            raise unittest.SkipTest("needs a Company")
        cls.mgr = _user("ess-roster-mgr@example.com")
        cls.a = _user("ess-roster-a@example.com")
        cls.b = _user("ess-roster-b@example.com")
        cls.out = _user("ess-roster-out@example.com")
        cls.mgr_emp = _employee(cls.mgr)
        cls.a_emp = _employee(cls.a, cls.mgr_emp)
        cls.b_emp = _employee(cls.b, cls.mgr_emp)
        cls.out_emp = _employee(cls.out)
        cls.day = _shift("ESS Test Day", "00:00:00", "23:59:00")
        cls.eve = _shift("ESS Test Evening", "14:00:00", "22:00:00")
        if not frappe.db.exists("ESS Checkin Location", "ESS Test HQ"):
            frappe.get_doc({"doctype": "ESS Checkin Location", "location_name": "ESS Test HQ", "latitude": HQ[0],
                            "longitude": HQ[1], "radius": 150, "applies_to": "All Employees"}).insert(ignore_permissions=True)
        _settings(enable_checkin=1, checkin_policy_mode="Allow employee-specific overrides", require_geolocation=1,
                  geofence_enforcement="Enforce geofence", default_geofence_radius=150, max_gps_accuracy=50,
                  enforce_shift_window=0, allow_checkin_without_shift=1, checkin_cooldown_minutes=0,
                  use_ess_locations=1, flag_location_risk=0, enable_roster=1, roster_change_notice_hours=0)
        frappe.db.commit()

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.delete("ESS Checkin Policy", {"employee": ["in", [self.a_emp, self.b_emp]]})
        _settings(enable_checkin=1, checkin_policy_mode="Allow employee-specific overrides", enforce_shift_window=0)

    def _emp(self, user):
        frappe.set_user(user)
        from thinknxg_ess_portal.services import identity
        frappe.local.ess_employee_cache = {}
        return identity.get_employee()

    def _override(self, employee, **kw):
        frappe.set_user("Administrator")
        frappe.get_doc({"doctype": "ESS Checkin Policy", "employee": employee, "reason": "test", **kw}).insert(
            ignore_permissions=True)

    # ---------------------------------------------------------------- policy
    def test_global_off_blocks_unless_override_allows(self):
        from thinknxg_ess_portal.services import checkin_policy
        _settings(enable_checkin=0)
        self.assertFalse(checkin_policy.resolve(self.a_emp).enabled)
        self._override(self.a_emp, checkin_access="Allow")
        self.assertTrue(checkin_policy.resolve(self.a_emp).enabled)

    def test_enforce_global_ignores_overrides(self):
        from thinknxg_ess_portal.services import checkin_policy
        _settings(enable_checkin=0, checkin_policy_mode="Enforce global setting for everyone")
        self._override(self.a_emp, checkin_access="Allow")
        p = checkin_policy.resolve(self.a_emp)
        self.assertFalse(p.enabled)
        self.assertIsNone(p.override)

    def test_deny_override_writes_denied_log(self):
        self._override(self.a_emp, checkin_access="Deny")
        self._emp(self.a)
        from thinknxg_ess_portal.api.attendance import check_in
        res = check_in(latitude=HQ[0], longitude=HQ[1], accuracy=10)
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "CHECKIN_DISABLED")
        self.assertEqual(frappe.db.get_value("ESS Checkin Log", res["log"], "decision"), "Denied")

    def test_outside_geofence_and_poor_accuracy(self):
        emp = self._emp(self.a)
        from thinknxg_ess_portal.services import checkin_policy
        far = checkin_policy.evaluate(emp, "IN", HQ[0] + 0.01, HQ[1], 10)
        self.assertEqual(far.code, "OUTSIDE_GEOFENCE")
        self.assertIn("ESS Test HQ", far.message)
        fuzzy = checkin_policy.evaluate(emp, "IN", HQ[0], HQ[1], 400)
        self.assertEqual(fuzzy.code, "LOCATION_INACCURATE")
        ok = checkin_policy.evaluate(emp, "IN", HQ[0], HQ[1], 15)
        self.assertTrue(ok.allowed, ok.message)

    def test_gps_exempt_employee(self):
        self._override(self.b_emp, gps_requirement="Exempt")
        emp = self._emp(self.b)
        from thinknxg_ess_portal.services import checkin_policy
        self.assertTrue(checkin_policy.evaluate(emp, "IN").allowed)

    def test_shift_window_enforced(self):
        _settings(enforce_shift_window=1, allow_checkin_without_shift=0)
        emp = self._emp(self.b)
        from thinknxg_ess_portal.services import checkin_policy
        res = checkin_policy.evaluate(emp, "IN", HQ[0], HQ[1], 10)
        self.assertIn(res.code, ("OUTSIDE_SHIFT_WINDOW", "NO_SHIFT"))

    # ---------------------------------------------------------------- roster
    def _roster(self):
        frappe.set_user(self.mgr)
        from thinknxg_ess_portal.services import roster
        frappe.local.ess_team_cache = {}
        start = getdate(add_days(today(), 2))
        doc = roster.create("Test roster", start, add_days(start, 6), [self.a_emp, self.b_emp], prefill="empty")
        cells = [{"employee": self.a_emp, "date": add_days(start, i), "shift_type": self.eve} for i in range(3)]
        cells += [{"employee": self.a_emp, "date": add_days(start, 3), "rest": 1}]
        cells += [{"employee": self.b_emp, "date": add_days(start, i), "shift_type": self.day} for i in range(3)]
        roster.save_cells(doc.name, cells)
        return doc, start

    def test_manager_cannot_roster_outside_team(self):
        frappe.set_user(self.mgr)
        from thinknxg_ess_portal.services import roster
        frappe.local.ess_team_cache = {}
        with self.assertRaises(frappe.PermissionError):
            roster.create("Nope", add_days(today(), 1), add_days(today(), 2), [self.out_emp])

    def test_publish_creates_tagged_assignments_and_republish_is_idempotent(self):
        doc, start = self._roster()
        from thinknxg_ess_portal.services import roster
        r1 = roster.publish(doc.name)
        self.assertEqual(r1["created"], 2, r1)
        tagged = frappe.get_all("Shift Assignment", filters={"ess_roster": doc.name, "docstatus": 1},
                                fields=["employee", "shift_type", "start_date", "end_date"])
        self.assertEqual(len(tagged), 2)
        a = next(t for t in tagged if t.employee == self.a_emp)
        self.assertEqual((getdate(a.start_date), getdate(a.end_date)), (start, add_days(start, 2)))
        r2 = roster.publish(doc.name)
        self.assertEqual(r2["created"], 2)
        self.assertEqual(frappe.db.count("Shift Assignment", {"ess_roster": doc.name, "docstatus": 1}), 2)

    def test_swap_needs_colleague_then_manager(self):
        doc, start = self._roster()
        from thinknxg_ess_portal.services import roster, workflow
        roster.publish(doc.name)
        emp_a = self._emp(self.a)
        req = roster.create_change(emp_a, "Swap with colleague", start, start, "family event", swap_with=self.b_emp)
        self.assertEqual(req.status, "Pending Colleague")
        frappe.set_user(self.mgr)
        frappe.local.ess_team_cache = {}
        self.assertNotIn(req.name, [i["name"] for i in workflow.pending(types=["roster"])])
        emp_b = self._emp(self.b)
        roster.respond_swap(req.name, True, emp_b)
        frappe.set_user(self.mgr)
        frappe.local.ess_team_cache = {}
        self.assertIn(req.name, [i["name"] for i in workflow.pending(types=["roster"])])
        workflow.act("ESS Roster Change Request", req.name, "approve")
        a_entry = frappe.db.get_value("ESS Roster Entry", {"roster": doc.name, "employee": self.a_emp, "date": start}, "shift_type")
        self.assertEqual(a_entry, self.day)
