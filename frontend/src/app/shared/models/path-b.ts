import type { CopilotMessage, TriageVendor } from './triage';

export type InvestigationTeam =
  | 'AP-FINANCE'
  | 'PROCUREMENT'
  | 'LOGISTICS'
  | 'COMPLIANCE'
  | 'TECH-SUPPORT';

export type TicketStatus = 'OPEN' | 'IN_PROGRESS' | 'PENDING_VENDOR' | 'RESOLVED';

export type TicketPriority = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

export interface PathBTicket {
  readonly ticket_id: string;
  readonly query_id: string;
  readonly subject: string;
  readonly body: string;
  readonly vendor: TriageVendor;
  readonly status: TicketStatus;
  readonly priority: TicketPriority;
  readonly team: InvestigationTeam;
  readonly category: string;
  readonly ai_intent: string;
  readonly opened_at: string;
  readonly sla_target_hours: number;
  readonly sla_elapsed_hours: number;
  readonly acknowledgment_sent_at: string;
  readonly acknowledgment_excerpt: string;
  readonly related_invoices: readonly string[];
  readonly related_pos: readonly string[];
  readonly resolution_notes: string;
}

export interface ResolutionSubmission {
  readonly ticket_id: string;
  readonly resolution_notes: string;
  readonly resolved_at: string;
}

export type { CopilotMessage };
