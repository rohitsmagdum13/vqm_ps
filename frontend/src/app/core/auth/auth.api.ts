import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import type { BackendRole } from '../../shared/models/user';

export interface LoginRequestDto {
  readonly username_or_email: string;
  readonly password: string;
}

export interface LoginResponseDto {
  readonly token: string;
  readonly user_name: string;
  readonly email: string;
  readonly role: BackendRole;
  readonly tenant: string;
  readonly vendor_id: string | null;
}

export interface LogoutResponseDto {
  readonly message: string;
}

@Injectable({ providedIn: 'root' })
export class AuthApi {
  readonly #http = inject(HttpClient);
  readonly #baseUrl = environment.apiBaseUrl;

  login(body: LoginRequestDto): Observable<LoginResponseDto> {
    return this.#http.post<LoginResponseDto>(`${this.#baseUrl}/auth/login`, body);
  }

  logout(token: string): Observable<LogoutResponseDto> {
    const headers = new HttpHeaders({ Authorization: `Bearer ${token}` });
    return this.#http.post<LogoutResponseDto>(`${this.#baseUrl}/auth/logout`, null, { headers });
  }
}
