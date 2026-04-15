import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { Observable, tap } from 'rxjs';
import { environment } from '../../environments/environment';

interface LoginResponse {
  token: string;
  user_name: string;
  email: string;
  role: string;
  tenant: string;
  vendor_id: string | null;
}

const STORAGE_KEY = 'vqms_auth';

@Injectable({ providedIn: 'root' })
export class AuthService {
  constructor(private http: HttpClient, private router: Router) {}

  login(usernameOrEmail: string, password: string): Observable<LoginResponse> {
    return this.http
      .post<LoginResponse>(`${environment.apiUrl}/auth/login`, {
        username_or_email: usernameOrEmail,
        password: password,
      })
      .pipe(
        tap((response) => {
          localStorage.setItem(STORAGE_KEY, JSON.stringify(response));
        })
      );
  }

  logout(): void {
    const token = this.getToken();
    if (token) {
      // Fire-and-forget — blacklist the token on the server
      this.http
        .post(`${environment.apiUrl}/auth/logout`, {}, {
          headers: { Authorization: `Bearer ${token}` },
        })
        .subscribe({ error: () => {} });
    }
    localStorage.removeItem(STORAGE_KEY);
    this.router.navigate(['/login']);
  }

  getToken(): string | null {
    const data = this.getStoredAuth();
    return data?.token ?? null;
  }

  /** Returns vendor_id if set, otherwise falls back to tenant */
  getVendorId(): string | null {
    const data = this.getStoredAuth();
    if (!data) return null;
    return data.vendor_id || data.tenant;
  }

  getEmail(): string | null {
    const data = this.getStoredAuth();
    return data?.email ?? null;
  }

  getUserName(): string | null {
    const data = this.getStoredAuth();
    return data?.user_name ?? null;
  }

  getRole(): string | null {
    const data = this.getStoredAuth();
    return data?.role ?? null;
  }

  isLoggedIn(): boolean {
    const token = this.getToken();
    if (!token) return false;

    // Decode JWT to check expiry (JWT is base64url-encoded)
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      const now = Math.floor(Date.now() / 1000);
      return payload.exp > now;
    } catch {
      return false;
    }
  }

  /** Called by token-refresh interceptor when backend sends X-New-Token */
  updateToken(newToken: string): void {
    const data = this.getStoredAuth();
    if (data) {
      data.token = newToken;
      localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
    }
  }

  private getStoredAuth(): LoginResponse | null {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }
}
