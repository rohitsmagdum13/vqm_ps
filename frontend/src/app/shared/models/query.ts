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
  readonly agent: string;
  readonly tl: readonly TimelineStep[];
  readonly ai: string;
  readonly msgs: readonly QueryMessage[];
}
