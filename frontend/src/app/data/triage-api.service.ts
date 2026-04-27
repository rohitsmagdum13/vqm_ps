import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

/** Shape returned by GET /triage/queue (one entry per pending package). */
export interface TriageQueueItemDto {
  readonly query_id: string;
  readonly correlation_id: string;
  readonly original_confidence: number;
  readonly suggested_category: string | null;
  readonly status: string;
  readonly created_at: string;
  // Surfaced from package_data JSONB so the queue can render real
  // values without per-row /triage/{id} fetches.
  readonly subject: string | null;
  readonly vendor_id: string | null;
  readonly ai_intent: string | null;
}

export interface TriageQueueResponse {
  readonly packages: readonly TriageQueueItemDto[];
}

/** Backend AnalysisResult subset we render. */
export interface AnalysisResultDto {
  readonly intent_classification: string;
  readonly extracted_entities: Readonly<Record<string, unknown>>;
  readonly urgency_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  readonly sentiment: 'POSITIVE' | 'NEUTRAL' | 'NEGATIVE' | 'FRUSTRATED';
  readonly confidence_score: number;
  readonly multi_issue_detected: boolean;
  readonly suggested_category: string;
}

/** Subset of UnifiedQueryPayload the package_data carries. */
export interface OriginalQueryDto {
  readonly query_id: string;
  readonly source: string;
  readonly subject: string;
  readonly body: string;
  readonly vendor_id: string | null;
  readonly received_at?: string;
}

/** Per-dimension confidence breakdown produced by the triage node. */
export interface ConfidenceBreakdownDto {
  readonly overall: number;
  readonly intent_classification: number;
  readonly entity_extraction: number;
  readonly single_issue_detection: number;
  readonly threshold: number;
}

export interface TriagePackageDto {
  readonly query_id: string;
  readonly correlation_id: string;
  readonly callback_token: string;
  readonly original_query: OriginalQueryDto;
  readonly analysis_result: AnalysisResultDto;
  readonly confidence_breakdown: ConfidenceBreakdownDto;
  readonly suggested_routing: Record<string, unknown> | null;
  readonly suggested_draft: Record<string, unknown> | null;
  readonly created_at: string;
}

@Injectable({ providedIn: 'root' })
export class TriageApiService {
  readonly #http = inject(HttpClient);
  readonly #base = `${environment.apiBaseUrl}/triage`;

  /** GET /triage/queue → list of pending packages (oldest first). */
  listQueue(limit = 50): Observable<TriageQueueResponse> {
    return this.#http.get<TriageQueueResponse>(`${this.#base}/queue`, {
      params: { limit: String(limit) },
    });
  }

  /** GET /triage/{query_id} → full TriagePackage as persisted. */
  getPackage(queryId: string): Observable<TriagePackageDto> {
    return this.#http.get<TriagePackageDto>(
      `${this.#base}/${encodeURIComponent(queryId)}`,
    );
  }
}
