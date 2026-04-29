import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, effect, inject, signal, untracked } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { QUERIES as MOCK_QUERIES } from '../data/mock-data';
import type { Query } from '../data/models';
import { toUiQueries } from '../data/query-mapper';
import { QueriesApi } from './queries.api';
import { SessionService } from './session.service';
import { VendorsStore } from './vendors.store';

export type LoadStatus = 'idle' | 'loading' | 'live' | 'mock' | 'error';

interface State {
  readonly status: LoadStatus;
  readonly queries: readonly Query[];
  readonly error: string | null;
}

const INITIAL: State = {
  status: 'idle',
  queries: MOCK_QUERIES,
  error: null,
};

/**
 * Source of truth for queries in the new design surface.
 *
 * Strategy mirrors `VendorsStore`:
 *   - Default to the mock QUERIES so screens render immediately and
 *     non-Admin sessions (Reviewer/Vendor) keep a working list.
 *   - When an Admin signs in, fetch `GET /admin/queries`. Map each
 *     row through `toUiQuery` using the live VendorsStore for vendor
 *     name/tier resolution.
 *   - On failure, keep the previous data (mock or last-good live) so
 *     the UI doesn't blank out.
 *
 * The store auto-refreshes when the vendor list updates so query rows
 * pick up vendor-name corrections without a manual reload.
 */
@Injectable({ providedIn: 'root' })
export class QueriesStore {
  readonly #api = inject(QueriesApi);
  readonly #session = inject(SessionService);
  readonly #vendors = inject(VendorsStore);

  readonly #state = signal<State>(INITIAL);
  readonly #lastDtos = signal<unknown[]>([]);

  readonly status = computed<LoadStatus>(() => this.#state().status);
  readonly list = computed<readonly Query[]>(() => this.#state().queries);
  readonly error = computed<string | null>(() => this.#state().error);
  readonly isLive = computed<boolean>(() => this.#state().status === 'live');

  byId = (queryId: string): Query | null =>
    this.list().find((q) => q.query_id === queryId) ?? null;

  constructor() {
    // Auto-load when an Admin token becomes available; reset on sign-out.
    effect(() => {
      const role = this.#session.role();
      const authed = this.#session.authed();
      if (authed && role === 'Admin') {
        void this.refresh();
      } else {
        this.#reset();
      }
    });

    // Re-derive UI queries when the vendor list changes so vendor-name
    // labels stay in sync with the master record.
    //
    // CRITICAL: read `#state` via `untracked()` so this effect does NOT
    // depend on `#state`. Without that guard, every write below triggers
    // the effect again — an infinite loop in zoneless mode that locks
    // up the page (Mail screen mounts ComposeModal which injects this
    // store, exposing the loop on every Mail page open).
    effect(() => {
      const vendors = this.#vendors.vendors();
      const dtos = this.#lastDtos();
      if (dtos.length === 0) return;
      const stateNow = untracked(() => this.#state());
      if (stateNow.status !== 'live') return;
      const remapped = toUiQueries(
        dtos as Parameters<typeof toUiQueries>[0],
        (id) => (id ? vendors.find((v) => v.vendor_id === id) ?? null : null),
      );
      this.#state.set({ ...stateNow, queries: remapped });
    });
  }

  async refresh(): Promise<void> {
    if (!this.#session.authed() || this.#session.role() !== 'Admin') return;

    this.#state.update((s) => ({ ...s, status: 'loading', error: null }));
    try {
      const resp = await firstValueFrom(this.#api.list());
      const vendors = this.#vendors.vendors();
      const mapped = toUiQueries(resp.queries, (id) =>
        id ? vendors.find((v) => v.vendor_id === id) ?? null : null,
      );
      this.#lastDtos.set([...resp.queries]);
      this.#state.set({
        status: 'live',
        queries: mapped.length > 0 ? mapped : MOCK_QUERIES,
        error: null,
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
    this.#lastDtos.set([]);
    this.#state.set(INITIAL);
  }

  #humanize(err: unknown): string {
    if (err instanceof HttpErrorResponse) {
      if (err.status === 0) return 'Cannot reach the server.';
      if (err.status === 401) return 'Session expired — please sign in again.';
      if (err.status === 403) return 'Admin role required to load queries.';
      if (err.status === 503) return 'Database unavailable — using cached data.';
      return `Query load failed (${err.status}).`;
    }
    return err instanceof Error ? err.message : 'Query load failed.';
  }
}
