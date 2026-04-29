import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

export interface PortalKpisDto {
  readonly open_queries: number;
  readonly resolved_queries: number;
  readonly avg_resolution_hours: number;
  readonly total_queries: number;
}

@Injectable({ providedIn: 'root' })
export class PortalKpisApi {
  readonly #http = inject(HttpClient);
  readonly #baseUrl = environment.apiBaseUrl;

  /**
   * The backend route reads vendor scope from the `X-Vendor-ID` header
   * (the auth interceptor only handles `Authorization`), so we set it
   * explicitly per call. The vendor_id passed here MUST come from the
   * authenticated session — never from a URL or form input.
   */
  getKpis(vendorId: string): Observable<PortalKpisDto> {
    const headers = new HttpHeaders({ 'X-Vendor-ID': vendorId });
    return this.#http.get<PortalKpisDto>(`${this.#baseUrl}/dashboard/kpis`, { headers });
  }
}
