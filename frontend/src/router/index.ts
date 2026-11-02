import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import { useSession } from "@/stores/session";

/**
 * meta.cap   -> capability required (pipe = any of). UI gating only; every API enforces its own scope.
 * meta.module-> portal module that must be enabled.
 */
const routes: RouteRecordRaw[] = [
  { path: "/", name: "dashboard", component: () => import("@/pages/DashboardPage.vue"), meta: { title: "Home" } },
  { path: "/inbox", name: "inbox", component: () => import("@/pages/InboxPage.vue"), meta: { title: "Inbox" } },
  { path: "/notifications", name: "notifications", component: () => import("@/pages/NotificationsPage.vue"), meta: { title: "Notifications" } },
  { path: "/settings", name: "settings", component: () => import("@/pages/MySettingsPage.vue"), meta: { title: "Settings" } },

  { path: "/attendance", name: "attendance", component: () => import("@/pages/attendance/AttendancePage.vue"), meta: { title: "Attendance", module: "attendance" } },
  { path: "/attendance/check-in", name: "checkin", component: () => import("@/pages/attendance/CheckInPage.vue"), meta: { title: "Check in", module: "attendance" } },
  { path: "/attendance/checkins", name: "my-checkins", component: () => import("@/pages/attendance/MyCheckinsPage.vue"), meta: { title: "Check-in records", module: "attendance" } },
  { path: "/leave/comp-off", name: "comp-off", component: () => import("@/pages/leave/CompOffPage.vue"), meta: { title: "Compensatory leave", module: "comp_off" } },
  { path: "/roster", name: "my-roster", component: () => import("@/pages/roster/MyRosterPage.vue"), meta: { title: "My roster", module: "roster" } },
  { path: "/holidays", name: "holidays", component: () => import("@/pages/HolidaysPage.vue"), meta: { title: "Holidays" } },
  { path: "/attendance/corrections", name: "corrections", component: () => import("@/pages/attendance/CorrectionsPage.vue"), meta: { title: "Corrections", module: "attendance" } },

  { path: "/leave", name: "leave", component: () => import("@/pages/leave/LeaveOverviewPage.vue"), meta: { title: "Leave", module: "leave" } },
  { path: "/leave/calendar", name: "leave-calendar", component: () => import("@/pages/leave/LeaveCalendarPage.vue"), meta: { title: "Leave calendar", module: "leave" } },
  { path: "/leave/apply", name: "leave-apply", component: () => import("@/pages/leave/ApplyLeavePage.vue"), meta: { title: "Apply for leave", module: "leave" } },

  { path: "/finances/payslips", name: "payslips", component: () => import("@/pages/finances/PayslipsPage.vue"), meta: { title: "Payslips", module: "payroll" } },
  { path: "/finances/payslips/:name", name: "payslip", component: () => import("@/pages/finances/PayslipDetailPage.vue"), meta: { title: "Payslips", module: "payroll" } },
  { path: "/finances/expenses", name: "expenses", component: () => import("@/pages/finances/ExpensesPage.vue"), meta: { title: "Expenses", module: "expenses" } },
  { path: "/finances/expenses/new", name: "expense-new", component: () => import("@/pages/finances/NewExpensePage.vue"), meta: { title: "New claim", module: "expenses" } },

  { path: "/documents", name: "documents", component: () => import("@/pages/DocumentsPage.vue"), meta: { title: "Documents", module: "documents" } },
  { path: "/profile", name: "profile", component: () => import("@/pages/ProfilePage.vue"), meta: { title: "My profile" } },
  { path: "/goals", name: "goals", component: () => import("@/pages/GoalsPage.vue"), meta: { title: "Goals & learning", module: "goals" } },
  { path: "/recognition", name: "recognition", component: () => import("@/pages/RecognitionPage.vue"), meta: { title: "Recognition", module: "recognition" } },
  { path: "/insights", name: "my-insights", component: () => import("@/pages/MyInsightsPage.vue"), meta: { title: "My insights", module: "analytics" } },

  { path: "/support", name: "support", component: () => import("@/pages/support/SupportPage.vue"), meta: { title: "HR helpdesk", module: "helpdesk" } },
  { path: "/support/new", name: "support-new", component: () => import("@/pages/support/NewTicketPage.vue"), meta: { title: "New ticket", module: "helpdesk" } },
  { path: "/support/:name", name: "ticket", component: () => import("@/pages/support/TicketPage.vue"), meta: { title: "HR helpdesk", module: "helpdesk" } },
  { path: "/assistant", name: "assistant", component: () => import("@/pages/AssistantPage.vue"), meta: { title: "HR assistant", module: "assistant" } },

  { path: "/team", name: "team", component: () => import("@/pages/team/TeamPage.vue"), meta: { title: "Team overview", cap: "manager|hr" } },
  { path: "/team/approvals", name: "approvals", component: () => import("@/pages/team/ApprovalsPage.vue"), meta: { title: "Approvals", cap: "manager|hr" } },
  { path: "/team/calendar", name: "team-calendar", component: () => import("@/pages/leave/LeaveCalendarPage.vue"), props: { team: true }, meta: { title: "Leave calendar", cap: "manager" } },
  { path: "/team/analytics", name: "team-analytics", component: () => import("@/pages/team/TeamAnalyticsPage.vue"), meta: { title: "Team analytics", cap: "manager", module: "analytics" } },
  { path: "/team/checkins", name: "team-checkins", component: () => import("@/pages/team/TeamCheckinsPage.vue"), meta: { title: "Team check-ins", cap: "team_checkins", module: "attendance" } },
  { path: "/team/roster", name: "rosters", component: () => import("@/pages/team/RosterListPage.vue"), meta: { title: "Roster planner", cap: "planner", module: "roster" } },
  { path: "/team/roster/:name", name: "roster-planner", component: () => import("@/pages/team/RosterPlannerPage.vue"), meta: { title: "Roster planner", cap: "planner", module: "roster" } },
  { path: "/team/member/:employee", name: "team-member", component: () => import("@/pages/team/TeamMemberPage.vue"), meta: { title: "Team overview", cap: "manager|hr" } },

  { path: "/hr/tickets", name: "hr-tickets", component: () => import("@/pages/hr/ServiceDeskPage.vue"), meta: { title: "Service desk", cap: "agent", module: "helpdesk" } },
  { path: "/hr/tickets/:name", name: "hr-ticket", component: () => import("@/pages/support/TicketPage.vue"), meta: { title: "Service desk", cap: "agent", module: "helpdesk" } },
  { path: "/hr/employees", name: "hr-employees", component: () => import("@/pages/hr/EmployeesPage.vue"), meta: { title: "Employees", cap: "hr" } },
  { path: "/hr/documents", name: "hr-documents", component: () => import("@/pages/hr/DocumentAdminPage.vue"), meta: { title: "Document admin", cap: "hr", module: "documents" } },
  { path: "/hr/checkin", name: "hr-checkin", component: () => import("@/pages/hr/CheckinControlPage.vue"), meta: { title: "Check-in control", cap: "hr" } },
  { path: "/hr/checkin-log", name: "hr-checkin-log", component: () => import("@/pages/hr/CheckinLogPage.vue"), meta: { title: "Check-in audit", cap: "hr" } },
  { path: "/hr/announcements", name: "hr-announcements", component: () => import("@/pages/hr/AnnouncementsAdminPage.vue"), meta: { title: "Announcements", cap: "hr" } },
  { path: "/hr/analytics", name: "hr-analytics", component: () => import("@/pages/hr/HrAnalyticsPage.vue"), meta: { title: "HR analytics", cap: "hr", module: "analytics" } },
  { path: "/hr/settings", name: "hr-settings", component: () => import("@/pages/hr/PortalSettingsPage.vue"), meta: { title: "Portal settings", cap: "admin" } },

  { path: "/forbidden", name: "forbidden", component: () => import("@/pages/StatusPage.vue"), props: { kind: "forbidden" } },
  { path: "/:pathMatch(.*)*", name: "notfound", component: () => import("@/pages/StatusPage.vue"), props: { kind: "notfound" } },
];

export const router = createRouter({
  history: createWebHistory("/ess"),
  routes,
  scrollBehavior: (_to, _from, saved) => saved || { top: 0 },
});

router.beforeEach((to) => {
  const s = useSession();
  const cap = to.meta.cap as string | undefined;
  const mod = to.meta.module as string | undefined;
  if (cap && !s.can(cap)) return { name: "forbidden" };
  if (mod && !s.module(mod)) return { name: "forbidden" };
  if (!s.employee && !cap && !["forbidden", "notfound", "notifications", "settings"].includes(String(to.name))) {
    // Users without an employee record (e.g. pure HR agents) land on their workspace.
    if (s.can("agent")) return { name: "hr-tickets" };
    if (s.can("hr")) return { name: "hr-employees" };
  }
  return true;
});

router.afterEach((to) => {
  const s = useSession();
  const title = (to.meta.title as string) || "";
  document.title = `${title ? `${title} – ` : ""}${s.settings.portal_title || "thinkNXG ESS Portal"}`;
});
