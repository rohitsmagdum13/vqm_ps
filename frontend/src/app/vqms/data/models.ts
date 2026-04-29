export type TierName = 'PLATINUM' | 'GOLD' | 'SILVER' | 'BRONZE';
export type ProcessingPath = 'A' | 'B' | 'C';
export type Priority = 'P1' | 'P2' | 'P3';

export interface Vendor {
  readonly vendor_id: string;
  readonly name: string;
  readonly website: string;
  readonly tier: TierName;
  readonly category: string;
  readonly payment_terms: string;
  readonly annual_revenue: number;
  readonly sla_response_hours: number;
  readonly sla_resolution_days: number;
  readonly status: string;
  readonly city: string;
  readonly state: string;
  readonly country: string;
  readonly onboarded_date: string;
  readonly health: number;
  readonly open_queries: number;
  readonly p1_open: number;
}

export interface Contact {
  readonly name: string;
  readonly role: string;
  readonly email: string;
  readonly phone: string;
}

export interface Contract {
  readonly id: string;
  readonly title: string;
  readonly value: number;
  readonly currency: string;
  readonly start: string;
  readonly end: string;
  readonly status: string;
}

export interface Query {
  readonly query_id: string;
  readonly correlation_id: string;
  readonly execution_id: string;
  readonly source: 'email' | 'portal';
  readonly subject: string;
  readonly vendor_id: string;
  readonly vendor_name: string;
  readonly vendor_tier: TierName;
  readonly priority: Priority;
  readonly status: string;
  readonly processing_path: ProcessingPath;
  readonly assigned_team: string;
  readonly intent: string;
  readonly confidence: number;
  readonly kb_match: number;
  readonly received_at: string;
  readonly sla_pct: number | null;
  readonly sla_deadline_min: number | null;
  readonly attachments: number;
  readonly ticket_id: string | null;
  readonly reopened: boolean;
}

export interface VolumeRow {
  readonly date: string;
  readonly A: number;
  readonly B: number;
  readonly C: number;
  readonly received: number;
}

export interface HourlyRow {
  readonly hour: string;
  readonly ingested: number;
  readonly resolved: number;
}

export interface ConfidenceBand {
  readonly band: string;
  readonly n: number;
}

export interface TeamSla {
  readonly team: string;
  readonly on_time: number;
  readonly breached: number;
}

export interface IntentBucket {
  readonly intent: string;
  readonly n: number;
}

export interface KbArticle {
  readonly id: string;
  readonly title: string;
  readonly last_updated: string;
  readonly uses_30d: number;
  readonly hit_rate: number;
}

export interface Integration {
  readonly name: string;
  readonly kind: string;
  readonly status: 'healthy' | 'degraded' | 'down' | 'standby';
  readonly latency_ms: number | null;
  readonly region: string;
  readonly note: string;
}

export interface Queue {
  readonly name: string;
  readonly visible: number;
  readonly in_flight: number;
  readonly dlq: number;
  readonly oldest_age_s: number;
  readonly throughput_1m: number;
}

export interface PipelineStage {
  readonly stage: string;
  readonly in: number;
  readonly out: number;
  readonly errors: number;
  readonly median_ms: number;
}

export interface AuditEntry {
  readonly ts: string;
  readonly actor: string;
  readonly action: string;
  readonly target: string;
  readonly note: string;
}

export interface UserRow {
  readonly email: string;
  readonly name: string;
  readonly role: 'Admin' | 'Reviewer' | 'Vendor';
  readonly last_active: string;
  readonly status: 'online' | 'away' | 'offline';
}

export interface FeatureFlag {
  readonly key: string;
  readonly on: boolean;
  readonly scope: string;
  readonly changed: string;
}

export interface ThreadMessage {
  readonly direction: 'inbound' | 'outbound' | 'system';
  readonly from?: string;
  readonly to?: string;
  readonly ts: string;
  readonly subject?: string;
  readonly body?: string;
  readonly note?: string;
  readonly attachments?: readonly { name: string; size: string }[];
}

export interface SourceUsed {
  readonly kb_id: string;
  readonly title: string;
  readonly cosine: number;
}
