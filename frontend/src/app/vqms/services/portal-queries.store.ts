import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, effect, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { QUERIES as MOCK_QUERIES } from '../data/mock-data';
import type { Query } from '../data/models';
import { toUiQueries } from '../data/query-mapper';
import {
  PortalQueriesApi,
  type QuerySubmissionDto,
  type SubmitQueryResponseDto,
  type VendorQueryDto,
} from './portal-queries.api';
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
  queries: [],
  error: null,
};

/**
 * Vendor-side query store. Mirrors the admin `QueriesStore` shape but
 * hits `/queries` (vendor-scoped, JWT decides ownership) instead of
 * `/admin/queries`.
 *
 * Strategy:
 *   - Defaults to an empty list so an authed vendor never sees another
 *     vendor's mock data leaking through.
 *   - On Vendor sign-in, fetch `/queries` and map through the same
 *     mapper the admin store uses. Vendor name/tier come from the
 *     session, not the vendor master (vendors don't have access to the
 *     master record).
 *   - On failure, fall back to filtered mock so the demo still shows
 *     something for the signed-in vendor's vendor_id.
 */
@Injectable({ providedIn: 'root' })
export class PortalQueriesStore {
  readonly #api = inject(PortalQueriesApi);
  readonly #session = inject(SessionService);
  readonly #vendors = inject(VendorsStore);

  readonly #state = signal<State>(INITIAL);
  readonly #lastDtos = signal<readonly VendorQueryDto[]>([]);

  readonly status = computed<LoadStatus>(() => this.#state().status);
  readonly list = computed<readonly Query[]>(() => this.#state().queries);
  readonly error = computed<string | null>(() => this.#state().error);
  readonly isLive = computed<boolean>(() => this.#state().status === 'live');

  constructor() {
    effect(() => {
      const role = this.#session.role();
      const authed = this.#session.authed();
      if (authed && role === 'Vendor') {
        void this.refresh();
      } else {
        this.#reset();
      }
    });

    // Re-derive on vendor list updates so the row's vendor_name/tier
    // stay in sync (the vendor master may be empty for a fresh tenant).
    effect(() => {
      const vendors = this.#vendors.vendors();
      const dtos = this.#lastDtos();
      if (this.#state().status !== 'live' || dtos.length === 0) return;
      const remapped = toUiQueries(dtos, (id) =>
        id ? vendors.find((v) => v.vendor_id === id) ?? null : null,
      );
      this.#state.update((s) => ({ ...s, queries: remapped }));
    });
  }

  async refresh(): Promise<void> {
    if (!this.#session.authed() || this.#session.role() !== 'Vendor') return;

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
        queries: mapped,
        error: null,
      });
    } catch (err: unknown) {
      this.#state.update((s) => ({
        ...s,
        status: 'error',
        error: this.#humanize(err),
        queries: this.#mockForVendor(),
      }));
    }
  }

  /**
   * Submit a new query via the multipart wizard endpoint. Errors are
   * humanized (Pydantic 422 details surface inline). On success the
   * list re-fetches automatically so the new row appears at the top.
   */
  async submit(
    submission: QuerySubmissionDto,
    files: readonly File[],
  ): Promise<SubmitQueryResponseDto> {
    let resp: SubmitQueryResponseDto;
    try {
      resp = await firstValueFrom(this.#api.submit(submission, files));
    } catch (err: unknown) {
      throw new Error(this.#humanize(err));
    }
    await this.refresh();
    return resp;
  }

  #mockForVendor(): readonly Query[] {
    const vid = this.#session.vendorId();
    if (!vid) return [];
    return MOCK_QUERIES.filter((q) => q.vendor_id === vid);
  }

  #reset(): void {
    this.#lastDtos.set([]);
    this.#state.set(INITIAL);
  }

  #humanize(err: unknown): string {
    if (err instanceof HttpErrorResponse) {
      if (err.status === 0) return 'Cannot reach the server.';
      if (err.status === 401) return 'Session expired — please sign in again.';
      if (err.status === 403) return 'This account is not a vendor account.';
      if (err.status === 409) return 'Duplicate submission detected.';
      const detail = this.#detailFromBody(err.error);
      if (detail) return detail;
      if (err.status === 422) return 'Validation failed — check the field values.';
      if (err.status === 503) return 'Portal service unavailable.';
      return `Request failed (${err.status}).`;
    }
    return err instanceof Error ? err.message : 'Request failed.';
  }

  #detailFromBody(body: unknown): string | null {
    if (!body || typeof body !== 'object') return null;
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: unknown; loc?: unknown } | undefined;
      if (first && typeof first.msg === 'string') {
        const loc = Array.isArray(first.loc)
          ? first.loc.filter((l) => typeof l === 'string').join(' › ')
          : '';
        return loc ? `${loc}: ${first.msg}` : first.msg;
      }
    }
    return null;
  }
}
