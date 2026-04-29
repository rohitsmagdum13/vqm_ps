import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, effect, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { QUERIES, VENDORS as MOCK_VENDORS } from '../data/mock-data';
import type { Vendor } from '../data/models';
import { toUiVendors } from '../data/vendor-mapper';
import { SessionService } from './session.service';
import {
  VendorsApi,
  type VendorAccountDto,
  type VendorCreateRequestDto,
  type VendorUpdateRequestDto,
} from './vendors.api';

export type LoadStatus = 'idle' | 'loading' | 'live' | 'mock' | 'error';

interface State {
  readonly status: LoadStatus;
  readonly vendors: readonly Vendor[];
  readonly raw: readonly VendorAccountDto[];
  readonly error: string | null;
}

const INITIAL: State = {
  status: 'idle',
  vendors: MOCK_VENDORS,
  raw: [],
  error: null,
};

/**
 * Single source of truth for vendor data in the new design surface.
 *
 * Strategy:
 *   - Default to the mock VENDORS so screens render immediately and
 *     the Reviewer/Vendor roles (which can't call /vendors) keep a
 *     usable list to look at.
 *   - When an Admin signs in, kick off `GET /vendors`. On success,
 *     replace the signal with the live data; on failure, log and
 *     keep mock so the UI doesn't blank out.
 *   - Mutations (create/update/delete) optimistically refresh the
 *     full list on success — Salesforce eventual-consistency means
 *     a re-fetch is the safest path.
 *
 * `status` exposes which mode the screens are reading from so the
 * page header can show "Live · Salesforce" vs "Mock data" and not
 * mislead the operator.
 */
@Injectable({ providedIn: 'root' })
export class VendorsStore {
  readonly #api = inject(VendorsApi);
  readonly #session = inject(SessionService);

  readonly #state = signal<State>(INITIAL);

  readonly status = computed<LoadStatus>(() => this.#state().status);
  readonly vendors = computed<readonly Vendor[]>(() => this.#state().vendors);
  readonly error = computed<string | null>(() => this.#state().error);
  readonly isLive = computed<boolean>(() => this.#state().status === 'live');

  byId = (vendorId: string): Vendor | null =>
    this.vendors().find((v) => v.vendor_id === vendorId) ?? null;

  constructor() {
    // Auto-load when an Admin token becomes available, and clear
    // back to mock when the session ends.
    effect(() => {
      const role = this.#session.role();
      const authed = this.#session.authed();
      if (authed && role === 'Admin') {
        // Fire and forget — refresh() handles its own state.
        void this.refresh();
      } else {
        this.#reset();
      }
    });
  }

  async refresh(): Promise<void> {
    if (!this.#session.authed() || this.#session.role() !== 'Admin') {
      // Reviewer and Vendor roles cannot call /vendors — stick with mock.
      return;
    }
    this.#state.update((s) => ({ ...s, status: 'loading', error: null }));
    try {
      const dtos = await firstValueFrom(this.#api.list());
      const mapped = toUiVendors(dtos, QUERIES);
      this.#state.set({
        status: 'live',
        vendors: mapped.length > 0 ? mapped : MOCK_VENDORS,
        raw: dtos,
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

  async update(vendorId: string, patch: VendorUpdateRequestDto): Promise<void> {
    await firstValueFrom(this.#api.update(vendorId, patch));
    await this.refresh();
  }

  /**
   * Create a new vendor in Salesforce. The backend auto-generates the
   * `Vendor_ID__c` (V-XXX). Errors are translated to a single readable
   * sentence so the form can render them inline — the raw HTTP error
   * from `simple-salesforce` would surface field names and stack
   * traces that don't help the operator.
   */
  async create(payload: VendorCreateRequestDto): Promise<void> {
    try {
      await firstValueFrom(this.#api.create(payload));
    } catch (err: unknown) {
      throw new Error(this.#humanize(err));
    }
    await this.refresh();
  }

  async remove(vendorId: string): Promise<void> {
    await firstValueFrom(this.#api.delete(vendorId));
    await this.refresh();
  }

  #reset(): void {
    this.#state.set(INITIAL);
  }

  #humanize(err: unknown): string {
    if (err instanceof HttpErrorResponse) {
      if (err.status === 0) return 'Cannot reach the server.';
      if (err.status === 401) return 'Session expired — please sign in again.';
      if (err.status === 403) return 'Admin role required.';
      const detail = this.#detailFromBody(err.error);
      if (detail) return detail;
      if (err.status === 502) return 'Salesforce request failed — please retry.';
      if (err.status === 422) return 'Validation failed — check the field values.';
      return `Request failed (${err.status}).`;
    }
    return err instanceof Error ? err.message : 'Request failed.';
  }

  #detailFromBody(body: unknown): string | null {
    if (!body || typeof body !== 'object') return null;
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      // FastAPI 422 bodies look like [{loc:[...], msg:"..."}]
      const first = detail[0] as { msg?: unknown } | undefined;
      if (first && typeof first.msg === 'string') return first.msg;
    }
    return null;
  }
}
