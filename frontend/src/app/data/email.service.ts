import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import type {
  MailAttachmentDownload,
  MailChain,
  MailChainList,
  MailListQuery,
  MailStats,
} from '../shared/models/email';

@Injectable({ providedIn: 'root' })
export class EmailService {
  readonly #http = inject(HttpClient);
  readonly #base = `${environment.apiBaseUrl}/emails`;

  listChains(query: MailListQuery = {}): Observable<MailChainList> {
    let params = new HttpParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== '') {
        params = params.set(key, String(value));
      }
    }
    return this.#http.get<MailChainList>(this.#base, { params });
  }

  getStats(): Observable<MailStats> {
    return this.#http.get<MailStats>(`${this.#base}/stats`);
  }

  getChain(queryId: string): Observable<MailChain> {
    return this.#http.get<MailChain>(`${this.#base}/${encodeURIComponent(queryId)}`);
  }

  getAttachmentDownload(
    queryId: string,
    attachmentId: string,
  ): Observable<MailAttachmentDownload> {
    return this.#http.get<MailAttachmentDownload>(
      `${this.#base}/${encodeURIComponent(queryId)}/attachments/${encodeURIComponent(attachmentId)}/download`,
    );
  }
}
