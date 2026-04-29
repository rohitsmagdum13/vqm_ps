import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

// Backend response types — exact shape returned by src/api/routes/dashboard.py.
// Mirrors src/models/email_dashboard.py (frozen Pydantic v2 models). Fields
// the UI doesn't render are still listed for forward compatibility.

export interface UserDto {
  readonly name: string;
  readonly email: string;
}

export interface AttachmentSummaryDto {
  readonly attachment_id: string;
  readonly filename: string;
  readonly content_type: string;
  readonly size_bytes: number;
  readonly file_format: string;
  readonly download_url: string | null;
  readonly expires_in_seconds: number;
}

export interface MailItemDto {
  readonly query_id: string;
  readonly message_id: string;
  readonly correlation_id: string;
  readonly internet_message_id: string | null;
  readonly sender: UserDto;
  readonly to_recipients: readonly UserDto[];
  readonly cc_recipients: readonly UserDto[];
  readonly bcc_recipients: readonly UserDto[];
  readonly reply_to: readonly UserDto[];
  readonly subject: string;
  readonly body: string;
  readonly body_html: string | null;
  readonly importance: string | null;
  readonly has_attachments: boolean;
  readonly web_link: string | null;
  readonly timestamp: string;
  readonly parsed_at: string;
  readonly created_at: string;
  readonly in_reply_to: string | null;
  readonly conversation_id: string | null;
  readonly thread_status: string;
  readonly vendor_id: string | null;
  readonly vendor_match_method: string | null;
  readonly s3_raw_email_key: string | null;
  readonly source: string;
  readonly attachments: readonly AttachmentSummaryDto[];
}

export interface MailChainDto {
  readonly conversation_id: string | null;
  readonly mail_items: readonly MailItemDto[];
  readonly status: string;
  readonly priority: string;
}

export interface MailChainListDto {
  readonly total: number;
  readonly page: number;
  readonly page_size: number;
  readonly mail_chains: readonly MailChainDto[];
}

export type PriorityKey = 'Critical' | 'High' | 'Medium' | 'Low';

export interface EmailStatsDto {
  readonly total_emails: number;
  readonly new_count: number;
  readonly reopened_count: number;
  readonly resolved_count: number;
  readonly priority_breakdown: Readonly<Record<PriorityKey, number>>;
  readonly today_count: number;
  readonly this_week_count: number;
  // Daily counts for the last 10 days, oldest -> newest. Length always 10.
  // Backed by /emails/stats — see services/email_dashboard/service.py
  // (_fill_daily_buckets) for the day-bucketing semantics.
  readonly past_10_days_new: readonly number[];
  readonly past_10_days_resolved: readonly number[];
}

export interface ListMailParams {
  readonly page?: number;
  readonly pageSize?: number;
  readonly status?: 'New' | 'Reopened' | 'Resolved';
  readonly priority?: 'High' | 'Medium' | 'Low';
  readonly search?: string;
  readonly sortBy?: 'timestamp' | 'status' | 'priority';
  readonly sortOrder?: 'asc' | 'desc';
}

@Injectable({ providedIn: 'root' })
export class MailApi {
  readonly #http = inject(HttpClient);
  readonly #baseUrl = environment.apiBaseUrl;

  list(opts: ListMailParams = {}): Observable<MailChainListDto> {
    let params = new HttpParams()
      .set('page', String(opts.page ?? 1))
      .set('page_size', String(opts.pageSize ?? 50))
      .set('sort_by', opts.sortBy ?? 'timestamp')
      .set('sort_order', opts.sortOrder ?? 'desc');
    if (opts.status) params = params.set('status', opts.status);
    if (opts.priority) params = params.set('priority', opts.priority);
    if (opts.search) params = params.set('search', opts.search);

    return this.#http.get<MailChainListDto>(`${this.#baseUrl}/emails`, { params });
  }

  stats(): Observable<EmailStatsDto> {
    return this.#http.get<EmailStatsDto>(`${this.#baseUrl}/emails/stats`);
  }

  chain(queryId: string): Observable<MailChainDto> {
    return this.#http.get<MailChainDto>(
      `${this.#baseUrl}/emails/${encodeURIComponent(queryId)}`,
    );
  }
}
