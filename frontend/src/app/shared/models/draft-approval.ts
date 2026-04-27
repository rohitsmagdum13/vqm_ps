/**
 * Models for the admin draft-approval queue.
 *
 * Path A queries park at status PENDING_APPROVAL after the Delivery node
 * has created the ServiceNow ticket and stamped the real INC number into
 * the draft. The admin queue lists those cases (DraftApprovalListItem)
 * and the detail view (DraftApprovalDetail) shows the full draft + AI
 * analysis so an admin can approve, edit-and-approve, or reject.
 */

export type DraftStatus = 'PENDING_APPROVAL' | 'RESOLVED' | 'DRAFT_REJECTED';

/** One row in the pending-approval queue. */
export interface DraftApprovalListItem {
  readonly query_id: string;
  readonly vendor_id: string | null;
  readonly subject: string | null;
  readonly source: string | null;
  readonly processing_path: string | null;
  readonly ticket_id: string | null;
  readonly intent: string | null;
  readonly confidence: number | null;
  readonly drafted_at: string;
  readonly created_at: string;
}

export interface DraftApprovalListResponse {
  readonly drafts: readonly DraftApprovalListItem[];
}

/** AI analysis snapshot — same shape used by the triage UI. */
export interface DraftAnalysis {
  readonly intent_classification?: string;
  readonly extracted_entities?: Readonly<Record<string, unknown>>;
  readonly urgency_level?: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  readonly sentiment?: string;
  readonly confidence_score?: number;
  readonly suggested_category?: string;
  readonly multi_issue_detected?: boolean;
}

/** Routing decision snapshot (assigned team, SLA, priority). */
export interface DraftRouting {
  readonly assigned_team?: string;
  readonly category?: string;
  readonly priority?: string;
  readonly sla_target?: { readonly total_hours?: number };
}

/**
 * The drafted email itself. ``_recipient_email`` and
 * ``_reply_to_message_id`` are stripped server-side before this hits the
 * UI, so this type does NOT include them.
 */
export interface DraftEmail {
  readonly draft_type?: 'RESOLUTION' | 'ACKNOWLEDGMENT' | string;
  readonly subject?: string;
  readonly body?: string;
  readonly confidence?: number;
  readonly sources?: readonly string[];
  readonly model_id?: string;
  readonly tokens_in?: number;
  readonly tokens_out?: number;
}

export interface DraftApprovalDetail {
  readonly query_id: string;
  readonly vendor_id: string | null;
  readonly source: string | null;
  readonly processing_path: string | null;
  readonly status: DraftStatus | string;
  readonly subject: string | null;
  readonly original_body: string | null;
  readonly ticket_id: string | null;
  readonly analysis: DraftAnalysis | null;
  readonly routing: DraftRouting | null;
  readonly draft: DraftEmail;
  readonly created_at: string;
  readonly drafted_at: string;
}

export interface ApproveResult {
  readonly query_id: string;
  readonly ticket_id: string | null;
  readonly recipient: string;
  readonly status: string;
}

export interface RejectResult {
  readonly query_id: string;
  readonly status: string;
}
