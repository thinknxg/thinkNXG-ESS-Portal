import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, cint, date_diff, get_datetime, get_last_day, getdate, now_datetime, today
from thinknxg_ess_portal.api._guard import guard, page
from thinknxg_ess_portal.services import checkin_policy, geo, hrms, identity, shifts
from thinknxg_ess_portal.services.idempotency import run_once
from thinknxg_ess_portal.services.ratelimit import check_rate


def _logs_since(employee, since):
    return frappe.get_all("Employee Checkin", filters={"employee": employee, "time": [">=", since]},
                          fields=["name", "time", "log_type", "device_id"], order_by="time asc")


def _status_label(day, cur, st, on_leave):
    if cur and st.open_in:
        return "On Duty"
    if cur:
        return "Shift Window Open"
    if on_leave:
        return "On Leave"
    if day["rest_day"]:
        return "Rest Day"
    if day["holiday"] and not day["windows"]:
        return "Holiday"
    if st.open_in:
        return "Checked In"
    if day["windows"]:
        return "Scheduled"
    return "Off Duty"


def _today_state(emp):
    now = now_datetime()
    d = now.date()
    p = checkin_policy.resolve(emp.name, now)
    st = checkin_policy.session_state(emp.name, now)
    cur = shifts.current_window(emp.name, now)
    nxt = shifts.next_window(emp.name, now)
    upcoming_days = shifts.plan([emp.name], d, add_days(d, 6))[emp.name]
    day = upcoming_days[0]
    since = min(get_datetime(f"{d} 00:00:00"), get_datetime(st.open_in.time) if st.open_in else now)
    logs = _logs_since(emp.name, since)
    att = frappe.db.get_value("Attendance", {"employee": emp.name, "attendance_date": d, "docstatus": 1},
                              ["status", "in_time", "out_time", "late_entry", "early_exit"], as_dict=True)
    on_leave = bool(day["leave"] and day["leave"]["status"] == "Approved" and not day["leave"]["half_day"])
    ref = cur or (day["windows"][0] if day["windows"] else None)
    cands = checkin_policy.candidate_locations(emp, p, ref["location"] if ref else None)
    locs = [{"name": c["name"], "radius": c["radius"], "source": c["source"]} for c in cands]
    shift = None
    if ref:
        shift = {"shift_type": ref["shift_type"], "start_time": ref["start"].strftime("%H:%M:%S"),
                 "end_time": ref["end"].strftime("%H:%M:%S"), "code": ref["code"], "color": ref["color"]}
    first_in = next((l.time for l in logs if l.log_type == "IN"), None)
    return {
        "date": str(d), "now": str(now), "status_label": _status_label(day, cur, st, on_leave),
        "shift": shift, "window": shifts.format_window(cur or ref) if (cur or ref) else None,
        "window_open": bool(cur), "next_shift": shifts.format_window(nxt) if nxt else None,
        "shifts_today": [shifts.format_window(x) for x in day["windows"]],
        "logs": [{"time": str(l.time), "log_type": l.log_type, "device": l.device_id} for l in logs],
        "next_action": st.next_action, "last_log": {"time": str(st.last.time), "log_type": st.last.log_type} if st.last else None,
        "first_in": str(first_in) if first_in else None,
        "attendance": att, "on_leave": on_leave, "holiday": day["holiday"], "rest_day": day["rest_day"],
        "checkin_enabled": p.enabled, "require_geolocation": p.gps_required,
        "policy": {"enabled": p.enabled, "gps_required": p.gps_required, "enforce_geofence": p.enforce_geofence,
                   "radius": p.radius, "max_accuracy": p.max_accuracy, "shift_window": p.shift_window,
                   "allow_without_shift": p.allow_without_shift, "summary": checkin_policy.summary(p),
                   "override": bool(p.override)},
        "locations": locs, "geofence": locs[0] if locs else None,
        "upcoming": [shifts.serialize_day(x) for x in upcoming_days[1:]],
    }


@frappe.whitelist(methods=["GET"])
def get_today():
    emp = guard("enable_attendance")
    return _today_state(emp)


@frappe.whitelist(methods=["GET", "POST"])
def precheck(log_type="IN", latitude=None, longitude=None, accuracy=None):
    """Dry run of the policy for the current position. Nothing is written."""
    emp = guard("enable_attendance")
    check_rate("checkin_precheck", 240)
    res = checkin_policy.evaluate(emp, log_type, latitude, longitude, accuracy)
    return checkin_policy.public_result(res)


def _insert_checkin(emp, res, latitude, longitude, accuracy):
    meta = frappe.get_meta("Employee Checkin")
    loc = res.location or {}
    doc = {"doctype": "Employee Checkin", "employee": emp.name, "time": res.now, "log_type": res.log_type,
           "device_id": "thinkNXG ESS Portal"}
    lat, lng = geo._num(latitude), geo._num(longitude)
    if lat is not None and lng is not None and meta.has_field("latitude"):
        doc.update({"latitude": lat, "longitude": lng})
    extras = {"ess_source": "ESS Portal", "ess_accuracy": geo._num(accuracy),
              "ess_location": (loc.get("matched") or {}).get("name"), "ess_distance": loc.get("distance")}
    for k, v in extras.items():
        if meta.has_field(k):
            doc[k] = v
    ci = frappe.get_doc(doc)
    ci.flags.ignore_permissions = True
    ci.insert()
    return {"doctype": "Employee Checkin", "name": ci.name, "time": str(ci.time), "log_type": res.log_type}


def _punch(log_type, latitude=None, longitude=None, accuracy=None, client_time=None, client_request_id=None):
    emp = guard("enable_attendance")
    check_rate("checkin", identity.settings().get("checkin_rate_limit_per_hour") or 30)
    if client_request_id:
        done = frappe.db.get_value("ESS Offline Action", {"client_request_id": str(client_request_id)[:140],
                                                          "user": frappe.session.user, "status": "Processed"},
                                   "reference_name")
        if done:
            t = frappe.db.get_value("Employee Checkin", done, "time")
            return {"ok": True, "duplicate": True, "name": done, "time": str(t), "log_type": log_type}
    res = checkin_policy.evaluate(emp, log_type, latitude, longitude, accuracy)
    if not res.allowed:
        log = checkin_policy.write_log(emp, res, latitude, longitude, accuracy, client_time)
        return {**checkin_policy.public_result(res), "log": log}
    frappe.db.savepoint("ess_punch")
    try:
        out = run_once(client_request_id, f"checkin_{log_type.lower()}",
                       lambda: _insert_checkin(emp, res, latitude, longitude, accuracy))
    except (frappe.ValidationError, frappe.DuplicateEntryError) as e:
        # thinkNXG HR's own Employee Checkin validation (e.g. native geolocation tracking) still applies.
        frappe.db.rollback(save_point="ess_punch")
        frappe.local.message_log = []
        res.update(allowed=False, code="NATIVE_VALIDATION", message=frappe.utils.strip_html(str(e))[:300],
                   hint=_("This was rejected by thinkNXG HR's own check-in rules. Contact HR if it keeps happening."))
        log = checkin_policy.write_log(emp, res, latitude, longitude, accuracy, client_time)
        return {**checkin_policy.public_result(res), "log": log}
    log = checkin_policy.write_log(emp, res, latitude, longitude, accuracy, client_time, checkin=out.get("name"))
    if frappe.get_meta("Employee Checkin").has_field("ess_log") and out.get("name"):
        frappe.db.set_value("Employee Checkin", out["name"], "ess_log", log, update_modified=False)
    matched = ((res.location or {}).get("matched") or {}).get("name")
    t = get_datetime(out["time"]).strftime("%H:%M")
    msg = (_("Checked in at {0}") if log_type == "IN" else _("Checked out at {0}")).format(t)
    if matched:
        msg += f" · {matched}"
    return {**checkin_policy.public_result(res), **out, "ok": True, "message": msg, "log": log}


@frappe.whitelist(methods=["POST"])
def check_in(latitude=None, longitude=None, accuracy=None, client_time=None, client_request_id=None):
    return _punch("IN", latitude, longitude, accuracy, client_time, client_request_id)


@frappe.whitelist(methods=["POST"])
def check_out(latitude=None, longitude=None, accuracy=None, client_time=None, client_request_id=None):
    return _punch("OUT", latitude, longitude, accuracy, client_time, client_request_id)


@frappe.whitelist(methods=["GET"])
def my_checkin_log(limit=30, offset=0):
    emp = guard("enable_attendance")
    limit, offset = page(limit, offset)
    return frappe.get_all("ESS Checkin Log", filters={"employee": emp.name}, limit=limit, start=offset,
                          order_by="creation desc",
                          fields=["name", "log_type", "decision", "reason_code", "message", "server_time",
                                  "matched_location", "distance_m", "accuracy", "shift_type", "risk_level"])


@frappe.whitelist(methods=["GET"])
def my_checkins(from_date=None, to_date=None):
    """The employee's own Employee Checkin records from every channel (portal, devices, Desk)."""
    emp = guard("enable_attendance")
    if not cint(identity.settings().get("show_own_checkins")):
        frappe.throw(_("Check-in records aren't available in the portal. Ask HR."), frappe.PermissionError)
    from thinknxg_ess_portal.api.checkin_records import fetch
    return fetch([emp.name], from_date, to_date, coordinates=True)


@frappe.whitelist(methods=["GET"])
def get_month(year=None, month=None):
    emp = guard("enable_attendance")
    start = getdate(f"{cint(year) or getdate().year}-{cint(month) or getdate().month:02d}-01")
    end = get_last_day(start)
    att = {str(a.attendance_date): a for a in frappe.get_all(
        "Attendance", filters={"employee": emp.name, "docstatus": 1, "attendance_date": ["between", [start, end]]},
        fields=["name", "attendance_date", "status", "in_time", "out_time", "late_entry", "early_exit", "leave_type",
                "shift", "working_hours"])}
    logs = {}
    for l in frappe.get_all("Employee Checkin", filters={"employee": emp.name,
                                                         "time": ["between", [f"{start} 00:00:00", f"{end} 23:59:59"]]},
                            fields=["time", "log_type"], order_by="time asc"):
        logs.setdefault(str(getdate(l.time)), []).append({"time": str(l.time)[11:16], "log_type": l.log_type})
    sched = {str(x["date"]): x for x in shifts.plan([emp.name], start, end)[emp.name]}
    days = []
    for i in range(date_diff(end, start) + 1):
        d = str(add_days(start, i))
        a = att.get(d)
        sd = sched.get(d) or {}
        hol = sd.get("holiday")
        if a:
            status = a.status
        elif sd.get("rest_day"):
            status = "Rest Day"
        elif hol and not sd.get("windows"):
            status = "Weekly Off" if hol["weekly_off"] else "Holiday"
        elif d > today():
            status = "Future"
        else:
            status = "Missing" if logs.get(d) else "Unmarked"
        days.append({"date": d, "status": status, "late": bool(a and a.late_entry),
                     "early_exit": bool(a and a.early_exit), "working_hours": a.working_hours if a else None,
                     "leave_type": a.leave_type if a else None, "logs": logs.get(d, []),
                     "holiday": hol["description"] if hol else None,
                     "shifts": [shifts.format_window(x) for x in sd.get("windows", [])],
                     "incomplete": bool(logs.get(d)) and len(logs.get(d)) % 2 == 1 and d < today()})
    summary = {}
    for d in days:
        summary[d["status"]] = summary.get(d["status"], 0) + 1
    summary["late"] = sum(1 for d in days if d["late"])
    return {"start": str(start), "end": str(end), "days": days, "summary": summary}


@frappe.whitelist(methods=["POST"])
def request_correction(from_date, to_date, reason="On Duty", explanation=None, half_day=0, half_day_date=None,
                       client_request_id=None):
    emp = guard("enable_attendance")
    if reason not in ("Work From Home", "On Duty"):
        frappe.throw(_("Invalid reason"))
    if getdate(from_date) > getdate(to_date):
        frappe.throw(_("From date must be before to date"))
    if getdate(to_date) > getdate(add_days(today(), 31)):
        frappe.throw(_("Corrections can only be requested up to 31 days ahead."))
    if not (explanation or "").strip():
        frappe.throw(_("Please explain the correction."))

    def do():
        doc = frappe.get_doc({"doctype": "Attendance Request", "employee": emp.name, "company": emp.company,
                              "from_date": from_date, "to_date": to_date, "reason": reason,
                              "explanation": explanation[:1000], "half_day": cint(half_day),
                              "half_day_date": half_day_date if cint(half_day) else None})
        doc.insert(ignore_permissions=True)
        approvers = [u for u in frappe.get_all("Employee", filters={"name": emp.reports_to}, pluck="user_id") if u] \
            if emp.reports_to else []
        from thinknxg_ess_portal.services.notifications import notify
        for u in approvers:
            notify(u, "Approvals", _("Attendance correction from {0}").format(emp.employee_name),
                   f"{from_date} → {to_date}", "/ess/team/approvals", doc.doctype, doc.name)
        return {"doctype": doc.doctype, "name": doc.name}

    return run_once(client_request_id, "attendance_correction", do)


@frappe.whitelist(methods=["GET"])
def my_corrections(limit=20, offset=0):
    emp = guard("enable_attendance")
    limit, offset = page(limit, offset)
    fields = ["name", "from_date", "to_date", "reason", "explanation", "docstatus", "creation"]
    if frappe.get_meta("Attendance Request").has_field("ess_status"):
        fields += ["ess_status", "ess_review_comment"]
    rows = frappe.get_all("Attendance Request", filters={"employee": emp.name}, fields=fields,
                          order_by="creation desc", limit=limit, start=offset)
    for r in rows:
        r["status"] = ("Approved" if r.docstatus == 1 else "Cancelled" if r.docstatus == 2 else
                       "Rejected" if r.get("ess_status") == "Rejected" else "Pending")
    return rows
