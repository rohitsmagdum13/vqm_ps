export type QueryStatus =
  | 'Open'
  | 'In Progress'
  | 'Awaiting Vendor'
  | 'Resolved'
  | 'Breached';

export type Priority = 'Low' | 'Medium' | 'High' | 'Critical';

export type SlaClass = 'sla-ok' | 'sla-brch';

export interface TimelineStep {
  readonly c: string;
  readonly t: string;
  readonly ts: string;
  readonly p?: boolean;
}

export type MessageAuthor = 'vendor' | 'us' | 'ai';

export interface QueryMessage {
  readonly f: MessageAuthor;
  readonly t: string;
  readonly ts: string;
}

export interface Query {
  readonly id: string;
  readonly subj: string;
  readonly type: string;
  readonly pri: Priority;
  readonly status: QueryStatus;
  readonly submitted: string;
  readonly sla: string;
  readonly slaCls: SlaClass;
  /** "Email" | "Portal" — display label derived from backend `source`. */
  readonly agent: string;
  /** Vendor that submitted the query. Null on email-path queries that
   *  failed Salesforce resolution. Used by admin views; vendors don't
   *  see this column on their own list. Optional so legacy seed/test
   *  fixtures that pre-date this field still type-check. */
  readonly vendor?: string | null;
  readonly tl: readonly TimelineStep[];
  readonly ai: string;
  readonly msgs: readonly QueryMessage[];
}
