/**
 * Timeline event surfaced by GET /queries/:id.trail.
 *
 * One row per pipeline step (intake → context_loading → query_analysis →
 * confidence_check → routing → kb_search → path_decision →
 * resolution|acknowledgment → quality_gate → delivery), per LLM sub-call,
 * and per admin / closure milestone. The Angular query-detail page
 * orders these by created_at and renders a live timeline.
 */

export type TrailStatus = 'success' | 'failed' | 'skipped' | string;

export interface TrailDetails {
  readonly case_status?: string;
  readonly processing_path?: string;
  readonly intent?: string;
  readonly urgency?: string;
  readonly sentiment?: string;
  readonly confidence_score?: number;
  readonly assigned_team?: string;
  readonly priority?: string;
  readonly sla_hours?: number;
  readonly total_matches?: number;
  readonly above_threshold?: number;
  readonly best_score?: number | null;
  readonly draft_type?: string;
  readonly draft_confidence?: number;
  readonly sources_count?: number;
  readonly checks_passed?: number;
  readonly failed_checks?: readonly string[];
  readonly ticket_id?: string;
  readonly vendor_id?: string;
  readonly interactions_loaded?: number;
  // LLM call sub-step (admin only)
  readonly tokens_in?: number;
  readonly tokens_out?: number;
  readonly cost_usd?: number;
  readonly model_id?: string;
  // Failure path
  readonly error_type?: string;
  readonly error?: string;
  // Free-form
  readonly [key: string]: unknown;
}

export interface TimelineEvent {
  readonly id: number;
  readonly query_id: string;
  readonly correlation_id: string;
  readonly step_name: string;
  readonly action: string;
  readonly status: TrailStatus;
  readonly details: TrailDetails;
  readonly duration_ms: number | null;
  readonly created_at: string;
  readonly actor: string;
}
