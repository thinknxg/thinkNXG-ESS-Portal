# thinkNXG ESS Portal

Enterprise Employee Self-Service for **thinkNXG HR v16** — a Vue 3 + TypeScript PWA served at `/ess` by a custom thinkNXG app, for employees, managers and HR.

The portal is an experience layer. Attendance, leave, payroll, expenses, performance and workflows stay in thinkNXG HR; the app never re-implements leave maths, payroll or accounting. Custom DocTypes exist only for capabilities thinkNXG HR doesn't have (helpdesk, letters, recognition, AI audit, policies, delegation).

```
Vue 3 PWA (/ess)    ──  Router guards, Pinia, in-memory server cache, offline queue
        │  same-origin session + CSRF, no API keys in the browser
thinkNXG API layer  ──  thinknxg_ess_portal.api.*  (identity → scope → validation → idempotency → audit)
        │
Native thinkNXG HR  ──  Employee, Checkin, Attendance(+Request), Leave Application/Allocation/Ledger,
                        Salary Slip, Expense Claim, Employee Advance, Shift Request, Shift Assignment, Goal, Appraisal, Training
Custom ESS          ──  39 DocTypes in module "ESS Portal"
Infra               ──  MariaDB · Redis (cache, rate limits, AI transcripts) · RQ jobs · scheduler · private files
```

## Install

```bash
cd frappe-bench
bench get-app /path/to/thinknxg_ess_portal        # or your git remote
bench --site your.site install-app thinknxg_ess_portal
bench --site your.site migrate
bench build --app thinknxg_ess_portal              # copies the prebuilt SPA into /assets
```

The zip ships with the frontend already built (`thinknxg_ess_portal/public/ess`, `www/ess.html`), so Node is not needed on the server. To rebuild:

```bash
cd apps/thinknxg_ess_portal/frontend
npm ci && npm run build        # type-check, Vite build, writes www/ess.html, stamps the service worker
npm run dev                    # http://localhost:8080/ess, proxies /api to FRAPPE_URL (default :8000)
npm test                       # Vitest
```

Requires `frappe`, `erpnext`, `hrms` (v16). Optional: `pip install pypdf` (index PDF policies), `pywebpush` (push notifications).

**After install**
1. Assign roles: `ESS Portal Admin`, `ESS HR Agent`, `ESS Payroll Officer`, `ESS Department Head` (created on install). Set *ESS Department Head* on Department records if department heads need team scope.
2. Open **ESS Portal Settings**: brand, module toggles, attendance rules, SLA defaults, AI provider + key, VAPID keys.
3. Add **ESS Knowledge Source** records (policies/FAQs) for the assistant; edit the two seeded **ESS Document Templates** and set a Letter Head.
4. Seeded: 7 helpdesk categories (incl. confidential *Payroll & Salary*, *Visa & Residency*), 5 recognition values, 7 badges.

## Roles and scope

| Capability | Employee | Manager (derived) | HR User / HR Manager | ESS HR Agent | ESS Payroll Officer | ESS Portal Admin |
|---|---|---|---|---|---|---|
| Own profile, attendance, leave, payslips, expenses | ✔ | ✔ | ✔ | if employee | if employee | if employee |
| Team attendance, calendar, approvals | – | reporting line (recursive) + headed departments + active delegations | company scope / all | – | – | – |
| Other employees' payslips | – | – | HR Manager (audited) | – | ✔ (audited) | – |
| HR tickets | own | own | all | non-confidential + assigned | confidential + assigned | all |
| Generate letters | eligible templates | eligible | approve per template role | – | – | ✔ |
| Analytics | own | team aggregates | HR scope, k-anonymised | – | – | – |
| Portal configuration, AI sources, audit trail | – | – | – | – | – | ✔ |

"Manager" is never a role check — it is derived per request from `Employee.reports_to` (recursive) and `Department.ess_department_head`. Every API derives identity from `frappe.session.user`; no endpoint accepts an employee id for the caller's own data. Router guards only shape navigation.

Record-level rules for custom DocTypes are enforced in `permissions/__init__.py` via `permission_query_conditions` and `has_permission`, so Desk and `/api/resource` cannot widen access either.

## API contracts (`/api/method/thinknxg_ess_portal.api.<module>.<fn>`)

| Module | Endpoints |
|---|---|
| `bootstrap` | `get_boot` |
| `dashboard` | `get_summary` |
| `inbox` | `get_items(cursor, limit, type)` → `{items[], total, next_cursor}` |
| `attendance` | `get_today`, `precheck`, `check_in`, `check_out`, `my_checkin_log`, `get_month`, `request_correction`, `my_corrections` |
| `roster` | employee: `my_schedule`, `swap_candidates`, `request_change`, `respond_swap`, `cancel_request`, `holidays`, `calendar_ics` · planner: `list_rosters`, `team_members`, `create_roster`, `get_roster`, `save_cells`, `add_employees`, `remove_employee`, `apply_pattern`, `copy_from`, `set_requirements`, `validate_roster`, `publish`, `archive`, `patterns`, `save_pattern` |
| `checkin_admin` | `get_overview`, `save_policy`, `list_locations`, `save_location`, `list_overrides`, `save_override`, `remove_override`, `resolve_for`, `logs`, `log_detail` |
| `leave` | `get_overview`, `preview`, `create_request`, `my_requests`, `withdraw_request`, `get_calendar` |
| `payroll` | `list_payslips`, `get_payslip`, `download_payslip`, `get_benefits` |
| `expenses` | `overview`, `create_claim`, `claim_detail`, `request_advance` |
| `profile` | `get_profile`, `request_change`, `save_employee_document` |
| `approvals` | `get_pending`, `get_detail`, `act`, `bulk_act`, `history`, `list_delegations`, `save_delegation`, `revoke_delegation`, `search_colleagues` |
| `team` | `get_overview`, `get_exceptions`, `get_member` |
| `helpdesk` | `categories`, `my_tickets`, `create_ticket`, `get_ticket`, `reply`, `reopen`, `rate`, `close`, `faqs` · agent: `queue`, `assign`, `set_status`, `set_priority`, `agents`, `canned_responses` |
| `documents` | `overview`, `request`, `cancel_request`, `download`, `admin_requests`, `regenerate` |
| `policies` | `list_mine`, `get_policy`, `acknowledge` |
| `announcements` | `list_announcements`, `mark_read`, `save_announcement`, `admin_list` |
| `recognition` | `feed`, `summary`, `give`, `react`, `team_summary`, `moderation_queue`, `moderate` |
| `goals` | `overview`, `update_goal_progress` |
| `analytics` | `employee`, `manager`, `hr` |
| `assistant` | `ask`, `confirm_action`, `feedback`, `conversations`, `suggestions` |
| `notifications` | `list_notifications`, `mark_read`, `get_preferences`, `set_preference`, `push_subscribe`, `push_unsubscribe` |
| `hr_admin` | `employee_search`, `employee_detail`, `verify_document`, `expiring_documents`, `get_settings`, `save_settings`, `save_knowledge_source`, `audit_events`, `ai_quality` |

All mutations accept `client_request_id`; `services/idempotency.run_once` records it in **ESS Offline Action**, so retries, double taps and offline replays never duplicate a request. Reads are GET-only, mutations POST-only.

## Custom DocTypes (module "ESS Portal")

Settings & ops: ESS Portal Settings · ESS Notification Preference · ESS Push Subscription · ESS Offline Action · ESS Audit Event · ESS Analytics Snapshot · ESS Approval Delegation
Helpdesk: ESS HR Ticket · ESS HR Ticket Comment · ESS HR Ticket Category · ESS Canned Response
Documents: ESS Document Template · ESS Document Request · ESS Employee Document (passport/resident card/visa/labour card with expiry)
Recognition: ESS Recognition · ESS Recognition Reaction · ESS Recognition Category · ESS Badge · ESS Badge Award
AI: ESS AI Conversation (metadata) · ESS AI Message Audit (no message text) · ESS Knowledge Source · ESS Knowledge Chunk
Comms: ESS Announcement · ESS Announcement Read · ESS Policy · ESS Policy Acknowledgement
Profile: ESS Profile Change Request · ESS Profile Change Item (child)

Check-in control: ESS Checkin Location · ESS Checkin Policy (+ ESS Checkin Policy Location) · ESS Checkin Log
Roster: ESS Roster (+ ESS Roster Requirement) · ESS Roster Entry · ESS Shift Pattern (+ ESS Shift Pattern Step) · ESS Roster Change Request

Custom fields: `Department.ess_department_head`, `Attendance Request.ess_status` / `ess_review_comment` (thinkNXG HR has no rejected state for drafts), `Shift Assignment.ess_roster` (marks assignments a roster owns), `Shift Type.ess_code` / `ess_color` (grid labels), `Employee Checkin.ess_source` / `ess_accuracy` / `ess_location` / `ess_distance` / `ess_log` (portal punch context; device and Desk punches leave them empty).

## How the key flows work

- **Check-in** — see *Employee check-in control* below. Server time only; never queued offline.
- **Leave** — balances from `get_leave_details`, days from `get_number_of_leave_days`, balance from `get_leave_balance_on`; overlap/holiday preview recalculated server-side on every date change and again at submit.
- **Approvals** — a request is actionable only if it is in the caller's computed pending list (approver field, reporting line, HR role, or active delegation). If a thinkNXG Workflow exists for the DocType, the matching workflow action is applied instead of setting status. Rejections require a reason. Every decision writes an ESS Audit Event.
- **Delegation** — hourly job shares open documents with the delegate and revokes on expiry.
- **Letters** — HR-authored Jinja templates (validated, versioned on change); employees pick a template, never fields or code. Eligibility (status, service months, monthly limit), optional approval by template role, PDF rendered in a background job, stored as a private File, verification code + public `/ess-verify` page (rate-limited, toggleable).
- **Helpdesk** — SLA due dates from category; transition map enforced in the controller; 15-minute escalation job (level 1 → category escalation user, level 2+ → HR Managers); internal notes never leave the server for employees; auto-close after N days.
- **Recognition** — monthly points budget per sender, optional HR moderation, no self-recognition, rule badges (anniversary, recognitions received/given, training, onboarding, policies). No rankings, nothing tied to hours or attendance.
- **Analytics** — server-side aggregates only; HR breakdowns below `min_group_size` (default 5) are suppressed; daily snapshot table for trend reporting.

## Employee check-in control

Settings live in **ESS Portal Settings → Employee Check-in / Geolocation** and in the portal at **HR operations → Check-in control** (HR Managers and ESS Portal Admins edit; HR Users view).

| Setting | Effect |
|---|---|
| Global employee check-in | Default permission for portal users. |
| Employee permission policy | *Allow employee-specific overrides*: an ESS Checkin Policy can allow or deny one person against the default. *Enforce global setting for everyone*: overrides are ignored. |
| Require GPS verification | Location must be captured before a punch is accepted. |
| Geofence enforcement | *Enforce geofence* (must be inside a permitted location) or *Record location only*. |
| Allowed geofence radius | Default radius for locations without their own. |
| Maximum GPS accuracy uncertainty | A fix reported worse than this (e.g. ±50 m) is refused with a specific message. |
| Allow check-in only during assigned shift window | IN punches only between *shift start − early minutes* and *shift end + late minutes*, from the Shift Type's own buffers (portal defaults when they are 0). Overnight shifts are handled. |
| Allow check-in on days without a shift | Otherwise rest days, holidays and unassigned days refuse IN punches. |

Per-employee **ESS Checkin Policy**: portal access (Inherit/Allow/Deny), GPS (Inherit/Required/Exempt), shift window (Inherit/Enforce/Don't enforce), radius and accuracy overrides, extra or exclusive locations, validity dates and a mandatory reason. Every change is written to ESS Audit Event.

**Permitted locations** for a punch are the Shift Location on the employee's current Shift Assignment (if enabled), active **ESS Checkin Locations** that apply to the employee (all, company, branch or department), and any locations listed on their override. *Only these locations* restricts them to the override's list.

**Decision order** (`services/checkin_policy.evaluate`): portal access → punch sequence (no double IN; OUT needs an open IN in the last 20 hours) → cooldown → shift window or no-shift rule → GPS presence, accuracy, geofence → risk flags. Every attempt, allowed or denied, writes an **ESS Checkin Log** with server and device time, coordinates, accuracy, matched or nearest location and distance, shift window, risk flags, IP, user agent and the full policy trace. HR can filter and export it at **HR operations → Check-in audit**.

**Channels are independent.** These rules apply only to `attendance.check_in`/`check_out`. Biometric devices posting to the Employee Checkin API and HR staff in Desk are untouched, so turning portal check-in off never stops a device integration.

**thinkNXG HR's own rule still applies.** If *HR Settings → Allow Geolocation Tracking* is on, thinkNXG HR validates every Employee Checkin against the Shift Location radius and requires coordinates. An ESS GPS exemption or an extra ESS location cannot override that; the portal reports it as `NATIVE_VALIDATION` and the settings page warns when it is on. Turn it off if ESS should be the single decision-maker.

**About GPS.** Browsers share location only over HTTPS (or localhost) and only with the employee's permission; the page explains each failure (blocked, unavailable, timeout, insecure). The server re-checks every coordinate, but a phone's reported position can't prove physical presence. Risk flags (unrealistic ±0 m accuracy, travel faster than *max travel speed*, coordinates identical to another day's) are logged for review and can optionally block.

## Rosters

**Employees** get *My roster* (week and month views, shift times, check-in window, location, rest days, holidays, leave), *Holidays* (year view, next holiday, weekly offs, .ics download) and can request a **shift change**, a **rest day** or a **swap with a colleague**. A swap goes to the colleague first, then to the approver (the roster's planner, or the reporting manager). Requests need the configured notice and must fall on a published roster. They appear in the existing Approvals queue as *Roster changes*.

**Managers and HR** use the **Roster planner**: paint shifts with click, drag or keyboard; apply rotation patterns (e.g. 2 days, 2 evenings, 1 night, 2 off) with a per-person stagger; copy a previous roster (whole weeks repeat so weekdays line up); set coverage needs per shift and weekday. Live checks cover overlapping shifts, minimum rest, maximum consecutive days, maximum weekly hours, coverage gaps, leave clashes, people on two rosters, default shifts on rest days, and manual Shift Assignments in the way. Managers can only roster their own reporting line; HR works within its scope.

**Publishing** writes native **Shift Assignments**, one per run of identical days, tagged with `ess_roster`, so thinkNXG HR auto-attendance, shift-based check-in linking and payroll keep working as they do today:
- By default only today onward is written, and past days lock once published. See *Past days* below.
- Republishing ends or cancels the roster's own future assignments and recreates them; untagged (manual) assignments are never touched unless HR ticks *trim manual assignments*, which ends or deactivates them with a comment.
- Rest days become **Weekly Off** shift assignments (see below) while *Publish roster rest days as weekly-off assignments* is on; otherwise they get no assignment, and an employee with a **default shift** may then be marked absent by thinkNXG HR, so the planner warns.
- People whose plan changed are notified. Each publish is recorded in ESS Audit Event.

**Department and branch filters.** The planner and the roster list filter by department, branch and name (kept in the URL, so a filtered view can be bookmarked). New rosters can be created for a whole department or branch, and *Add people* filters the same way. When a filter is on, coverage counts only the people shown and the planner says so.

**Weekly offs.** Weekly offs come from each employee's holiday list (`Employee.holiday_list`, falling back to the company's). With *Mark weekly offs from holiday lists* on, new rosters, patterns and copies prefill them as rest days shown as **W**; *Weekly offs* in the planner re-applies them for everyone, the selected people or the people shown, and keeps days that already have a shift unless you choose to overwrite. Rostering a shift on a weekly off is flagged in the checks. Rest days on non-weekly-off days still show as **R**.

**Past days.** Users with **System Manager**, **ESS Portal Admin** or a role listed in *Roles allowed to change past days* (default `HR Manager` and the new `ESS Roster Backdate` role) can turn on *Edit past days* and fill or fix days within *Allow past-day changes for (days)* (default 31; 0 disables it for everyone). Everyone else sees past published days locked, and the server enforces it. When publishing, *Also apply past days* writes Shift Assignments for the past window:
- days with submitted **Attendance** are skipped and reported, so payroll-relevant attendance is never silently contradicted;
- manual (untagged) Shift Assignments are never changed for past days; they are reported instead;
- the roster's own assignments are split around the changed range, so earlier and later days keep their assignment;
- every past edit and backfill is written to ESS Audit Event.

After a backfill, re-run *Process Auto Attendance* on the affected Shift Types (or mark attendance) for the past days to pick up the new shifts.

## Weekly offs in holiday lists

A Shift Assignment can be a **Weekly Off / Rest Day**: tick *Weekly Off / Rest Day* on the Shift Assignment form (Desk), which switches it to the *Weekly Off* shift type and makes the end date mandatory, or publish a roster whose rest days are planned in the portal (the planner's *Weekly offs → Set a rest period* marks a start-to-end range for many people at once). Any Shift Type can be marked *Weekly Off / Rest Day*; install creates one called **Weekly Off** (all day, auto attendance off).

| Assignment event | Holiday list |
|---|---|
| Submitted | every date from start to end date is added as **"Weekly Off"** (`weekly_off = 1`), tagged with the assignment's name |
| End date or status changed | its own rows that no longer apply are removed, new dates are added |
| Cancelled or deleted | all rows tagged with that assignment are removed |

What is never touched: dates that were already holidays (public holidays, the list's own weekly offs, rows added by hand, other assignments' rows) are left as they are and are not removed later. Only rows carrying the assignment's tag (`Holiday.ess_shift_assignment`) are ever deleted.

**Which holiday list.** The list is the one thinkNXG HR applies to the employee on each date (Holiday List Assignments in v16, honouring list changes within the range; `Employee.holiday_list` on releases without them). Shared lists are never written to:
- the first time an employee needs weekly offs in a shared list, a **personal copy** is created (`<list> · <employee>`, with *ESS Personal List For* and *ESS Copied From* set) and assigned to the employee from the date the shared list applied to them. A list used only by that employee is written directly;
- the copy follows the shared list: when HR edits the shared list, its holidays are re-copied into every personal copy, keeping the weekly-off rows and anything added by hand to the copy (a new public holiday on the same date as a weekly off replaces the weekly-off row, noted on the list);
- because thinkNXG HR picks an employee's own assignment before the company's, later company Holiday List Assignments are mirrored onto these employees (now and whenever a new company assignment is submitted), so next year's company list still applies. Generated assignments are marked *Created by ESS (weekly offs)*.

If no holiday list covers a date (for example a weekly off in January before next year's list exists), the assignment is refused with a clear message, or, with *When no holiday list covers a date → Skip*, those days are skipped and noted in the assignment's *Holiday List Entries* field.

Notes: a Weekly Off assignment overlaps any working shift on the same dates, so thinkNXG HR's own overlap check stops the two being combined. Punches on such a day are still recorded (portal check-in follows the *allow check-in without a shift* setting); turn on auto attendance for the Weekly Off shift type if those days should be marked Present automatically (they then qualify for compensatory leave), since generated holidays stop them being marked absent.

## Check-in records

*Check-in records* (employees) lists every **Employee Checkin** for the person, grouped by day, from all channels: this portal, biometric devices (by `device_id`) and Desk/API, with first in, last out, missing check-outs and the day's attendance. *Team check-ins* (managers and HR) adds date, department, branch and employee filters, an "only days needing attention" view and CSV export.

| Setting | Effect |
|---|---|
| Employees can see their own check-in records | turns the employee page on or off |
| Managers can see check-ins of | *Direct and indirect reports* / *Direct reports only* / *None* |
| Show raw GPS coordinates to | *HR only* (default) or *HR and managers*; employees always see their own; otherwise only the matched location and distance are returned |
| Maximum days per check-in records query | caps every request (default 31 days) |

HR users see everyone within their HR scope. The rules are applied on the server; the menu entry only appears when the user has access.

## Compensatory leave

Employees open *Compensatory leave* (in the menu and on the Leave page) and see the days in the last *Claim worked days from the last (days)* (default 60) they worked on a **weekly off**, a **holiday** (from their holiday list) or, if allowed, a **published roster rest day**, with attendance status and hours. A day qualifies when it has submitted attendance (Present, Work From Home or Half Day), meets *Minimum worked hours for a claim*, and isn't already claimed by an open or approved request. Half-day attendance counts as half a day.

Requests are native **Compensatory Leave Request** documents, so allocation follows thinkNXG HR: consecutive full days become one request; each half day becomes its own request (the native form allows one half day per request). The request goes to the employee's leave approver (or reporting manager) and appears in *Approvals* and the inbox as *Comp-off*. Approving submits the request, which credits the leave; rejecting keeps it as a draft marked *Rejected* with the reviewer's comment; the employee can withdraw a pending request.

Setup on the bench:
- mark at least one **Leave Type** as *Is Compensatory*;
- an active **Leave Period** must cover the work dates, or thinkNXG HR refuses to submit the request;
- roster rest days are accepted through an override of `CompensatoryLeaveRequest.validate_holidays` (`overrides/compensatory_leave_request.py`), only while *Roster rest days are eligible* is on; holiday-list days follow the native rules.

New endpoints: `roster.mark_weekly_offs`, `roster.publish(backfill=1)`, `attendance.my_checkins`, `checkin_records.team_checkins`, `comp_off.eligible_days`, `comp_off.create_request`, `comp_off.my_requests`, `comp_off.withdraw`. Settings live in *ESS Portal Settings → Roster, records & leave* and in the portal under *Check-in control*.

## AI HR assistant

`services/assistant.py` → identity check → module/rate limit → deterministic refusal guard for other people's pay/personal data → redaction (IBAN, card/account numbers, emails, phones) → model with **allow-listed tools** → proposal.

- Tools (`services/ai_tools.py`) take **no identity arguments**; any `employee`/`user` argument a model invents is stripped. Data always comes from the session employee, so "show me Ahmed's payslip" cannot succeed even if the model tries.
- Policy answers come from BM25 retrieval over **ESS Knowledge Chunk**, filtered by audience/company/department *before* scoring, cited as [1], [2]. Retrieved text is labelled as data in the system prompt.
- Consequential actions (leave request, HR ticket) are returned as proposals held in Redis for 15 minutes; the employee confirms in a card, and the normal API (with validation and idempotency) runs.
- Payslip amounts are hidden from the model unless `ai_allow_salary_answers` is on.
- Providers: Anthropic Messages API or any OpenAI-compatible endpoint; key stored as a Password field, server-side only. With the provider *Disabled*, the assistant still works in deterministic mode (intent routing + policy excerpts + "raise a ticket" proposal).
- Audit stores metadata only (intent, tools, sources, outcome, latency, redaction count, feedback). Transcripts live in Redis for 24 h. Retention job purges metadata after `ai_retention_days`.

## PWA

Manifest + icons under `/assets/thinknxg_ess_portal/ess/`, service worker served from `www/ess-sw.js` with scope `/ess`. Hashed assets cache-first; navigation network-first with an offline page; `/api`, `/files`, `/private` are never cached. Leave requests, tickets and recognition can be queued offline (state shown as Queued → Submitted → Confirmed) and replay with the same request id; check-in and approvals require a live server confirmation. Web Push via VAPID (optional `pywebpush`); payloads carry only a title and route. Logout clears caches and the offline queue.

EN/AR with full RTL, light/dark/system themes, keyboard command palette (Ctrl/⌘ K), skip link, focus-trapped dialogs, reduced-motion support, touch-sized controls and a bottom tab bar with a centre punch button on mobile.

## Tests

- `thinknxg_ess_portal/tests/test_pure.py` — 20 unit tests for geofence maths, accuracy rules, risk flags, shift windows (including overnight and thinkNXG's timedelta times), roster rules, coverage and rotation patterns. Runs without a bench: `python -m pytest thinknxg_ess_portal/tests/test_pure.py`.
- `thinknxg_ess_portal/tests/test_weekly_off_rules.py` — 8 unit tests for which holiday rows an assignment adds, keeps and removes, personal-list mirroring and company-assignment mirrors (no bench needed).
- `thinknxg_ess_portal/tests/test_checkin_roster.py` — integration tests: global off vs. Allow override, *Enforce global* ignoring overrides, Deny override writing a denied log, outside-geofence and poor-accuracy refusals, GPS exemption, shift-window enforcement, managers blocked from rostering outside their team, publish creating tagged assignments and republish replacing them, swap needing colleague acceptance before it reaches the manager.
- `thinknxg_ess_portal/tests/test_roster_compoff.py` — weekly offs prefilled and re-marked, past days locked without the backdate role, backdate role filling a missing past assignment, backfill skipping days with attendance, comp-off eligibility, double-claim prevention and rejection, working days refused, check-in visibility for employees vs managers and hidden coordinates, range cap.
- `thinknxg_ess_portal/tests/test_weekly_off.py` — ticking Weekly Off, personal list created while the shared list and colleagues stay unchanged, change/cancel/delete removing only the assignment's rows, personal list following the shared list, missing-list stop vs skip, next year's company list still applying.

- `thinknxg_ess_portal/tests/test_security.py` — colleague ticket isolation, confidential tickets hidden from agents, internal notes hidden, manager scope = reporting line, non-manager blocked from team member, unauthorised approval blocked, protected profile fields rejected, idempotent duplicate submission, assistant refusal for a colleague's payslip, AI tool identity stripping, self-recognition blocked.
  `bench --site test.site run-tests --app thinknxg_ess_portal`
- `frontend/tests/unit.spec.ts` — markdown XSS escaping and link allow-list, offline queue rules, format helpers (`npm test`).

## Notes and assumptions to verify on your bench

- Python package is `thinknxg_ess_portal` (thinkNXG requires the package to match the app name), so methods are `thinknxg_ess_portal.api.*` rather than `ess_portal.api.*`.
- Field names follow thinkNXG HR v16 and are guarded with `meta.has_field` where they vary (Checkin latitude/longitude, Shift Location, Overtime Slip, Employee Benefit Ledger, Goal, Onboarding). Confirm against your installed release and customisations.
- Expense claims are created as drafts with the company's default payable account; submission/payment stays with Accounts unless *Auto-submit approved expenses* is enabled. Employee Advance uses the company's default advance account.
- The UI uses its own lightweight component set rather than `frappe-ui`, to keep the build reproducible; it can be swapped in later without touching the API layer.
- Realtime events are published (`ess_notification`, `ess_ticket_update`); the SPA polls unread counts every 60 s and does not require socket.io.
