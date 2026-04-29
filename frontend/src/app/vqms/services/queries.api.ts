import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

/**
 * One row of `GET /admin/queries`. Reflects the join in
 * `admin_queries.py:list_all_queries` between
 * `workflow.case_execution` and `intake.portal_queries`. Most
 * portal-side fields are nullable because email-sourced queries
 * don't have a corresponding row in `intake.portal_queries`.
 */
export interface AdminQueryDto {
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

export interface AdminQueriesListResponse {
  readonly queries: readonly AdminQueryDto[];
}

export interface AdminQueryDetailDto extends AdminQueryDto {
  readonly description: string | null;
}

export interface TrailEvent {
  readonly [key: string]: unknown;
}

export interface TrailResponse {
  readonly events: readonly TrailEvent[];
}

@Injectable({ providedIn: 'root' })
export class QueriesApi {
  readonly #http = inject(HttpClient);
  readonly #baseUrl = environment.apiBaseUrl;

  list(vendorId?: string): Observable<AdminQueriesListResponse> {
    let params = new HttpParams();
    if (vendorId) params = params.set('vendor_id', vendorId);
    return this.#http.get<AdminQueriesListResponse>(`${this.#baseUrl}/admin/queries`, {
      params,
    });
  }

  get(queryId: string): Observable<AdminQueryDetailDto> {
    return this.#http.get<AdminQueryDetailDto>(
      `${this.#baseUrl}/admin/queries/${encodeURIComponent(queryId)}`,
    );
  }

  getTrail(queryId: string): Observable<TrailResponse> {
    return this.#http.get<TrailResponse>(
      `${this.#baseUrl}/admin/queries/${encodeURIComponent(queryId)}/trail`,
    );
  }
}
