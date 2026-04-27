import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import type {
  ApproveResult,
  DraftApprovalDetail,
  DraftApprovalListResponse,
  RejectResult,
} from '../shared/models/draft-approval';

/**
 * HTTP client for the admin draft-approval API
 * (see src/api/routes/admin_drafts.py).
 *
 * All endpoints require ADMIN role. The JWT interceptor attaches the
 * Bearer token; a non-admin caller will get a 403 from the backend.
 */
@Injectable({ providedIn: 'root' })
export class DraftApprovalsService {
  readonly #http = inject(HttpClient);
  readonly #base = `${environment.apiBaseUrl}/admin/drafts`;

  list(): Observable<DraftApprovalListResponse> {
    return this.#http.get<DraftApprovalListResponse>(this.#base);
  }

  get(queryId: string): Observable<DraftApprovalDetail> {
    return this.#http.get<DraftApprovalDetail>(
      `${this.#base}/${encodeURIComponent(queryId)}`,
    );
  }

  approve(queryId: string): Observable<ApproveResult> {
    return this.#http.post<ApproveResult>(
      `${this.#base}/${encodeURIComponent(queryId)}/approve`,
      {},
    );
  }

  approveWithEdits(
    queryId: string,
    body: { subject: string; body_html: string },
  ): Observable<ApproveResult> {
    return this.#http.post<ApproveResult>(
      `${this.#base}/${encodeURIComponent(queryId)}/edit-approve`,
      body,
    );
  }

  reject(queryId: string, feedback: string): Observable<RejectResult> {
    return this.#http.post<RejectResult>(
      `${this.#base}/${encodeURIComponent(queryId)}/reject`,
      { feedback },
    );
  }
}
