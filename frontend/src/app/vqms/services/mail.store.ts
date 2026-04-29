import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, effect, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import {
  MAIL_THREADS as MOCK_THREADS,
  type MailThread,
} from '../data/mail';
import { toMailThreads } from '../data/mail-mapper';
import { MailApi, type EmailStatsDto } from './mail.api';
import { SessionService } from './session.service';

export type MailLoadStatus = 'idle' | 'loading' | 'live' | 'mock' | 'error';

interface State {
  readonly status: MailLoadStatus;
  readonly threads: readonly MailThread[];
  readonly stats: EmailStatsDto | null;
  readonly error: string | null;
  readonly lastFetchedAt: number | null;
}

const INITIAL: State = {
  status: 'idle',
  threads: MOCK_THREADS,
  stats: null,
  error: null,
  lastFetchedAt: null,
};

/**
 * Source of truth for the Mail / Email management screen.
 *
 * Strategy:
 *   - Default to MOCK_THREADS so the screen renders instantly and works
 *     even when the backend is offline (matches the same pattern as
 *     VendorsStore).
 *   - When an Admin is signed in, kick off `GET /emails`. On success,
 *     replace threads with the live data; on failure (Cannot reach,
 *     401/403, 5xx), keep mock and surface the error in `error()` so
 *     the page header can show a chip.
 *   - `status` exposes the mode so the UI can label the data as
 *     Live / Mock / Loading / Error.
 *
 * The mapper drops fields the dashboard endpoint does not yet expose
 * (processing_path, confidence_score, AI drafts, SLA percent) — those
 * default to neutral values so the row chips degrade gracefully until
 * the backend grows them.
 */
@Injectable({ providedIn: 'root' })
export class MailStore {
  readonly #api = inject(MailApi);
  readonly #session = inject(SessionService);

  readonly #state = signal<State>(INITIAL);

  readonly status = computed<MailLoadStatus>(() => this.#state().status);
  readonly threads = computed<readonly MailThread[]>(() => this.#state().threads);
  readonly stats = computed<EmailStatsDto | null>(() => this.#state().stats);
  readonly error = computed<string | null>(() => this.#state().error);
  readonly isLive = computed<boolean>(() => this.#state().status === 'live');
  readonly lastFetchedAt = computed<number | null>(() => this.#state().lastFetchedAt);

  constructor() {
    // Auto-load when an Admin token is present; reset to mock on sign-out.
    effect(() => {
      const role = this.#session.role();
      const authed = this.#session.authed();
      // eslint-disable-next-line no-console
      console.log('[MailStore] session change', { authed, role });
      if (authed && role === 'Admin') {
        void this.refresh();
      } else {
        this.#reset();
      }
    });
  }

  async refresh(): Promise<void> {
    if (!this.#session.authed() || this.#session.role() !== 'Admin') {
      // eslint-disable-next-line no-console
      console.log('[MailStore] refresh skipped — not Admin', {
        authed: this.#session.authed(),
        role: this.#session.role(),
      });
      this.#state.update((s) => ({ ...s, status: 'mock', error: null }));
      return;
    }
    // eslint-disable-next-line no-console
    console.log('[MailStore] refresh starting → GET /emails + /emails/stats');
    this.#state.update((s) => ({ ...s, status: 'loading', error: null }));

    try {
      // List + stats in parallel; either failing keeps the other partial result.
      const [list, stats] = await Promise.all([
        firstValueFrom(this.#api.list({ pageSize: 50 })),
        firstValueFrom(this.#api.stats()).catch(() => null),
      ]);
      const mapped = toMailThreads(list.mail_chains);
      // eslint-disable-next-line no-console
      console.log('[MailStore] refresh OK', {
        chains: list.mail_chains.length,
        threads: mapped.length,
        statsLoaded: stats !== null,
      });
      this.#state.set({
        status: 'live',
        // Empty live list means "no email-sourced queries yet" — that's a
        // legitimate empty state, so don't fall back to mock.
        threads: mapped,
        stats,
        error: null,
        lastFetchedAt: Date.now(),
      });
    } catch (err: unknown) {
      // eslint-disable-next-line no-console
      console.error('[MailStore] refresh FAILED', err);
      this.#state.update((s) => ({
        ...s,
        status: 'error',
        error: this.#humanize(err),
      }));
    }
  }

  #reset(): void {
    this.#state.set(INITIAL);
  }

  #humanize(err: unknown): string {
    if (err instanceof HttpErrorResponse) {
      if (err.status === 0) return 'Cannot reach the API server.';
      if (err.status === 401) return 'Session expired — please sign in again.';
      if (err.status === 403) return 'Admin role required to load live email data.';
      if (err.status === 503) return 'Email dashboard service is not available.';
      const detail = this.#detailFromBody(err.error);
      if (detail) return detail;
      return `Request failed (${err.status}).`;
    }
    return err instanceof Error ? err.message : 'Request failed.';
  }

  #detailFromBody(body: unknown): string | null {
    if (!body || typeof body !== 'object') return null;
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === 'string') return detail;
    return null;
  }
}
