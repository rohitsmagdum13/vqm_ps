import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, effect, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { PortalKpisApi, type PortalKpisDto } from './portal-kpis.api';
import { PortalQueriesStore } from './portal-queries.store';
import { SessionService } from './session.service';

export type LoadStatus = 'idle' | 'loading' | 'live' | 'mock' | 'error';

interface State {
  readonly status: LoadStatus;
  readonly kpis: PortalKpisDto;
  readonly error: string | null;
}

const ZERO_KPIS: PortalKpisDto = {
  open_queries: 0,
  resolved_queries: 0,
  avg_resolution_hours: 0,
  total_queries: 0,
};

const INITIAL: State = {
  status: 'idle',
  kpis: ZERO_KPIS,
  error: null,
};

/**
 * Vendor-portal KPIs (open / resolved / total / avg resolution hours).
 *
 * Strategy:
 *   - Defaults to zeros — a fresh tenant should not see fake numbers.
 *   - Fetches `/dashboard/kpis` when a Vendor signs in, with the JWT
 *     vendor_id mirrored into the `X-Vendor-ID` header that the
 *     backend expects.
 *   - On error, falls back to deriving counts from
 *     `PortalQueriesStore.list()` so the hero strip still shows
 *     plausible numbers when the database is briefly unavailable.
 */
@Injectable({ providedIn: 'root' })
export class PortalKpisStore {
  readonly #api = inject(PortalKpisApi);
  readonly #session = inject(SessionService);
  readonly #queries = inject(PortalQueriesStore);

  readonly #state = signal<State>(INITIAL);

  readonly status = computed<LoadStatus>(() => this.#state().status);
  readonly kpis = computed<PortalKpisDto>(() => this.#state().kpis);
  readonly error = computed<string | null>(() => this.#state().error);

  constructor() {
    effect(() => {
      const role = this.#session.role();
      const authed = this.#session.authed();
      if (authed && role === 'Vendor') {
        void this.refresh();
      } else {
        this.#state.set(INITIAL);
      }
    });
  }

  async refresh(): Promise<void> {
    const vendorId = this.#session.vendorId();
    if (!this.#session.authed() || this.#session.role() !== 'Vendor' || !vendorId) {
      return;
    }

    this.#state.update((s) => ({ ...s, status: 'loading', error: null }));
    try {
      const dto = await firstValueFrom(this.#api.getKpis(vendorId));
      this.#state.set({ status: 'live', kpis: dto, error: null });
    } catch (err: unknown) {
      this.#state.set({
        status: 'error',
        kpis: this.#deriveFromQueries(),
        error: this.#humanize(err),
      });
    }
  }

  #deriveFromQueries(): PortalKpisDto {
    const list = this.#queries.list();
    const open = list.filter(
      (q) => !['RESOLVED', 'CLOSED', 'MERGED_INTO_PARENT'].includes(q.status),
    ).length;
    const resolved = list.filter(
      (q) => q.status === 'RESOLVED' || q.status === 'CLOSED',
    ).length;
    return {
      open_queries: open,
      resolved_queries: resolved,
      total_queries: list.length,
      avg_resolution_hours: 0,
    };
  }

  #humanize(err: unknown): string {
    if (err instanceof HttpErrorResponse) {
      if (err.status === 0) return 'Cannot reach the server.';
      if (err.status === 401) return 'Session expired.';
      if (err.status === 503) return 'Database unavailable.';
      return `KPI load failed (${err.status}).`;
    }
    return err instanceof Error ? err.message : 'KPI load failed.';
  }
}
