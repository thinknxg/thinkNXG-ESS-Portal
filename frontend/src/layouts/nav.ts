export interface NavItem { label: string; to: string; icon: string; cap?: string; module?: string; badge?: string }
export interface NavGroup { label: string; cap?: string; items: NavItem[] }

export const NAV: NavGroup[] = [
  { label: "Overview", items: [
    { label: "Home", to: "/", icon: "home" },
    { label: "Inbox", to: "/inbox", icon: "inbox", badge: "inbox" },
  ] },
  { label: "My work", items: [
    { label: "Attendance", to: "/attendance", icon: "clock", module: "attendance" },
    { label: "Check-in records", to: "/attendance/checkins", icon: "clock", module: "attendance" },
    { label: "My roster", to: "/roster", icon: "calendar", module: "roster" },
    { label: "Leave", to: "/leave", icon: "sun", module: "leave" },
    { label: "Compensatory leave", to: "/leave/comp-off", icon: "sun", module: "comp_off" },
    { label: "Holidays", to: "/holidays", icon: "calendar" },
  ] },
  { label: "My finances", items: [
    { label: "Payslips", to: "/finances/payslips", icon: "wallet", module: "payroll" },
    { label: "Expenses", to: "/finances/expenses", icon: "receipt", module: "expenses" },
  ] },
  { label: "Me", items: [
    { label: "Documents", to: "/documents", icon: "file", module: "documents" },
    { label: "My profile", to: "/profile", icon: "user" },
    { label: "Goals & learning", to: "/goals", icon: "target", module: "goals" },
    { label: "Recognition", to: "/recognition", icon: "star", module: "recognition" },
    { label: "My insights", to: "/insights", icon: "chart", module: "analytics" },
  ] },
  { label: "Help", items: [
    { label: "HR helpdesk", to: "/support", icon: "lifebuoy", module: "helpdesk" },
    { label: "HR assistant", to: "/assistant", icon: "spark", module: "assistant" },
  ] },
  { label: "Team", cap: "manager|hr|planner|team_checkins", items: [
    { label: "Team overview", to: "/team", icon: "users", cap: "manager|hr" },
    { label: "Approvals", to: "/team/approvals", icon: "check", cap: "manager|hr", badge: "approvals" },
    { label: "Roster planner", to: "/team/roster", icon: "calendar", cap: "planner", module: "roster" },
    { label: "Team check-ins", to: "/team/checkins", icon: "clock", cap: "team_checkins", module: "attendance" },
    { label: "Team analytics", to: "/team/analytics", icon: "chart", cap: "manager", module: "analytics" },
  ] },
  { label: "HR operations", cap: "hr|agent|admin", items: [
    { label: "Service desk", to: "/hr/tickets", icon: "lifebuoy", cap: "agent", module: "helpdesk" },
    { label: "Employees", to: "/hr/employees", icon: "users", cap: "hr" },
    { label: "Document admin", to: "/hr/documents", icon: "file", cap: "hr", module: "documents" },
    { label: "Check-in control", to: "/hr/checkin", icon: "pin", cap: "hr" },
    { label: "Check-in audit", to: "/hr/checkin-log", icon: "shield", cap: "hr" },
    { label: "Announcements", to: "/hr/announcements", icon: "megaphone", cap: "hr" },
    { label: "HR analytics", to: "/hr/analytics", icon: "chart", cap: "hr", module: "analytics" },
    { label: "Portal settings", to: "/hr/settings", icon: "gear", cap: "admin" },
  ] },
];
