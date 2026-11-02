/** Typed contracts for thinknxg_ess_portal.api.* — one place to change if the backend moves. */
import { downloadUrl, get, post, requestId } from "./api";
import type { AssistantReply, InboxItem, MutationResult } from "@/types";

const withId = <T extends Record<string, any>>(p: T) => ({ client_request_id: requestId(), ...p });

export const Boot = { get: () => get("bootstrap.get_boot") };
export const Dashboard = { summary: () => get("dashboard.get_summary") };
export const Inbox = {
  items: (cursor?: string | null, type?: string) =>
    get<{ items: InboxItem[]; total: number; next_cursor: string | null }>("inbox.get_items", { cursor, type, limit: 30 }),
};

export const Attendance = {
  today: () => get("attendance.get_today"),
  precheck: (p: Record<string, any>) => get("attendance.precheck", p),
  /** Resolves with { ok: false, code, message, hint } when the policy refuses the punch. */
  checkIn: (p: Record<string, any>) => post<any>("attendance.check_in", withId(p)),
  checkOut: (p: Record<string, any>) => post<any>("attendance.check_out", withId(p)),
  myLog: () => get<any[]>("attendance.my_checkin_log"),
  myCheckins: (from_date: string, to_date: string) => get("attendance.my_checkins", { from_date, to_date }),
  month: (year: number, month: number) => get("attendance.get_month", { year, month }),
  requestCorrection: (p: Record<string, any>) => post<MutationResult>("attendance.request_correction", withId(p)),
  corrections: () => get<any[]>("attendance.my_corrections"),
};

export const Roster = {
  mySchedule: (from_date: string, to_date: string) => get("roster.my_schedule", { from_date, to_date }),
  swapCandidates: (from_date: string, to_date: string) => get<any[]>("roster.swap_candidates", { from_date, to_date }),
  requestChange: (p: Record<string, any>) => post<MutationResult>("roster.request_change", withId(p)),
  respondSwap: (name: string, accept: boolean) => post("roster.respond_swap", { name, accept: accept ? 1 : 0 }),
  cancelRequest: (name: string) => post("roster.cancel_request", { name }),
  holidays: (year: number) => get("roster.holidays", { year }),
  icsUrl: (from_date: string, to_date: string) => downloadUrl("roster.calendar_ics", { from_date, to_date }),
  list: (p: Record<string, any> = {}) => get<any[]>("roster.list_rosters", p),
  teamMembers: (p: Record<string, any> = {}) => get<any[]>("roster.team_members", p),
  create: (p: Record<string, any>) => post("roster.create_roster", p),
  get: (name: string) => get("roster.get_roster", { name }),
  saveCells: (name: string, cells: any[]) => post("roster.save_cells", { name, cells }),
  addEmployees: (name: string, employees: string[], prefill = "current") => post("roster.add_employees", { name, employees, prefill }),
  removeEmployee: (name: string, employee: string) => post("roster.remove_employee", { name, employee }),
  applyPattern: (p: Record<string, any>) => post("roster.apply_pattern", p),
  copyFrom: (name: string, source: string, keep_weekly_offs = 1) => post("roster.copy_from", { name, source, keep_weekly_offs }),
  markWeeklyOffs: (name: string, employees: string[] | null, overwrite = 0) => post("roster.mark_weekly_offs", { name, employees, overwrite }),
  setRequirements: (name: string, rows: any[]) => post("roster.set_requirements", { name, rows }),
  validate: (name: string) => get("roster.validate_roster", { name }),
  publish: (name: string, trim_manual = 0, backfill = 0) => post("roster.publish", { name, trim_manual, backfill }),
  archive: (name: string) => post("roster.archive", { name }),
  patterns: () => get<any[]>("roster.patterns"),
  savePattern: (p: Record<string, any>) => post("roster.save_pattern", p),
};

export const CheckinRecords = {
  team: (p: Record<string, any>) => get("checkin_records.team_checkins", p),
};

export const CompOff = {
  eligible: () => get("comp_off.eligible_days"),
  create: (p: Record<string, any>) => post<MutationResult>("comp_off.create_request", withId(p)),
  mine: () => get<any[]>("comp_off.my_requests"),
  withdraw: (name: string) => post("comp_off.withdraw", { name }),
};

export const CheckinAdmin = {
  overview: () => get("checkin_admin.get_overview"),
  savePolicy: (values: Record<string, any>) => post("checkin_admin.save_policy", { values }),
  locations: () => get("checkin_admin.list_locations"),
  saveLocation: (p: Record<string, any>) => post("checkin_admin.save_location", p),
  overrides: (q?: string) => get<any[]>("checkin_admin.list_overrides", { q }),
  saveOverride: (p: Record<string, any>) => post("checkin_admin.save_override", p),
  removeOverride: (employee: string) => post("checkin_admin.remove_override", { employee }),
  resolveFor: (employee: string) => get("checkin_admin.resolve_for", { employee }),
  logs: (p: Record<string, any>) => get("checkin_admin.logs", p),
  logDetail: (name: string) => get("checkin_admin.log_detail", { name }),
};

export const Leave = {
  overview: () => get("leave.get_overview"),
  preview: (p: Record<string, any>) => get("leave.preview", p),
  create: (p: Record<string, any>, cid?: string) => post<MutationResult>("leave.create_request", { client_request_id: cid || requestId(), ...p }),
  list: (status?: string) => get<any[]>("leave.my_requests", { status, limit: 50 }),
  withdraw: (name: string) => post("leave.withdraw_request", { name }),
  calendar: (year: number, month: number, include_team = 0) => get("leave.get_calendar", { year, month, include_team }),
};

export const Payroll = {
  list: (year?: number) => get("payroll.list_payslips", { year }),
  detail: (name: string) => get("payroll.get_payslip", { name }),
  benefits: () => get("payroll.get_benefits"),
};

export const Expenses = {
  overview: () => get("expenses.overview"),
  create: (p: Record<string, any>) => post<MutationResult>("expenses.create_claim", withId(p)),
  detail: (name: string) => get("expenses.claim_detail", { name }),
  advance: (p: Record<string, any>) => post<MutationResult>("expenses.request_advance", withId(p)),
};

export const Profile = {
  get: () => get("profile.get_profile"),
  requestChange: (p: Record<string, any>) => post<MutationResult>("profile.request_change", withId(p)),
  saveDocument: (p: Record<string, any>) => post<MutationResult>("profile.save_employee_document", withId(p)),
};

export const Approvals = {
  pending: () => get("approvals.get_pending"),
  detail: (doctype: string, name: string) => get("approvals.get_detail", { doctype, name }),
  act: (doctype: string, name: string, action: "approve" | "reject", comment?: string) =>
    post("approvals.act", withId({ doctype, name, action, comment })),
  bulk: (items: { doctype: string; name: string }[], action: string, comment?: string) =>
    post("approvals.bulk_act", { items, action, comment }),
  history: () => get<any[]>("approvals.history"),
  delegations: () => get<any[]>("approvals.list_delegations"),
  saveDelegation: (p: Record<string, any>) => post("approvals.save_delegation", withId(p)),
  revokeDelegation: (name: string) => post("approvals.revoke_delegation", { name }),
  colleagues: (txt: string) => get<any[]>("approvals.search_colleagues", { txt }),
};

export const Team = {
  overview: () => get("team.get_overview"),
  exceptions: (days = 7) => get("team.get_exceptions", { days }),
  member: (employee: string) => get("team.get_member", { employee }),
};

export const Helpdesk = {
  categories: () => get<any[]>("helpdesk.categories"),
  mine: (status?: string) => get<any[]>("helpdesk.my_tickets", { status }),
  create: (p: Record<string, any>, cid?: string) => post<MutationResult>("helpdesk.create_ticket", { client_request_id: cid || requestId(), ...p }),
  ticket: (name: string) => get("helpdesk.get_ticket", { name }),
  reply: (name: string, comment: string, internal = 0, attachments: string[] = []) =>
    post("helpdesk.reply", withId({ name, comment, internal, attachments })),
  reopen: (name: string, reason: string) => post("helpdesk.reopen", { name, reason }),
  rate: (name: string, rating: number, comment?: string) => post("helpdesk.rate", { name, rating, comment }),
  close: (name: string) => post("helpdesk.close", { name }),
  queue: (p: Record<string, any>) => get("helpdesk.queue", p),
  assign: (name: string, user: string) => post("helpdesk.assign", { name, user }),
  setStatus: (name: string, status: string, note?: string) => post("helpdesk.set_status", { name, status, note }),
  setPriority: (name: string, priority: string) => post("helpdesk.set_priority", { name, priority }),
  agents: () => get<any[]>("helpdesk.agents"),
  canned: (category?: string) => get<any[]>("helpdesk.canned_responses", { category }),
  faqs: (q?: string) => get<any[]>("helpdesk.faqs", { q }),
};

export const Documents = {
  overview: () => get("documents.overview"),
  request: (p: Record<string, any>) => post<MutationResult>("documents.request", withId(p)),
  cancel: (name: string) => post("documents.cancel_request", { name }),
  admin: (status?: string) => get("documents.admin_requests", { status }),
  regenerate: (name: string) => post("documents.regenerate", { name }),
};

export const Policies = {
  get: (name: string) => get("policies.get_policy", { name }),
  acknowledge: (name: string) => post("policies.acknowledge", { name }),
};

export const Announcements = {
  list: () => get<any[]>("announcements.list_announcements"),
  read: (name: string) => post("announcements.mark_read", { name }),
  adminList: () => get<any[]>("announcements.admin_list"),
  save: (p: Record<string, any>) => post("announcements.save_announcement", p),
};

export const Recognition = {
  feed: (scope = "all", offset = 0) => get<any[]>("recognition.feed", { scope, offset, limit: 20 }),
  summary: () => get("recognition.summary"),
  give: (p: Record<string, any>, cid?: string) => post<MutationResult>("recognition.give", { client_request_id: cid || requestId(), ...p }),
  react: (name: string, reaction: string) => post("recognition.react", { name, reaction }),
  team: () => get("recognition.team_summary"),
  moderation: () => get<any[]>("recognition.moderation_queue"),
  moderate: (name: string, action: string) => post("recognition.moderate", { name, action }),
};

export const Analytics = {
  employee: () => get("analytics.employee"),
  manager: () => get("analytics.manager"),
  hr: () => get("analytics.hr"),
};

export const Assistant = {
  ask: (message: string, conversation_id?: string | null, lang = "en") =>
    post<AssistantReply>("assistant.ask", { message, conversation_id, lang }),
  confirm: (token: string) => post<MutationResult>("assistant.confirm_action", { token }),
  feedback: (conversation_id: string, helpful: boolean) => post("assistant.feedback", { conversation_id, helpful: helpful ? 1 : 0 }),
  suggestions: () => get<string[]>("assistant.suggestions"),
};

export const Notifications = {
  list: (unread_only = 0) => get<any[]>("notifications.list_notifications", { unread_only }),
  markRead: (names?: string[], all = 0) => post<{ unread: number }>("notifications.mark_read", { names, all }),
  prefs: () => get("notifications.get_preferences"),
  setPref: (event_type: string, channel: string, enabled: boolean) =>
    post("notifications.set_preference", { event_type, channel, enabled: enabled ? 1 : 0 }),
  subscribe: (subscription: any) => post("notifications.push_subscribe", { subscription }),
};

export const Goals = {
  overview: () => get("goals.overview"),
  progress: (name: string, progress: number) => post("goals.update_goal_progress", withId({ name, progress })),
};

export const HR = {
  search: (q?: string, department?: string) => get<any[]>("hr_admin.employee_search", { q, department }),
  employee: (employee: string) => get("hr_admin.employee_detail", { employee }),
  verifyDocument: (name: string, verified = 1) => post("hr_admin.verify_document", { name, verified }),
  expiring: (days = 60) => get<any[]>("hr_admin.expiring_documents", { days }),
  settings: () => get("hr_admin.get_settings"),
  saveSettings: (values: Record<string, any>, ai_api_key?: string) => post("hr_admin.save_settings", { values, ai_api_key }),
  saveKnowledge: (p: Record<string, any>) => post("hr_admin.save_knowledge_source", p),
  audit: (event_type?: string) => get<any[]>("hr_admin.audit_events", { event_type }),
  aiQuality: () => get("hr_admin.ai_quality"),
};
