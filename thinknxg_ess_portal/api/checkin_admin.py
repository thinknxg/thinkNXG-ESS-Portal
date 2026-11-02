import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, today
from thinknxg_ess_portal.api._guard import guard, page, parse
from thinknxg_ess_portal.services import checkin_policy, identity, shifts
from thinknxg_ess_portal.services.audit import log_event

POLICY_KEYS = ["enable_checkin", "checkin_policy_mode", "enforce_shift_window", "allow_checkin_without_shift",
               "shift_window_early_minutes", "shift_window_late_minutes", "checkin_cooldown_minutes",
               "checkin_rate_limit_per_hour", "require_geolocation", "geofence_enforcement", "default_geofence_radius",
               "max_gps_accuracy", "use_shift_location", "use_ess_locations", "flag_location_risk",
               "block_high_risk_checkins", "max_travel_speed_kmh"]
ROSTER_KEYS = ["enable_roster", "roster_min_rest_hours", "roster_max_consecutive_days", "roster_max_weekly_hours",
               "roster_week_start", "allow_roster_change_requests", "allow_shift_swaps", "roster_change_notice_hours",
               "roster_notify_on_publish", "roster_auto_weekly_off", "roster_backdate_days", "roster_backdate_roles",
               "show_own_checkins", "manager_checkin_visibility", "checkin_coordinates_visible_to",
               "checkin_records_max_days", "enable_comp_off", "comp_off_window_days", "comp_off_allow_roster_rest_days",
               "comp_off_min_hours", "enable_weekly_off_holidays", "roster_rest_as_weekly_off", "weekly_off_shift_type",
               "weekly_off_missing_list"]
RANGES = {"default_geofence_radius": (10, 5000), "max_gps_accuracy": (5, 1000), "shift_window_early_minutes": (0, 720),
          "shift_window_late_minutes": (0, 720), "checkin_cooldown_minutes": (0, 120),
          "checkin_rate_limit_per_hour": (5, 500), "max_travel_speed_kmh": (50, 2000), "roster_min_rest_hours": (0, 24),
          "roster_max_consecutive_days": (0, 31), "roster_max_weekly_hours": (0, 120), "roster_change_notice_hours": (0, 720),
          "roster_backdate_days": (0, 366), "checkin_records_max_days": (1, 92), "comp_off_window_days": (1, 366),
          "comp_off_min_hours": (0, 24)}


def _viewer():
    guard(employee=False)
    if not identity.is_hr():
        frappe.throw(_("Check-in control is restricted to HR."), frappe.PermissionError)


def _manager():
    guard(employee=False)
    if not (identity.is_hr_manager() or identity.is_admin()):
        frappe.throw(_("Only HR Managers and ESS Portal Admins can change check-in policy."), frappe.PermissionError)


def _scope_check(employee):
    sc = identity.hr_scope_employees()
    if sc is not None and employee not in sc:
        frappe.throw(_("Not permitted"), frappe.PermissionError)


def _native_geolocation():
    try:
        return bool(cint(frappe.db.get_single_value("HR Settings", "allow_geolocation_tracking")))
    except Exception:
        return None


@frappe.whitelist(methods=["GET"])
def get_overview():
    _viewer()
    s = frappe.get_single("ESS Portal Settings")
    values = {k: s.get(k) for k in POLICY_KEYS + ROSTER_KEYS}
    p = checkin_policy.resolve(None, settings=frappe._dict(values))
    return {"values": values, "summary": checkin_policy.summary(p), "can_edit": identity.is_hr_manager() or identity.is_admin(),
            "native_geolocation_tracking": _native_geolocation(),
            "shift_types": frappe.get_all("Shift Type", pluck="name", order_by="name asc"),
            "counts": {"overrides": frappe.db.count("ESS Checkin Policy", {"is_active": 1}),
                       "locations": frappe.db.count("ESS Checkin Location", {"is_active": 1}),
                       "denied_7d": frappe.db.count("ESS Checkin Log", {"decision": "Denied",
                                                                        "creation": [">=", add_days(today(), -7)]}),
                       "high_risk_7d": frappe.db.count("ESS Checkin Log", {"risk_level": "High",
                                                                           "creation": [">=", add_days(today(), -7)]})}}


@frappe.whitelist(methods=["POST"])
def save_policy(values):
    _manager()
    values = parse(values, {})
    s = frappe.get_single("ESS Portal Settings")
    changed = []
    for k, v in values.items():
        if k not in POLICY_KEYS + ROSTER_KEYS:
            continue
        if k in RANGES and v not in (None, ""):
            lo, hi = RANGES[k]
            if not lo <= float(v) <= hi:
                frappe.throw(_("{0} must be between {1} and {2}.").format(s.meta.get_label(k), lo, hi))
        if s.get(k) != v:
            s.set(k, v)
            changed.append(f"{k}={v}")
    s.save(ignore_permissions=True)
    shifts.clear_cache()
    log_event("Settings Change", s.doctype, s.name, details="check-in/roster policy: " + ", ".join(changed))
    return {"changed": len(changed)}


@frappe.whitelist(methods=["GET"])
def list_locations():
    _viewer()
    rows = frappe.get_all("ESS Checkin Location", fields=["name", "location_name", "latitude", "longitude", "radius",
                                                          "is_active", "applies_to", "company", "branch", "department",
                                                          "shift_location", "address"], order_by="location_name")
    native = []
    if frappe.db.exists("DocType", "Shift Location"):
        native = frappe.get_all("Shift Location", fields=["name", "location_name", "latitude", "longitude", "checkin_radius"])
    return {"locations": rows, "shift_locations": native}


@frappe.whitelist(methods=["POST"])
def save_location(location_name, latitude, longitude, radius=150, applies_to="All Employees", company=None, branch=None,
                  department=None, shift_location=None, address=None, is_active=1, name=None):
    _manager()
    doc = frappe.get_doc("ESS Checkin Location", name) if name else frappe.new_doc("ESS Checkin Location")
    if not name:
        doc.location_name = location_name
    doc.update({"latitude": latitude, "longitude": longitude, "radius": cint(radius), "applies_to": applies_to,
                "company": company if applies_to == "Company" else None, "branch": branch if applies_to == "Branch" else None,
                "department": department if applies_to == "Department" else None, "shift_location": shift_location,
                "address": address, "is_active": cint(is_active)})
    doc.save(ignore_permissions=True)
    return {"name": doc.name}


@frappe.whitelist(methods=["GET"])
def list_overrides(q=None):
    _viewer()
    flt = {}
    sc = identity.hr_scope_employees()
    if sc is not None:
        flt["employee"] = ["in", sc or [""]]
    or_f = {"employee_name": ["like", f"%{q[:60]}%"], "employee": ["like", f"%{q[:60]}%"]} if q else None
    rows = frappe.get_all("ESS Checkin Policy", filters=flt, or_filters=or_f, order_by="modified desc", limit=300,
                          fields=["name", "employee", "employee_name", "is_active", "checkin_access", "gps_requirement",
                                  "shift_window", "radius_override", "accuracy_override", "location_mode", "valid_from",
                                  "valid_until", "reason", "modified", "modified_by"])
    for r in rows:
        r["locations"] = frappe.get_all("ESS Checkin Policy Location", filters={"parent": r.name}, pluck="location")
    return rows


@frappe.whitelist(methods=["POST"])
def save_override(employee, reason, checkin_access="Inherit", gps_requirement="Inherit", shift_window="Inherit",
                  radius_override=None, accuracy_override=None, location_mode="Add to default locations", locations=None,
                  valid_from=None, valid_until=None, is_active=1):
    _manager()
    _scope_check(employee)
    name = frappe.db.get_value("ESS Checkin Policy", {"employee": employee})
    doc = frappe.get_doc("ESS Checkin Policy", name) if name else frappe.new_doc("ESS Checkin Policy")
    doc.update({"employee": employee, "reason": reason, "checkin_access": checkin_access, "gps_requirement": gps_requirement,
                "shift_window": shift_window, "radius_override": cint(radius_override) or None,
                "accuracy_override": cint(accuracy_override) or None, "location_mode": location_mode,
                "valid_from": valid_from or None, "valid_until": valid_until or None, "is_active": cint(is_active)})
    doc.set("locations", [{"location": l} for l in parse(locations, []) if l])
    doc.save(ignore_permissions=True)
    return {"name": doc.name}


@frappe.whitelist(methods=["POST"])
def remove_override(employee):
    _manager()
    _scope_check(employee)
    name = frappe.db.get_value("ESS Checkin Policy", {"employee": employee})
    if name:
        frappe.delete_doc("ESS Checkin Policy", name, ignore_permissions=True)
        log_event("Settings Change", "ESS Checkin Policy", None, employee=employee, details="override removed")
    return {"ok": True}


@frappe.whitelist(methods=["GET"])
def resolve_for(employee):
    _viewer()
    _scope_check(employee)
    emp = frappe.db.get_value("Employee", employee, ["name", "employee_name", "company", "branch", "department",
                                                     "default_shift", "status", "user_id"], as_dict=True)
    if not emp:
        frappe.throw(_("Employee not found"))
    now = frappe.utils.now_datetime()
    p = checkin_policy.resolve(employee, now)
    cur = shifts.current_window(employee, now)
    today_plan = shifts.schedule(employee, getdate(), getdate())[0]
    ref = cur or ((shifts.plan([employee], getdate(), getdate())[employee][0]["windows"] or [None])[0])
    cands = checkin_policy.candidate_locations(emp, p, ref["location"] if ref else None)
    return {"employee": emp, "policy": {k: v for k, v in p.items()}, "summary": checkin_policy.summary(p),
            "locations": cands, "today": today_plan, "window_open": bool(cur),
            "has_portal_user": bool(emp.user_id), "native_geolocation_tracking": _native_geolocation()}


@frappe.whitelist(methods=["GET"])
def logs(from_date=None, to_date=None, employee=None, decision=None, reason_code=None, risk=None, limit=100, offset=0):
    _viewer()
    limit, offset = page(limit, offset)
    flt = {"server_time": ["between", [f"{from_date or add_days(today(), -7)} 00:00:00", f"{to_date or today()} 23:59:59"]]}
    sc = identity.hr_scope_employees()
    if sc is not None:
        flt["employee"] = ["in", sc or [""]]
    if employee:
        flt["employee"] = employee
    if decision:
        flt["decision"] = decision
    if reason_code:
        flt["reason_code"] = reason_code
    if risk:
        flt["risk_level"] = risk
    rows = frappe.get_all("ESS Checkin Log", filters=flt, limit=limit, start=offset, order_by="server_time desc",
                          fields=["name", "employee", "employee_name", "user", "log_type", "decision", "reason_code",
                                  "message", "server_time", "client_time", "source", "checkin", "latitude", "longitude",
                                  "accuracy", "matched_location", "distance_m", "nearest_location", "nearest_distance_m",
                                  "shift_type", "risk_level", "risk_flags", "ip_address", "policy_override"])
    by_code = frappe.get_all("ESS Checkin Log", filters=flt, fields=["reason_code", "decision", "count(name) as n"],
                             group_by="reason_code, decision")
    return {"rows": rows, "summary": by_code}


@frappe.whitelist(methods=["GET"])
def log_detail(name):
    _viewer()
    doc = frappe.get_doc("ESS Checkin Log", name)
    _scope_check(doc.employee)
    return doc.as_dict()
