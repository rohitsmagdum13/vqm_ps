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
