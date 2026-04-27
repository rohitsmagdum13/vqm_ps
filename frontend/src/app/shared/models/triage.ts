export type TriageStatus = 'PENDING_REVIEW' | 'IN_REVIEW' | 'COMPLETED';

/**
 * Per-dimension scores produced by the triage node
 * (src/orchestration/nodes/triage.py::_build_confidence_breakdown).
 * Keys match the backend exactly so we render real production data.
 */
export interface ConfidenceBreakdown {
  readonly overall: number;
  readonly intent_classification: number;
  readonly entity_extraction: number;
  readonly single_issue_detection: number;
  readonly threshold: number;
}

/**
 * Vendor display object. Only `vendor_id` is guaranteed — the richer
 * fields are filled in only when we have the vendor cached or fetched
 * from /vendors/{id}. Components must handle nulls gracefully.
 */
export interface TriageVendor {
  readonly vendor_id: string;
  readonly company_name?: string | null;
  readonly tier?: 'Platinum' | 'Gold' | 'Silver' | 'Bronze' | null;
  readonly primary_contact?: string | null;
  readonly account_manager?: string | null;
  readonly annual_spend_usd?: number | null;
  readonly industry?: string | null;
}

export interface TriageCase {
  readonly query_id: string;
  readonly received_at: string;
  readonly subject: string;
  readonly body: string;
  readonly vendor: TriageVendor;
  readonly status: TriageStatus;

  readonly ai_intent: string;
  readonly ai_suggested_category: string;
  readonly ai_urgency: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  readonly ai_sentiment: 'POSITIVE' | 'NEUTRAL' | 'NEGATIVE' | 'FRUSTRATED' | 'positive' | 'neutral' | 'frustrated' | 'angry';
  readonly ai_extracted_entities: Readonly<Record<string, unknown>>;
  readonly ai_confidence: number;
  readonly ai_confidence_breakdown: ConfidenceBreakdown;
  readonly ai_low_confidence_reasons: readonly string[];
  readonly ai_multi_issue_detected: boolean;
}

export interface ReviewerDecision {
  readonly query_id: string;
  readonly corrected_intent: string;
  readonly corrected_category: string;
  readonly assigned_team: 'AP-FINANCE' | 'PROCUREMENT' | 'LOGISTICS' | 'COMPLIANCE' | 'TECH-SUPPORT';
  readonly notes: string;
}

export type CopilotMessageRole = 'reviewer' | 'agent_thought' | 'tool_call' | 'tool_result' | 'agent_final';

export interface CopilotMessage {
  readonly id: string;
  readonly role: CopilotMessageRole;
  readonly content: string;
  readonly tool_name?: string;
  readonly tool_args?: Readonly<Record<string, unknown>>;
  readonly timestamp: string;
}
