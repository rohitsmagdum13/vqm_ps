import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { type Observable, map } from 'rxjs';
import { environment } from '../../environments/environment';
import type {
  Vendor,
  VendorCreateInput,
  VendorCreateResult,
  VendorDeleteResult,
  VendorUpdateInput,
  VendorUpdateResult,
} from '../shared/models/vendor';

@Injectable({ providedIn: 'root' })
export class VendorService {
  readonly #http = inject(HttpClient);
  readonly #base = `${environment.apiBaseUrl}/vendors`;

  list(): Observable<readonly Vendor[]> {
    return this.#http.get<Vendor[]>(this.#base);
  }

  create(input: VendorCreateInput): Observable<Vendor> {
    return this.#http.post<VendorCreateResult>(this.#base, input).pipe(
      map((r) => {
        if (!r.vendor) {
          throw new Error(r.message || 'Vendor missing from create response');
        }
        return r.vendor;
      }),
    );
  }

  update(vendorId: string, patch: VendorUpdateInput): Observable<Vendor> {
    return this.#http
      .put<VendorUpdateResult>(`${this.#base}/${encodeURIComponent(vendorId)}`, patch)
      .pipe(
        map((r) => {
          if (!r.vendor) {
            throw new Error(r.message || 'Vendor missing from update response');
          }
          return r.vendor;
        }),
      );
  }

  delete(vendorId: string): Observable<void> {
    return this.#http
      .delete<VendorDeleteResult>(`${this.#base}/${encodeURIComponent(vendorId)}`)
      .pipe(map(() => void 0));
  }
}
