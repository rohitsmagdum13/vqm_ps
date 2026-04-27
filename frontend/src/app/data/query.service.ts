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
    files: readonly File[] = [],
  ): Observable<QuerySubmissionResult> {
    // Backend now accepts multipart/form-data with the structured fields
    // packed into a single `submission` JSON form field plus 0..N file
    // parts under the name `files`. We always send multipart so the
    // request shape stays consistent whether the user attaches files
    // or not.
    const form = new FormData();
    form.append('submission', JSON.stringify(payload));
    for (const f of files) {
      form.append('files', f, f.name);
    }
    return this.#http.post<QuerySubmissionResult>(this.#base, form, {
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
