"""Thin compatibility layer over thinkNXG HR v15 functions.

The portal never re-implements leave/attendance/payroll maths - it calls thinkNXG HR. These wrappers
only isolate import paths that moved between releases.
"""
import frappe
from frappe.utils import getdate, flt


def leave_details(employee, date):
    from hrms.hr.doctype.leave_application.leave_application import get_leave_details
    return get_leave_details(employee, date)


def leave_days(employee, leave_type, from_date, to_date, half_day=None, half_day_date=None):
    from hrms.hr.doctype.leave_application.leave_application import get_number_of_leave_days
    return flt(get_number_of_leave_days(employee, leave_type, from_date, to_date, half_day, half_day_date))


def leave_balance(employee, leave_type, date, to_date=None):
    from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on
    return flt(get_leave_balance_on(employee, leave_type, date, to_date,
                                    consider_all_leaves_in_the_allocation_period=True))


def leave_approver(employee):
    try:
        from hrms.hr.doctype.leave_application.leave_application import get_leave_approver
        return get_leave_approver(employee)
    except Exception:
        return frappe.db.get_value("Employee", employee, "leave_approver")


def holiday_list(employee):
    for path in ("hrms.hr.utils.get_holiday_list_for_employee",
                 "erpnext.setup.doctype.employee.employee.get_holiday_list_for_employee"):
        try:
            return frappe.get_attr(path)(employee, raise_exception=False)
        except Exception:
            continue
    hl = frappe.db.get_value("Employee", employee, "holiday_list")
    if not hl:
        company = frappe.db.get_value("Employee", employee, "company")
        hl = frappe.db.get_value("Company", company, "default_holiday_list")
    return hl


def holidays_between(employee, start, end):
    hl = holiday_list(employee)
    if not hl:
        return []
    return frappe.get_all("Holiday", filters={"parent": hl, "holiday_date": ["between", [start, end]]},
                          fields=["holiday_date", "description", "weekly_off"], order_by="holiday_date asc")


def active_shift(employee, date=None):
    """Return the shift (type + timings + optional geofence) for a date."""
    date = getdate(date)
    sa = frappe.db.sql("""
        select name, shift_type, {loc} from `tabShift Assignment`
        where employee=%s and docstatus=1 and status='Active' and start_date<=%s
          and (end_date is null or end_date>=%s)
        order by start_date desc limit 1""".format(
        loc="shift_location" if frappe.get_meta("Shift Assignment").has_field("shift_location") else "null as shift_location"),
        (employee, date, date), as_dict=True)
    shift_type = sa[0].shift_type if sa else frappe.db.get_value("Employee", employee, "default_shift")
    if not shift_type:
        return None
    st = frappe.db.get_value("Shift Type", shift_type, ["name", "start_time", "end_time"], as_dict=True)
    out = {"shift_type": shift_type, "start_time": str(st.start_time) if st else None,
           "end_time": str(st.end_time) if st else None, "location": None}
    if sa and sa[0].shift_location and frappe.db.exists("DocType", "Shift Location"):
        loc = frappe.db.get_value("Shift Location", sa[0].shift_location,
                                  ["name", "location_name", "latitude", "longitude", "checkin_radius"], as_dict=True)
        out["location"] = loc
    return out
