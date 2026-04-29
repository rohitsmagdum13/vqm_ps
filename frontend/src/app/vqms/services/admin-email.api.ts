import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

// Typed wrappers around the admin email send endpoints.
// Backend: src/api/routes/admin_email.py
//   POST /admin/email/send                          — fresh email
//   POST /admin/email/queries/{query_id}/reply      — threaded reply
// Both endpoints use multipart/form-data because they accept attachments.
// `X-Request-Id` (optional) deduplicates retries — same payload returns
// the original send result instead of double-sending.

export interface AdminSendResultDto {
  readonly outbound_id: string;
  readonly to: readonly string[];
  readonly cc: readonly string[];
  readonly bcc: readonly string[];
  readonly subject: string;
  readonly sent_at: string | null;
  readonly thread_mode: string;
  readonly query_id: string | null;
  readonly reply_to_message_id: string | null;
  readonly conversation_id: string | null;
  readonly attachments: readonly { filename: string; size_bytes: number }[];
  readonly idempotent_replay: boolean;
}

export interface ReplyToQueryRequest {
  readonly queryId: string;
  readonly bodyHtml: string;
  readonly cc?: string;
  readonly bcc?: string;
  /** Comma-separated. Defaults to original sender on the backend. */
  readonly toOverride?: string;
  /** Pin reply to a specific inbound message; defaults to latest. */
  readonly replyToMessageId?: string;
  readonly files?: readonly File[];
  /** X-Request-Id header value for idempotent retries. */
  readonly requestId?: string;
}

export interface SendFreshRequest {
  /** Comma-separated recipient emails. Required. */
  readonly to: string;
  readonly subject: string;
  readonly bodyHtml: string;
  readonly cc?: string;
  readonly bcc?: string;
  /** Optional Salesforce vendor id, audit-only. */
  readonly vendorId?: string;
  /** Optional existing query_id to link this send against. */
  readonly queryId?: string;
  readonly files?: readonly File[];
  readonly requestId?: string;
}

@Injectable({ providedIn: 'root' })
export class AdminEmailApi {
  readonly #http = inject(HttpClient);
  readonly #baseUrl = environment.apiBaseUrl;

  /**
   * Reply on the existing email trail attached to `queryId`. Vendor
   * receives the email inside the same conversation as the original
   * (Graph's /messages/{id}/reply preserves conversationId, In-Reply-To,
   * and References headers).
   */
  replyToQuery(req: ReplyToQueryRequest): Observable<AdminSendResultDto> {
    const form = new FormData();
    form.set('body_html', req.bodyHtml);
    if (req.cc) form.set('cc', req.cc);
    if (req.bcc) form.set('bcc', req.bcc);
    if (req.toOverride) form.set('to_override', req.toOverride);
    if (req.replyToMessageId) form.set('reply_to_message_id', req.replyToMessageId);
    for (const f of req.files ?? []) {
      form.append('files', f, f.name);
    }
    const url = `${this.#baseUrl}/admin/email/queries/${encodeURIComponent(req.queryId)}/reply`;
    return this.#http.post<AdminSendResultDto>(url, form, {
      headers: this.#headers(req.requestId),
    });
  }

  /**
   * Send a fresh email — no existing thread. Backend assigns a new
   * conversation/trail. `to` is comma-separated since the backend
   * splits on comma server-side.
   */
  send(req: SendFreshRequest): Observable<AdminSendResultDto> {
    const form = new FormData();
    form.set('to', req.to);
    form.set('subject', req.subject);
    form.set('body_html', req.bodyHtml);
    if (req.cc) form.set('cc', req.cc);
    if (req.bcc) form.set('bcc', req.bcc);
    if (req.vendorId) form.set('vendor_id', req.vendorId);
    if (req.queryId) form.set('query_id', req.queryId);
    for (const f of req.files ?? []) {
      form.append('files', f, f.name);
    }
    return this.#http.post<AdminSendResultDto>(
      `${this.#baseUrl}/admin/email/send`,
      form,
      { headers: this.#headers(req.requestId) },
    );
  }

  // The browser sets the multipart boundary on FormData automatically;
  // we MUST NOT set Content-Type ourselves or the boundary is missing
  // and FastAPI parses zero form fields.
  #headers(requestId?: string): HttpHeaders {
    let h = new HttpHeaders();
    if (requestId) h = h.set('X-Request-Id', requestId);
    return h;
  }
}
