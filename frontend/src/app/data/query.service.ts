import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import type { TimelineEvent } from '../shared/models/timeline';

export type BackendPriority = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

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

export interface QuerySubmissionPayload {
  readonly query_type: BackendQueryType;
  readonly subject: string;
  readonly description: string;
  readonly priority: BackendPriority;
  readonly reference_number?: string | null;
}

export interface QuerySubmissionResult {
  readonly query_id: string;
  readonly status: string;
  readonly created_at: string;
}

export interface QueryListItem {
  readonly query_id: string;
  readonly subject: string | null;
  readonly query_type: BackendQueryType | string | null;
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

export interface QueryDetail extends QueryListItem {
  readonly description: string | null;
  readonly vendor_id: string | null;
}

export interface QueryListResponse {
  readonly queries: readonly QueryListItem[];
}

export interface QueryTrailResponse {
  readonly events: readonly TimelineEvent[];
}

function vendorHeader(vendorId: string | null): HttpHeaders | undefined {
  if (!vendorId) return undefined;
  return new HttpHeaders({ 'X-Vendor-ID': vendorId });
}

@Injectable({ providedIn: 'root' })
export class QueryService {
  readonly #http = inject(HttpClient);
  readonly #base = `${environment.apiBaseUrl}/queries`;

  list(vendorId: string | null): Observable<QueryListResponse> {
    const headers = vendorHeader(vendorId);
    return this.#http.get<QueryListResponse>(this.#base, headers ? { headers } : {});
  }

  submit(
    vendorId: string,
    payload: QuerySubmissionPayload,
  ): Observable<QuerySubmissionResult> {
    return this.#http.post<QuerySubmissionResult>(this.#base, payload, {
      headers: vendorHeader(vendorId),
    });
  }

  get(vendorId: string | null, queryId: string): Observable<QueryDetail> {
    const headers = vendorHeader(vendorId);
    return this.#http.get<QueryDetail>(
      `${this.#base}/${encodeURIComponent(queryId)}`,
      headers ? { headers } : {},
    );
  }

  trail(vendorId: string | null, queryId: string): Observable<QueryTrailResponse> {
    const headers = vendorHeader(vendorId);
    return this.#http.get<QueryTrailResponse>(
      `${this.#base}/${encodeURIComponent(queryId)}/trail`,
      headers ? { headers } : {},
    );
  }
}
