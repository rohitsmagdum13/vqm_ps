import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, effect, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { OverviewApi, type AdminOverviewDto } from './overview.api';
import { SessionService } from './session.service';

export type OverviewLoadStatus = 'idle' | 'loading' | 'live' | 'mock' | 'error';

interface State {
  readonly status: OverviewLoadStatus;
  readonly data: AdminOverviewDto | null;
  readonly error: string | null;
  readonly lastFetchedAt: number | null;
}

const INITIAL: State = {
  status: 'idle',
  data: null,
  error: null,
  lastFetchedAt: null,
};

/**
 * Single source of truth for the Operations Overview screen.
 *
 * Strategy (mirrors MailStore):
 *   - Default to `null` data so the page renders mock visuals
 *     immediately (the page already imports TREND_30D / HOURLY_24H
 *     / etc. as fallbacks).
 *   - When an Admin signs in, kick off `GET /admin/overview`. On
 *     success, replace `data` with the live payload; on failure,
 *     surface the error so the page header chip shows the reason.
 *   - `status` exposes the mode so the screen can label data as
 *     Live / Mock / Loading / Error.
 *
 * The bundled endpoint means a single fetch populates every chart —
 * no per-chart loading states to coordinate.
 */
@Injectable({ providedIn: 'root' })
export class OverviewStore {
  readonly #api = inject(OverviewApi);
  readonly #session = inject(SessionService);

  readonly #state = signal<State>(INITIAL);

  readonly status = computed<OverviewLoadStatus>(() => this.#state().status);
  readonly data = computed<AdminOverviewDto | null>(() => this.#state().data);
  readonly error = computed<string | null>(() => this.#state().error);
  readonly isLive = computed<boolean>(() => this.#state().status === 'live');
  readonly lastFetchedAt = computed<number | null>(() => this.#state().lastFetchedAt);

  constructor() {
    // Auto-load when an Admin token is present; reset on sign-out.
    effect(() => {
      const role = this.#session.role();
      const authed = this.#session.authed();
      if (authed && role === 'Admin') {
        void this.refresh();
      } else {
        this.#reset();
      }
    });
  }

  async refresh(): Promise<void> {
    if (!this.#session.authed() || this.#session.role() !== 'Admin') {
      // Reviewer / Vendor cannot call /admin/overview — keep mock visuals.
      this.#state.update((s) => ({ ...s, status: 'mock', error: null }));
      return;
    }
    this.#state.update((s) => ({ ...s, status: 'loading', error: null }));

    try {
      const data = await firstValueFrom(this.#api.get());
      this.#state.set({
        status: 'live',
        data,
        error: null,
        lastFetchedAt: Date.now(),
      });
    } catch (err: unknown) {
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
      if (err.status === 403) return 'Admin role required to load live overview data.';
      if (err.status === 503) return 'Overview service is not available.';
      const detail = this.#detailFromBody(err.error);
      if (detail) return detail;
      return `Request failed (${err.status}).`;
    }
    return err instanceof Error ? err.message : 'Request failed.';
  }

  #detailFromBody(body: unknown): string | null {
    if (!body || typeof body !== 'object') return null;
    const detail = (body as { detail?: unknown }).detail;
    return typeof detail === 'string' ? detail : null;
  }
}
