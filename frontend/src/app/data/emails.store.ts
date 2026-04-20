import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { forkJoin } from 'rxjs';
import type {
  MailChain,
  MailListQuery,
  MailPriority,
  MailSortField,
  MailSortOrder,
  MailStats,
  MailStatus,
} from '../shared/models/email';
import { EmailService } from './email.service';

function errorMessage(err: unknown): string {
  if (err instanceof HttpErrorResponse) {
    const detail =
      err.error && typeof err.error === 'object' && 'detail' in err.error
        ? (err.error as { detail?: unknown }).detail
        : null;
    if (typeof detail === 'string' && detail.length > 0) return detail;
    if (err.status === 0) return 'Cannot reach the server. Is the backend running?';
    if (err.status === 401) return 'Session expired. Please sign in again.';
    if (err.status === 403) return 'Admin access required.';
    return `Request failed (${err.status})`;
  }
  if (err instanceof Error) return err.message;
  return 'Unexpected error';
}

@Injectable({ providedIn: 'root' })
export class EmailsStore {
  readonly #svc = inject(EmailService);

  readonly #chains = signal<readonly MailChain[]>([]);
  readonly #stats = signal<MailStats | null>(null);
  readonly #loading = signal<boolean>(false);
  readonly #error = signal<string | null>(null);
  readonly #hasLoaded = signal<boolean>(false);

  readonly #total = signal<number>(0);
  readonly #page = signal<number>(1);
  readonly #pageSize = signal<number>(20);

  readonly #status = signal<MailStatus | null>(null);
  readonly #priority = signal<MailPriority | null>(null);
  readonly #search = signal<string>('');
  readonly #sortBy = signal<MailSortField>('timestamp');
  readonly #sortOrder = signal<MailSortOrder>('desc');

  readonly #selectedQueryId = signal<string | null>(null);
  readonly #selectedChain = signal<MailChain | null>(null);
  readonly #detailLoading = signal<boolean>(false);

  readonly chains = this.#chains.asReadonly();
  readonly stats = this.#stats.asReadonly();
  readonly loading = this.#loading.asReadonly();
  readonly error = this.#error.asReadonly();
  readonly hasLoaded = this.#hasLoaded.asReadonly();

  readonly total = this.#total.asReadonly();
  readonly page = this.#page.asReadonly();
  readonly pageSize = this.#pageSize.asReadonly();

  readonly status = this.#status.asReadonly();
  readonly priority = this.#priority.asReadonly();
  readonly search = this.#search.asReadonly();
  readonly sortBy = this.#sortBy.asReadonly();
  readonly sortOrder = this.#sortOrder.asReadonly();

  readonly selectedQueryId = this.#selectedQueryId.asReadonly();
  readonly selectedChain = this.#selectedChain.asReadonly();
  readonly detailLoading = this.#detailLoading.asReadonly();

  readonly totalPages = computed<number>(() => {
    const t = this.#total();
    const ps = this.#pageSize();
    if (ps <= 0) return 1;
    return Math.max(1, Math.ceil(t / ps));
  });

  readonly filterCounts = computed(() => {
    const s = this.#stats();
    return {
      all: s?.total_emails ?? 0,
      new: s?.new_count ?? 0,
      reopened: s?.reopened_count ?? 0,
      resolved: s?.resolved_count ?? 0,
    };
  });

  refresh(): void {
    this.#loading.set(true);
    this.#error.set(null);
    const query: MailListQuery = {
      page: this.#page(),
      page_size: this.#pageSize(),
      status: this.#status() ?? undefined,
      priority: this.#priority() ?? undefined,
      search: this.#search().trim() || undefined,
      sort_by: this.#sortBy(),
      sort_order: this.#sortOrder(),
    };
    forkJoin({
      list: this.#svc.listChains(query),
      stats: this.#svc.getStats(),
    }).subscribe({
      next: ({ list, stats }) => {
        this.#chains.set(list.mail_chains);
        this.#stats.set(stats);
        this.#total.set(list.total);
        this.#page.set(list.page);
        this.#pageSize.set(list.page_size);
        this.#loading.set(false);
        this.#hasLoaded.set(true);
      },
      error: (err: unknown) => {
        this.#error.set(errorMessage(err));
        this.#loading.set(false);
        this.#hasLoaded.set(true);
      },
    });
  }

  refreshStats(): void {
    this.#svc.getStats().subscribe({
      next: (s) => this.#stats.set(s),
      error: () => {
        /* stats-only refresh is best-effort; don't blow up the UI */
      },
    });
  }

  setStatus(s: MailStatus | null): void {
    if (this.#status() === s) return;
    this.#status.set(s);
    this.#page.set(1);
    this.refresh();
  }

  setPriority(p: MailPriority | null): void {
    if (this.#priority() === p) return;
    this.#priority.set(p);
    this.#page.set(1);
    this.refresh();
  }

  setSearch(q: string): void {
    const v = q ?? '';
    if (this.#search() === v) return;
    this.#search.set(v);
    this.#page.set(1);
    this.refresh();
  }

  setSort(field: MailSortField, order: MailSortOrder): void {
    if (this.#sortBy() === field && this.#sortOrder() === order) return;
    this.#sortBy.set(field);
    this.#sortOrder.set(order);
    this.refresh();
  }

  setPage(n: number): void {
    const clamped = Math.max(1, Math.min(n, this.totalPages()));
    if (clamped === this.#page()) return;
    this.#page.set(clamped);
    this.refresh();
  }

  setPageSize(n: number): void {
    if (n <= 0 || n === this.#pageSize()) return;
    this.#pageSize.set(n);
    this.#page.set(1);
    this.refresh();
  }

  selectChain(queryId: string | null): void {
    this.#selectedQueryId.set(queryId);
    if (queryId === null) {
      this.#selectedChain.set(null);
      return;
    }
    const listed = this.#chains().find((c) =>
      c.mail_items.some((m) => m.query_id === queryId),
    );
    if (listed) {
      this.#selectedChain.set(listed);
    }
    this.#detailLoading.set(true);
    this.#svc.getChain(queryId).subscribe({
      next: (chain) => {
        this.#selectedChain.set(chain);
        this.#detailLoading.set(false);
      },
      error: (err: unknown) => {
        this.#error.set(errorMessage(err));
        this.#detailLoading.set(false);
      },
    });
  }

  downloadAttachment(queryId: string, attachmentId: string): Promise<string> {
    return new Promise((resolve, reject) => {
      this.#svc.getAttachmentDownload(queryId, attachmentId).subscribe({
        next: (dl) => {
          if (typeof window !== 'undefined') {
            window.open(dl.download_url, '_blank', 'noopener');
          }
          resolve(dl.download_url);
        },
        error: (err: unknown) => {
          const msg = errorMessage(err);
          this.#error.set(msg);
          reject(new Error(msg));
        },
      });
    });
  }
}
