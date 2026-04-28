import { HttpClient, HttpParams } from '@angular/common/http';
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

export type ExtractionStatus = 'pending' | 'success' | 'failed' | 'skipped';

export type ExtractionMethod =
  | 'textract'
  | 'pdfplumber'
  | 'openpyxl'
  | 'python_docx'
  | 'decode'
  | 'none';

export interface SubmittedAttachment {
  readonly attachment_id: string;
  readonly filename: string;
  readonly size_bytes: number;
  readonly extraction_status: ExtractionStatus;
  readonly extraction_method: ExtractionMethod;
}

export interface ExtractedAmount {
  readonly value: number;
  readonly currency: string;
}

export interface ExtractedEntities {
  readonly invoice_numbers: readonly string[];
  readonly po_numbers: readonly string[];
  readonly amounts: readonly ExtractedAmount[];
  readonly dates: readonly string[];
  readonly vendor_names: readonly string[];
  readonly product_skus: readonly string[];
  readonly contract_ids: readonly string[];
  readonly ticket_numbers: readonly string[];
  readonly emails: readonly string[];
  readonly phone_numbers: readonly string[];
  readonly summary: string;
}

export interface QuerySubmissionResult {
  readonly query_id: string;
  readonly status: string;
  readonly created_at: string;
  readonly attachments?: readonly SubmittedAttachment[];
  readonly extracted_entities?: ExtractedEntities;
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

/**
 * Backend has two distinct URL prefixes for queries:
 *   /queries              — vendor-only routes; the backend reads the
 *                           vendor identity from the JWT, no header needed
 *   /admin/queries        — admin-only routes; can scope by ?vendor_id=
 *
 * `Scope` selects which prefix the service hits. The backend rejects
 * cross-role calls (a vendor token hitting /admin/queries gets 403)
 * so the role check is enforced server-side too.
 */
export type QueryScope = 'vendor' | 'admin';

@Injectable({ providedIn: 'root' })
export class QueryService {
  readonly #http = inject(HttpClient);
  readonly #vendorBase = `${environment.apiBaseUrl}/queries`;
  readonly #adminBase = `${environment.apiBaseUrl}/admin/queries`;

  /** Pick the URL prefix for the given scope. */
  #base(scope: QueryScope): string {
    return scope === 'admin' ? this.#adminBase : this.#vendorBase;
  }

  /** List queries.
   *
   * Vendor scope: returns only the JWT vendor's queries (no params).
   * Admin scope: returns all queries; pass `vendorIdFilter` to scope
   * the listing to a single vendor.
   */
  list(
    scope: QueryScope,
    vendorIdFilter: string | null = null,
  ): Observable<QueryListResponse> {
    const url = this.#base(scope);
    if (scope === 'admin' && vendorIdFilter) {
      const params = new HttpParams().set('vendor_id', vendorIdFilter);
      return this.#http.get<QueryListResponse>(url, { params });
    }
    return this.#http.get<QueryListResponse>(url);
  }

  /** Submit a new query. Vendors only — admins don't submit. */
  submit(
    payload: QuerySubmissionPayload,
    files: readonly File[] = [],
  ): Observable<QuerySubmissionResult> {
    // Multipart: structured fields go in the `submission` JSON form
    // field, attachments under `files`. vendor_id comes from the JWT;
    // there is no longer a header for it.
    const form = new FormData();
    form.append('submission', JSON.stringify(payload));
    for (const f of files) {
      form.append('files', f, f.name);
    }
    return this.#http.post<QuerySubmissionResult>(this.#vendorBase, form);
  }

  get(scope: QueryScope, queryId: string): Observable<QueryDetail> {
    return this.#http.get<QueryDetail>(
      `${this.#base(scope)}/${encodeURIComponent(queryId)}`,
    );
  }

  trail(scope: QueryScope, queryId: string): Observable<QueryTrailResponse> {
    return this.#http.get<QueryTrailResponse>(
      `${this.#base(scope)}/${encodeURIComponent(queryId)}/trail`,
    );
  }
}
