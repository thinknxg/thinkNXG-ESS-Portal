export type Lang = "en" | "ar";

export interface Capabilities {
  employee: boolean;
  manager: boolean;
  hr: boolean;
  hr_manager: boolean;
  agent: boolean;
  payroll_officer: boolean;
  admin: boolean;
  planner?: boolean;
  team_checkins?: boolean;
  modules: Record<string, boolean>;
}

export interface Boot {
  user: { name: string; full_name: string; image?: string | null; email: string; desk_access?: boolean };
  employee: null | {
    name: string; employee_name: string; first_name?: string; designation?: string; department?: string;
    company?: string; branch?: string; image?: string | null; date_of_joining?: string;
  };
  capabilities: Capabilities;
  settings: Record<string, any>;
  lang: Lang;
  server_date: string;
  unread: number;
}

export interface InboxItem {
  id: string; type: string; title: string; status: string; due_date: string | null;
  route: string; reference?: string; priority: "high" | "normal" | "low"; meta?: Record<string, any>;
}

export interface LeaveBalance {
  leave_type: string; allocated: number; taken: number; pending: number; expired: number; remaining: number;
}

export interface ApprovalItem {
  id: string; doctype: string; name: string; type: string; title: string; employee: string;
  employee_name: string; submitted_on: string; age_days: number; details: Record<string, any>;
  delegated_from?: string | null;
}

export interface Ticket {
  name: string; subject: string; category: string; priority: string; status: string; sla_status: string;
  employee_name?: string; assigned_to?: string; resolution_due?: string; creation: string; modified?: string;
  rating?: number; is_confidential?: number; escalation_level?: number;
}

export interface Citation { source: string; title: string; section?: string; snippet?: string }
export interface Proposal { type: "leave_request" | "hr_ticket"; token: string; payload: Record<string, any>; preview?: any }
export interface AssistantReply {
  conversation_id: string; answer: string; citations: Citation[]; proposal: Proposal | null;
  outcome: string; notice?: string;
}

export interface MutationResult { doctype?: string; name?: string; duplicate?: boolean; [k: string]: any }
