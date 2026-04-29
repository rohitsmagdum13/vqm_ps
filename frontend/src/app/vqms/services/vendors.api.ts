import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

/**
 * Salesforce-shape vendor record as returned by the FastAPI
 * `GET /vendors` endpoint. The backend translates the Salesforce
 * `Vendor_Account__c` custom object into this DTO — note that
 * `vendor_id`, `vendor_tier`, and most other fields are nullable
 * because Salesforce records often have empty custom fields.
 */
export interface VendorAccountDto {
  readonly id: string;
  readonly name: string;
  readonly vendor_id: string | null;
  readonly website: string | null;
  readonly vendor_tier: string | null;
  readonly category: string | null;
  readonly payment_terms: string | null;
  readonly annual_revenue: number | null;
  readonly sla_response_hours: number | null;
  readonly sla_resolution_days: number | null;
  readonly vendor_status: string | null;
  readonly onboarded_date: string | null;
  readonly billing_city: string | null;
  readonly billing_state: string | null;
  readonly billing_country: string | null;
}

export interface VendorUpdateRequestDto {
  readonly website?: string;
  readonly vendor_tier?: string;
  readonly category?: string;
  readonly payment_terms?: string;
  readonly annual_revenue?: number;
  readonly sla_response_hours?: number;
  readonly sla_resolution_days?: number;
  readonly vendor_status?: string;
  readonly onboarded_date?: string;
  readonly billing_city?: string;
  readonly billing_state?: string;
  readonly billing_country?: string;
}

export interface VendorCreateRequestDto extends VendorUpdateRequestDto {
  readonly name: string;
}

export interface VendorMutationResultDto {
  readonly success: boolean;
  readonly vendor_id: string;
  readonly message: string;
  readonly vendor: VendorAccountDto | null;
}

@Injectable({ providedIn: 'root' })
export class VendorsApi {
  readonly #http = inject(HttpClient);
  readonly #baseUrl = environment.apiBaseUrl;

  list(): Observable<readonly VendorAccountDto[]> {
    return this.#http.get<readonly VendorAccountDto[]>(`${this.#baseUrl}/vendors`);
  }

  create(body: VendorCreateRequestDto): Observable<VendorMutationResultDto> {
    return this.#http.post<VendorMutationResultDto>(`${this.#baseUrl}/vendors`, body);
  }

  update(
    vendorId: string,
    body: VendorUpdateRequestDto,
  ): Observable<VendorMutationResultDto> {
    return this.#http.put<VendorMutationResultDto>(
      `${this.#baseUrl}/vendors/${encodeURIComponent(vendorId)}`,
      body,
    );
  }

  delete(vendorId: string): Observable<VendorMutationResultDto> {
    return this.#http.delete<VendorMutationResultDto>(
      `${this.#baseUrl}/vendors/${encodeURIComponent(vendorId)}`,
    );
  }
}
