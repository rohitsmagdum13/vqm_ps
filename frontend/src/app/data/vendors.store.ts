import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import type { Vendor, VendorCreateInput, VendorUpdateInput } from '../shared/models/vendor';
import { VendorService } from './vendor.service';

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

function keyFor(v: Vendor): string {
  return v.vendor_id ?? v.id;
}

@Injectable({ providedIn: 'root' })
export class VendorsStore {
  readonly #svc = inject(VendorService);

  readonly #vendors = signal<readonly Vendor[]>([]);
  readonly #search = signal<string>('');
  readonly #selectedId = signal<string | null>(null);
  readonly #loading = signal<boolean>(false);
  readonly #error = signal<string | null>(null);
  readonly #hasLoaded = signal<boolean>(false);

  readonly vendors = this.#vendors.asReadonly();
  readonly search = this.#search.asReadonly();
  readonly selectedId = this.#selectedId.asReadonly();
  readonly loading = this.#loading.asReadonly();
  readonly error = this.#error.asReadonly();
  readonly hasLoaded = this.#hasLoaded.asReadonly();

  readonly filtered = computed<readonly Vendor[]>(() => {
    const q = this.#search().trim().toLowerCase();
    const all = this.#vendors();
    if (q.length === 0) return all;
    return all.filter((v) => {
      const hay = [
        v.name,
        v.vendor_id ?? '',
        v.billing_city ?? '',
        v.billing_state ?? '',
        v.website ?? '',
        v.category ?? '',
      ]
        .join(' ')
        .toLowerCase();
      return hay.includes(q);
    });
  });

  readonly selected = computed<Vendor | null>(() => {
    const id = this.#selectedId();
    if (id === null) return null;
    return this.#vendors().find((v) => v.id === id) ?? null;
  });

  refresh(): void {
    this.#loading.set(true);
    this.#error.set(null);
    this.#svc.list().subscribe({
      next: (rows) => {
        this.#vendors.set(rows);
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

  create(input: VendorCreateInput): Promise<Vendor> {
    this.#loading.set(true);
    this.#error.set(null);
    return new Promise((resolve, reject) => {
      this.#svc.create(input).subscribe({
        next: (row) => {
          this.#vendors.update((xs) => [row, ...xs]);
          this.#loading.set(false);
          resolve(row);
        },
        error: (err: unknown) => {
          const msg = errorMessage(err);
          this.#error.set(msg);
          this.#loading.set(false);
          reject(new Error(msg));
        },
      });
    });
  }

  update(vendor: Vendor, patch: VendorUpdateInput): Promise<Vendor> {
    this.#loading.set(true);
    this.#error.set(null);
    const key = keyFor(vendor);
    return new Promise((resolve, reject) => {
      this.#svc.update(key, patch).subscribe({
        next: (row) => {
          this.#vendors.update((xs) => xs.map((v) => (v.id === vendor.id ? row : v)));
          this.#loading.set(false);
          resolve(row);
        },
        error: (err: unknown) => {
          const msg = errorMessage(err);
          this.#error.set(msg);
          this.#loading.set(false);
          reject(new Error(msg));
        },
      });
    });
  }

  remove(vendor: Vendor): Promise<void> {
    this.#loading.set(true);
    this.#error.set(null);
    const key = keyFor(vendor);
    return new Promise((resolve, reject) => {
      this.#svc.delete(key).subscribe({
        next: () => {
          this.#vendors.update((xs) => xs.filter((v) => v.id !== vendor.id));
          if (this.#selectedId() === vendor.id) this.#selectedId.set(null);
          this.#loading.set(false);
          resolve();
        },
        error: (err: unknown) => {
          const msg = errorMessage(err);
          this.#error.set(msg);
          this.#loading.set(false);
          reject(new Error(msg));
        },
      });
    });
  }

  setSearch(q: string): void {
    this.#search.set(q);
  }

  select(id: string | null): void {
    this.#selectedId.set(id);
  }
}
