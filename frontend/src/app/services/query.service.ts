import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface QueryItem {
  query_id: string;
  subject: string | null;
  query_type: string | null;
  status: string;
  priority: string | null;
  source: string;
  processing_path: string | null;
  reference_number: string | null;
  sla_deadline: string | null;
  created_at: string;
  updated_at: string;
}

export interface QueryDetail extends QueryItem {
  description: string | null;
  vendor_id: string | null;
}

export interface KpiResponse {
  open_queries: number;
  resolved_queries: number;
  avg_resolution_hours: number;
  total_queries: number;
}

export interface SubmitResponse {
  query_id: string;
  status: string;
  created_at: string;
}

/** Maps backend query type codes to readable labels.
 *  Must stay in sync with backend QUERY_TYPES in models/query.py. */
export const QUERY_TYPE_LABELS: Record<string, string> = {
  RETURN_REFUND: 'Return & Refund',
  GENERAL_INQUIRY: 'General Inquiry',
  CATALOG_PRICING: 'Catalog & Pricing',
  CONTRACT_QUERY: 'Contract Query',
  PURCHASE_ORDER: 'Purchase Order',
  SLA_BREACH_REPORT: 'SLA Breach Report',
  DELIVERY_SHIPMENT: 'Delivery & Shipment',
  INVOICE_PAYMENT: 'Invoice & Payment',
  COMPLIANCE_AUDIT: 'Compliance & Audit',
  TECHNICAL_SUPPORT: 'Technical Support',
  ONBOARDING: 'Onboarding',
  QUALITY_ISSUE: 'Quality Issue',
};

/** Returns the human-readable label for a query type code,
 *  or the raw code if not found in the map. */
export function queryTypeLabel(code: string | null | undefined): string {
  if (!code) return '-';
  return QUERY_TYPE_LABELS[code] ?? code;
}

@Injectable({ providedIn: 'root' })
export class QueryService {
  constructor(private http: HttpClient) {}

  getKpis(): Observable<KpiResponse> {
    return this.http.get<KpiResponse>(`${environment.apiUrl}/dashboard/kpis`);
  }

  getQueries(): Observable<{ queries: QueryItem[] }> {
    return this.http.get<{ queries: QueryItem[] }>(`${environment.apiUrl}/queries`);
  }

  getQueryById(queryId: string): Observable<QueryDetail> {
    return this.http.get<QueryDetail>(`${environment.apiUrl}/queries/${queryId}`);
  }

  submitQuery(payload: {
    query_type: string;
    subject: string;
    description: string;
    priority: string;
    reference_number?: string;
  }): Observable<SubmitResponse> {
    return this.http.post<SubmitResponse>(`${environment.apiUrl}/queries`, payload);
  }
}
