"""Weekly Off / Rest Day Shift Assignments, written into the employee's holiday list.

A Shift Assignment is a weekly off when its Shift Type is marked *ESS Weekly Off*, or when *Weekly Off / Rest Day* is
ticked on the assignment (which switches it to the configured Weekly Off shift type). Every date from its start to its
end date becomes a "Weekly Off" holiday in the holiday list the employee follows on that date. Each row is tagged with
the assignment's name, so changing, cancelling or deleting the assignment removes exactly those rows and nothing else.
Dates that are already holidays are left alone and are never removed.

Holiday lists are normally shared by many employees, and a shared list is never changed. The employee gets a personal
copy of it, assigned from the date the shared list applied to them, and the copy follows later edits of the shared list
(Holiday List on_update). thinkNXG HR picks an employee's own holiday-list assignment before the company's, so later
company assignments are mirrored onto the employee to keep them in effect.
"""
from collections import defaultdict
from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import cint, date_diff, getdate
from thinknxg_ess_portal.services import hrms, identity
from thinknxg_ess_portal.services import weekly_off_rules as rules

MAX_DAYS = 400
TYPES_KEY = "ess_shift_type:weekly_off_types"  # cleared with the other shift-type cache keys
SKIP = "Skip those days and note it on the assignment"


# ------------------------------------------------------------------ settings and types
def enabled():
    return bool(cint(identity.settings().get("enable_weekly_off_holidays"))) and _ready()


def _ready():
    return frappe.get_meta("Shift Assignment").has_field("ess_weekly_off") and frappe.get_meta("Holiday").has_field(
        "ess_shift_assignment")


def roster_rest_enabled():
    return enabled() and bool(cint(identity.settings().get("roster_rest_as_weekly_off")))


def has_hla():
    return bool(frappe.db.exists("DocType", "Holiday List Assignment"))


def weekly_off_types():
    v = frappe.cache.get_value(TYPES_KEY)
    if v is None:
        v = (frappe.get_all("Shift Type", filters={"ess_weekly_off": 1}, pluck="name")
             if frappe.get_meta("Shift Type").has_field("ess_weekly_off") else [])
        frappe.cache.set_value(TYPES_KEY, v, expires_in_sec=600)
    return set(v)


def default_type():
    return ensure_shift_type(identity.settings().get("weekly_off_shift_type") or "Weekly Off")


def ensure_shift_type(name="Weekly Off"):
    """The shift type used for weekly offs: all day, no auto attendance, marked ESS Weekly Off."""
    if not frappe.get_meta("Shift Type").has_field("ess_weekly_off"):
        return name
    if frappe.db.exists("Shift Type", name):
        if not cint(frappe.db.get_value("Shift Type", name, "ess_weekly_off")):
            frappe.db.set_value("Shift Type", name, "ess_weekly_off", 1)
            frappe.cache.delete_value(TYPES_KEY)
        return name
    doc = frappe.get_doc({"doctype": "Shift Type", "name": name, "start_time": "00:00:00", "end_time": "23:59:00",
                          "ess_weekly_off": 1, "enable_auto_attendance": 0})
    if doc.meta.has_field("ess_code"):
        doc.ess_code = "W"
    doc.flags.ignore_permissions = True
    doc.insert()
    frappe.cache.delete_value(TYPES_KEY)
    return name


# ------------------------------------------------------------------ report + deferral
def report():
    if getattr(frappe.local, "ess_wo_report", None) is None:
        frappe.local.ess_wo_report = {"added": 0, "removed": 0, "existing": 0, "outside": 0, "assignments": 0,
                                      "personal_lists": [], "mirrored": [], "notes": []}
    return frappe.local.ess_wo_report


def reset_report():
    frappe.local.ess_wo_report = None
    return report()


@contextmanager
def deferred():
    """Collect assignment changes and sync each employee's holiday lists once at the end (used by roster publish)."""
    outer = getattr(frappe.local, "ess_wo_queue", None)
    frappe.local.ess_wo_queue = [] if outer is None else outer
    try:
        yield
        if outer is None:
            queued = list(dict.fromkeys(frappe.local.ess_wo_queue))
            frappe.local.ess_wo_queue = None
            sync_many(queued)
    finally:
        if outer is None:
            frappe.local.ess_wo_queue = None


def queue(name):
    """Ask for a sync of this assignment (now, or when the surrounding deferred() block ends)."""
    if getattr(frappe.local, "ess_wo_queue", None) is not None:
        frappe.local.ess_wo_queue.append(name)
    else:
        sync_many([name])


# ------------------------------------------------------------------ Shift Assignment events
def before_validate(doc, method=None):
    if not _ready():
        return
    types = weekly_off_types()
    if cint(doc.get("ess_weekly_off")) and doc.shift_type not in types:
        doc.shift_type = default_type()
    elif doc.shift_type and doc.shift_type in types:
        doc.ess_weekly_off = 1
    if cint(doc.get("ess_weekly_off")):
        if not doc.end_date:
            frappe.throw(_("A Weekly Off / Rest Day assignment needs an end date."))
        if date_diff(doc.end_date, doc.start_date) + 1 > MAX_DAYS:
            frappe.throw(_("A Weekly Off / Rest Day assignment can cover at most {0} days.").format(MAX_DAYS))


def on_change(doc, method=None):
    """on_submit / on_update_after_submit / on_cancel."""
    if not _ready():
        return
    if doc.docstatus == 1 and not enabled():
        return  # switched off: leave holiday lists as they are until the assignment is cancelled or deleted
    if cint(doc.get("ess_weekly_off")) or frappe.db.exists("Holiday", {"ess_shift_assignment": doc.name}):
        queue(doc.name)


def on_trash(doc, method=None):
    if _ready() and frappe.db.exists("Holiday", {"ess_shift_assignment": doc.name}):
        _sync(doc.name, doc=doc, deleting=True)


# ------------------------------------------------------------------ sync
def sync_many(names):
    for name in names:
        if frappe.db.exists("Shift Assignment", name):
            _sync(name)


def _wanted(doc, deleting=False):
    if deleting or doc.docstatus != 1 or doc.status != "Active" or not cint(doc.get("ess_weekly_off")):
        return set()
    if not doc.end_date:
        return set()
    return set(rules.dates_between(getdate(doc.start_date), getdate(doc.end_date)))


def _sync(name, doc=None, deleting=False):
    doc = doc or frappe.get_doc("Shift Assignment", name)
    rep = report()
    want = _wanted(doc, deleting)
    held = defaultdict(set)
    for r in frappe.get_all("Holiday", filters={"ess_shift_assignment": doc.name, "parenttype": "Holiday List"},
                            fields=["parent", "holiday_date"]):
        held[r.parent].add(getdate(r.holiday_date))

    # 1. which list each date belongs to, checked before anything is changed
    plan, missing = [], set()
    if want:
        covered = set()
        for rng in _ranges(doc.employee, min(want), max(want)):
            lf, lt = frappe.db.get_value("Holiday List", rng.holiday_list, ["from_date", "to_date"])
            inside = {d for d in want if getdate(rng.from_date) <= d <= getdate(rng.to_date) and getdate(lf) <= d <= getdate(lt)}
            if inside:
                plan.append((rng, inside))
                covered |= inside
        missing = want - covered
    if missing:
        msg = _("No holiday list covers {0} for {1}: {2}").format(
            _("{0} day(s)").format(len(missing)), doc.employee,
            ", ".join(str(d) for d in sorted(missing)[:10]) + (" …" if len(missing) > 10 else ""))
        if identity.settings().get("weekly_off_missing_list") != SKIP:
            frappe.throw(msg + ". " + _("Extend the holiday list or assign one that covers these dates."),
                         title=_("Holiday list missing"))
        rep["outside"] += len(missing)
        rep["notes"].append(msg)

    # 2. personal copies only for lists that will actually receive rows
    targets = defaultdict(set)
    for rng, inside in plan:
        hl = rng.holiday_list
        if frappe.db.get_value("Holiday List", hl, "ess_employee") != doc.employee:
            hl = _personalise(doc.employee, hl, getdate(rng.from_date))
        targets[hl] |= inside

    per_list = {}
    for hl in sorted(set(held) | set(targets)):
        per_list[hl] = _write(hl, doc.name, targets.get(hl, set()))
        rep["added"] += per_list[hl]["added"]
        rep["removed"] += per_list[hl]["removed"]
        rep["existing"] += per_list[hl]["existing"]
    rep["assignments"] += 1
    if not deleting and frappe.get_meta("Shift Assignment").has_field("ess_holiday_lists"):
        text = rules.summary({k: v for k, v in per_list.items() if targets.get(k)})
        if missing:
            text = (text + "\n" if text else "") + _("Not written (no holiday list): {0} day(s)").format(len(missing))
        frappe.db.set_value("Shift Assignment", doc.name, "ess_holiday_lists", text or None, update_modified=False)
    return per_list


def _write(hl, tag, wanted):
    hdoc = frappe.get_doc("Holiday List", hl)
    rows = [{"date": getdate(h.holiday_date), "tag": h.get("ess_shift_assignment") or None} for h in hdoc.holidays]
    p = rules.plan_rows(rows, wanted, tag, getdate(hdoc.from_date), getdate(hdoc.to_date))
    out = {"added": len(p["add"]), "removed": len(p["remove"]), "kept": len(p["keep"]),
           "existing": len(p["existing"]), "outside": len(p["outside"])}
    if not p["add"] and not p["remove"]:
        return out
    drop = set(p["remove"])
    hdoc.holidays = [h for h in hdoc.holidays
                     if not (h.get("ess_shift_assignment") == tag and getdate(h.holiday_date) in drop)]
    for d in p["add"]:
        hdoc.append("holidays", {"holiday_date": d, "description": rules.DESCRIPTION, "weekly_off": 1,
                                 "ess_shift_assignment": tag})
    _resort(hdoc)
    _save_list(hdoc)
    return out


def _resort(hdoc):
    hdoc.holidays = sorted(hdoc.holidays, key=lambda h: getdate(h.holiday_date))
    for i, h in enumerate(hdoc.holidays, 1):
        h.idx = i


def _save_list(hdoc):
    hdoc.flags.ignore_permissions = True
    hdoc.flags.ess_weekly_off_sync = True
    hdoc.save()


# ------------------------------------------------------------------ which list, made personal
def _ranges(employee, a, b):
    try:
        from hrms.utils.holiday_list import get_holiday_list_ranges_for_employee
    except ImportError:
        hl = hrms.holiday_list(employee)
        return [frappe._dict(holiday_list=hl, from_date=a, to_date=b)] if hl else []
    return [frappe._dict(r) for r in get_holiday_list_ranges_for_employee(employee, a, b, raise_exception=False)]


def personal_ranges(employee, a, b):
    """The holiday lists in effect for the employee over [a, b], each replaced by the employee's personal copy."""
    out = []
    for r in _ranges(employee, a, b):
        hl = r.holiday_list
        if frappe.db.get_value("Holiday List", hl, "ess_employee") != employee:
            hl = _personalise(employee, hl, getdate(r.from_date))
        out.append(frappe._dict(holiday_list=hl, from_date=r.from_date, to_date=r.to_date))
    return out


def _company_default(hl):
    return frappe.get_meta("Company").has_field("default_holiday_list") and frappe.db.exists(
        "Company", {"default_holiday_list": hl})


def _exclusive(hl, employee):
    """True when only this employee uses the list, so it can be written directly."""
    if _company_default(hl) or frappe.db.exists("Holiday List", {"ess_base_holiday_list": hl}):
        return False
    if has_hla():
        users = set(frappe.get_all("Holiday List Assignment", filters={"holiday_list": hl, "docstatus": 1},
                                   pluck="assigned_to"))
        return users == {employee}
    if not frappe.get_meta("Employee").has_field("holiday_list"):
        return False
    users = set(frappe.get_all("Employee", filters={"holiday_list": hl}, pluck="name"))
    return users == {employee}


def _personalise(employee, base, on_date):
    if _exclusive(base, employee):
        frappe.db.set_value("Holiday List", base, "ess_employee", employee, update_modified=False)
        return base
    copy = _copy(base, employee)
    if has_hla():
        _reassign(employee, base, copy, on_date)
    else:
        frappe.db.set_value("Employee", employee, "holiday_list", copy)
        frappe.get_doc("Employee", employee).add_comment(
            "Info", _("Holiday list changed to {0}, a personal copy of {1}, to hold weekly-off shift assignments.").format(
                copy, base))
    report()["personal_lists"].append({"employee": employee, "holiday_list": copy, "base": base})
    return copy


def _copy(base, employee):
    found = frappe.db.get_value("Holiday List", {"ess_employee": employee, "ess_base_holiday_list": base})
    if found:
        return found
    src = frappe.get_doc("Holiday List", base)
    taken = set(frappe.get_all("Holiday List", filters={"name": ["like", f"{base[:120]}%"]}, pluck="name"))
    doc = frappe.copy_doc(src)
    doc.holiday_list_name = rules.personal_name(base, employee, taken)
    doc.ess_employee = employee
    doc.ess_base_holiday_list = base
    doc.holidays = [h for h in doc.holidays if not h.get("ess_shift_assignment")]
    for h in doc.holidays:
        h.ess_from_base = 1
    _resort(doc)
    doc.flags.ignore_permissions = True
    doc.flags.ess_weekly_off_sync = True
    doc.insert()
    doc.add_comment("Info", _("Personal copy of {0} for {1}, created to hold weekly-off shift assignments. "
                              "It follows changes to {0} automatically.").format(base, employee))
    return doc.name


def _hla_rows(assigned_to):
    meta = frappe.get_meta("Holiday List Assignment")
    extra = [f for f in ("ess_generated", "ess_source", "ess_base_assignment") if meta.has_field(f)]
    return frappe.get_all("Holiday List Assignment", filters={"assigned_to": ["in", assigned_to], "docstatus": 1},
                          fields=["name", "assigned_to", "applicable_for", "holiday_list", "from_date"] + extra,
                          order_by="from_date asc")


def _resolve(own, company, on_date):
    """Same precedence as thinkNXG HR: latest own assignment on or before the date, then the company's,
    then the earliest one of either."""
    for rows in (own, company):
        active = [a for a in rows if getdate(a.from_date) <= on_date]
        if active:
            return active[-1]
    for rows in (own, company):
        if rows:
            return rows[0]
    return None


def _new_hla(employee, holiday_list, from_date, source, base_assignment):
    doc = frappe.get_doc({"doctype": "Holiday List Assignment", "applicable_for": "Employee",
                          "assigned_to": employee, "holiday_list": holiday_list, "from_date": from_date})
    if doc.meta.has_field("naming_series") and not doc.get("naming_series"):
        doc.naming_series = (doc.meta.get_field("naming_series").options or "HR-HLA-.YYYY.-").split("\n")[0]
    for k, v in (("ess_generated", 1), ("ess_source", source), ("ess_base_assignment", base_assignment)):
        if doc.meta.has_field(k):
            doc.set(k, v)
    doc.flags.ignore_permissions = True
    doc.insert()
    doc.submit()
    return doc.name


def _cancel_hla(name, why):
    doc = frappe.get_doc("Holiday List Assignment", name)
    doc.flags.ignore_permissions = True
    doc.flags.ignore_links = True
    doc.cancel()
    doc.add_comment("Info", why)


def _reassign(employee, base, copy, on_date):
    company = frappe.db.get_value("Employee", employee, "company")
    rows = _hla_rows([employee, company])
    own = [r for r in rows if r.assigned_to == employee]
    comp = [r for r in rows if r.assigned_to == company]
    cur = _resolve(own, comp, on_date)
    if not cur or cur.holiday_list != base:
        frappe.throw(_("Couldn't work out which holiday list assignment gives {0} the list {1}.").format(employee, base))
    if cur.assigned_to == employee:
        # The employee's own assignment: swap it for the personal copy from the same date.
        source = cur.get("ess_source") or "Employee"
        _cancel_hla(cur.name, _("Replaced by a personal copy {0} for weekly-off shift assignments.").format(copy))
        _new_hla(employee, copy, cur.from_date, source, cur.get("ess_base_assignment") or cur.name)
        return
    # A company assignment: give the employee the copy from that date, and keep later company lists in effect.
    start = getdate(cur.from_date)
    _new_hla(employee, copy, start, "Company", cur.name)
    for c in rules.mirrors_needed(start, [getdate(r.from_date) for r in own],
                                  [{"name": r.name, "holiday_list": r.holiday_list, "from_date": getdate(r.from_date)}
                                   for r in comp]):
        _new_hla(employee, c["holiday_list"], c["from_date"], "Company", c["name"])
        report()["mirrored"].append({"employee": employee, "holiday_list": c["holiday_list"], "from": str(c["from_date"])})


# ------------------------------------------------------------------ keeping copies and mirrors in step
def on_holiday_list_update(doc, method=None):
    if doc.flags.get("ess_weekly_off_sync") or doc.get("ess_employee") or not _ready():
        return
    if not frappe.get_meta("Holiday List").has_field("ess_base_holiday_list"):
        return
    for name in frappe.get_all("Holiday List", filters={"ess_base_holiday_list": doc.name}, pluck="name"):
        _follow(doc, name)


def _follow(base, name):
    p = frappe.get_doc("Holiday List", name)
    base_rows = [{"date": getdate(h.holiday_date), "description": h.description, "weekly_off": h.weekly_off,
                  "is_half_day": h.get("is_half_day")} for h in base.holidays if not h.get("ess_shift_assignment")]
    own = [{"date": getdate(h.holiday_date), "tag": h.get("ess_shift_assignment") or None,
            "from_base": cint(h.get("ess_from_base")), "description": h.description, "weekly_off": h.weekly_off,
            "is_half_day": h.get("is_half_day")} for h in p.holidays]
    rows, dropped = rules.mirror(base_rows, own)
    p.from_date, p.to_date = base.from_date, base.to_date
    p.holidays = []
    for r in rows:
        if r["date"] < getdate(p.from_date) or r["date"] > getdate(p.to_date):
            continue
        row = {"holiday_date": r["date"], "description": r.get("description") or rules.DESCRIPTION,
               "weekly_off": r.get("weekly_off") or 0, "ess_shift_assignment": r.get("tag"),
               "ess_from_base": 1 if r.get("from_base") else 0}
        if r.get("is_half_day") is not None and frappe.get_meta("Holiday").has_field("is_half_day"):
            row["is_half_day"] = r["is_half_day"]
        p.append("holidays", row)
    _resort(p)
    _save_list(p)
    if dropped:
        p.add_comment("Info", _("{0} now has a holiday on {1}; the weekly-off rows for those dates were replaced.").format(
            base.name, ", ".join(str(r["date"]) for r in dropped)))


def on_hla_submit(doc, method=None):
    """A new company holiday list: mirror it onto employees whose personal-list assignment would hide it."""
    if doc.applicable_for != "Company" or not doc.meta.has_field("ess_generated"):
        return
    employees = {r.assigned_to for r in frappe.get_all(
        "Holiday List Assignment", filters={"ess_generated": 1, "ess_source": "Company", "docstatus": 1,
                                            "applicable_for": "Employee"}, fields=["assigned_to"])}
    if not employees:
        return
    employees &= set(frappe.get_all("Employee", filters={"company": doc.assigned_to, "name": ["in", list(employees)]},
                                    pluck="name"))
    start = getdate(doc.from_date)
    for emp in sorted(employees):
        own = _hla_rows([emp])
        if any(getdate(r.from_date) == start for r in own):
            continue
        cur = [r for r in own if getdate(r.from_date) <= start]
        if cur and cint(cur[-1].get("ess_generated")) and cur[-1].get("ess_source") == "Company":
            _new_hla(emp, doc.holiday_list, start, "Company", doc.name)


def on_hla_cancel(doc, method=None):
    if doc.applicable_for != "Company" or not doc.meta.has_field("ess_base_assignment"):
        return
    for m in frappe.get_all("Holiday List Assignment", filters={"ess_base_assignment": doc.name, "docstatus": 1,
                                                                "ess_generated": 1},
                            fields=["name", "holiday_list", "assigned_to"]):
        if m.holiday_list == doc.holiday_list:
            _cancel_hla(m.name, _("Company holiday list assignment {0} was cancelled.").format(doc.name))
        else:
            frappe.get_doc("Holiday List Assignment", m.name).add_comment(
                "Info", _("Company holiday list assignment {0} was cancelled. This personal holiday list assignment "
                          "was kept because it holds weekly offs; review it.").format(doc.name))
