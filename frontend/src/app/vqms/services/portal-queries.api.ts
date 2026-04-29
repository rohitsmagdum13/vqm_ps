import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

/**
 * Backend `QueryType` literal. Matches `models/query.py:QUERY_TYPES` —
 * any value sent must be one of these or the backend rejects with 422.
 */
export type BackendQueryType =
  | 'RETURN_REFUND'
  | 'GENERAL_INQUIRY'
  | 'CATALOG_PRICING'
  | 'CONTRACT_QUERY'
  | 'PURCHASE_ORDER'
  | 'SLA_BREACH_REPORT'
  | 'DELIVERY_SHIPMENT'
  | 'INVOICE_PAYMENT'
  | 'COMPLIANCE_AUDIT'
  | 'TECHNICAL_SUPPORT'
  | 'ONBOARDING'
  | 'QUALITY_ISSUE';

export type BackendPriority = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

export interface QuerySubmissionDto {
  readonly query_type: BackendQueryType;
  readonly subject: string;
  readonly description: string;
  readonly priority: BackendPriority;
  readonly reference_number: string | null;
}

/** Same row shape as `/admin/queries` — see queries.api.ts for fields. */
export interface VendorQueryDto {
  readonly query_id: string;
  readonly subject: string | null;
  readonly query_type: string | null;
  readonly status: string;
  readonly priority: string | null;
  readonly source: string;
  readonly processing_path: string | null;
  readonly reference_number: string | null;
  readonly vendor_id: string | null;
  readonly sla_deadline: string | null;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface VendorQueriesListResponse {
  readonly queries: readonly VendorQueryDto[];
}

export interface VendorQueryDetailDto extends VendorQueryDto {
  readonly description: string | null;
}

export interface AttachmentResultDto {
  readonly attachment_id: string;
  readonly filename: string;
  readonly size_bytes: number;
  readonly extraction_status: string;
  readonly extraction_method: string;
}

export interface SubmitQueryResponseDto {
  readonly query_id: string;
  readonly status: string;
  readonly created_at: string;
  readonly attachments: readonly AttachmentResultDto[];
  readonly extracted_entities: Readonly<Record<string, unknown>>;
}

export interface TrailResponse {
  readonly events: readonly Readonly<Record<string, unknown>>[];
}

@Injectable({ providedIn: 'root' })
export class PortalQueriesApi {
  readonly #http = inject(HttpClient);
  readonly #baseUrl = environment.apiBaseUrl;

  list(): Observable<VendorQueriesListResponse> {
    return this.#http.get<VendorQueriesListResponse>(`${this.#baseUrl}/queries`);
  }

  get(queryId: string): Observable<VendorQueryDetailDto> {
    return this.#http.get<VendorQueryDetailDto>(
      `${this.#baseUrl}/queries/${encodeURIComponent(queryId)}`,
    );
  }

  getTrail(queryId: string): Observable<TrailResponse> {
    return this.#http.get<TrailResponse>(
      `${this.#baseUrl}/queries/${encodeURIComponent(queryId)}/trail`,
    );
  }

  /**
   * Multipart submission: backend expects a `submission` form field
   * carrying JSON-encoded `QuerySubmission` plus 0..N file uploads on
   * the `files` field. Files are passed as native browser `File`
   * objects so the browser sets the `Content-Type: multipart/form-data;
   * boundary=…` header automatically.
   */
  submit(
    submission: QuerySubmissionDto,
    files: readonly File[],
  ): Observable<SubmitQueryResponseDto> {
    const fd = new FormData();
    fd.append('submission', JSON.stringify(submission));
    for (const f of files) {
      fd.append('files', f, f.name);
    }
    return this.#http.post<SubmitQueryResponseDto>(`${this.#baseUrl}/queries`, fd);
  }
}
