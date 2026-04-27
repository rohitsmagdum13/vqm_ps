import { Injectable, computed, inject, signal } from '@angular/core';
import { type Observable, firstValueFrom, map, tap } from 'rxjs';
import { USERS } from '../../data/users.data';
import {
  type AuthSession,
  type Role,
  type User,
  mapBackendRole,
} from '../../shared/models/user';
import { AuthApi, type LoginResponseDto } from './auth.api';

const STORAGE_KEY = 'vqms.session';

@Injectable({ providedIn: 'root' })
export class AuthService {
  readonly #api = inject(AuthApi);

  readonly #session = signal<AuthSession | null>(this.#loadFromStorage());

  readonly session = this.#session.asReadonly();
  readonly token = computed<string | null>(() => this.#session()?.token ?? null);
  readonly isAuthed = computed<boolean>(() => this.#session() !== null);
  readonly role = computed<Role>(() => {
    const s = this.#session();
    if (!s) return 'vendor';
    return mapBackendRole(s.role) ?? 'vendor';
  });
  readonly vendorId = computed<string | null>(() => this.#session()?.vendorId ?? null);

  readonly user = computed<User>(() => {
    const s = this.#session();
    const fallbackRole = this.role();
    const fallback = USERS[fallbackRole];
    if (!s) return fallback;
    const ini = this.#initials(s.userName);
    return {
      name: s.userName,
      ini,
      company: s.tenant,
      role: `${s.role} · ${s.tenant}`,
      email: s.email,
    };
  });

  loginWithCredentials(
    email: string,
    password: string,
    expectedRole: Role,
  ): Observable<AuthSession> {
    return this.#api.login({ username_or_email: email, password }).pipe(
      map((dto) => this.#toSession(dto)),
      tap((session) => {
        const mapped = mapBackendRole(session.role);
        if (mapped === null) {
          throw new Error(`Role ${session.role} is not supported by this portal`);
        }
        if (mapped !== expectedRole) {
          throw new Error(
            `This account is a ${mapped}. Please use the ${mapped} tab to sign in.`,
          );
        }
        this.#persist(session);
        this.#session.set(session);
      }),
    );
  }

  async logout(): Promise<void> {
    const token = this.token();
    if (token) {
      try {
        await firstValueFrom(this.#api.logout(token));
      } catch {
        // Swallow — we still want to clear local state even if server call fails
      }
    }
    this.#clearStorage();
    this.#session.set(null);
  }

  updateToken(newToken: string): void {
    const current = this.#session();
    if (!current) return;
    const next: AuthSession = { ...current, token: newToken };
    this.#persist(next);
    this.#session.set(next);
  }

  /** Build a Router path that respects the role-based URL shape.
   *
   * Vendor pages live under `/:vendorId/...` so each query, wizard
   * step, etc. is scoped to the logged-in vendor in the URL bar.
   * Admin pages keep the flat `/admin/...` shape. This helper hides
   * that branching from callers — they pass the segments after the
   * vendor prefix and get a path Angular's Router can navigate to.
   *
   * Examples:
   *   role=vendor, vendorId=V-001, path=['queries']  -> ['/', 'V-001', 'queries']
   *   role=admin,                  path=['queries']  -> ['/', 'queries']
   */
  vendorPath(...segments: string[]): string[] {
    const trimmed = segments.filter((s) => s !== '');
    if (this.role() === 'vendor') {
      const vid = this.vendorId();
      if (vid) return ['/', vid, ...trimmed];
    }
    return ['/', ...trimmed];
  }

  /** Where to land the user after login or when they hit the root URL.
   *
   * Vendor → `/:vendorId/portal`; admin → `/admin`; signed-out fallback
   * → `/login`. Returned as a string array ready for Router.navigate().
   */
  homePath(): string[] {
    if (this.role() === 'admin') return ['/', 'admin'];
    const vid = this.vendorId();
    if (vid) return ['/', vid, 'portal'];
    return ['/', 'login'];
  }

  #toSession(dto: LoginResponseDto): AuthSession {
    return {
      token: dto.token,
      userName: dto.user_name,
      email: dto.email,
      role: dto.role,
      tenant: dto.tenant,
      vendorId: dto.vendor_id,
    };
  }

  #persist(session: AuthSession): void {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    } catch {
      // localStorage unavailable (private mode / quota) — session still held in memory
    }
  }

  #clearStorage(): void {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // noop
    }
  }

  #loadFromStorage(): AuthSession | null {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw) as unknown;
      if (!this.#isSession(parsed)) return null;
      return parsed;
    } catch {
      return null;
    }
  }

  #isSession(value: unknown): value is AuthSession {
    if (!value || typeof value !== 'object') return false;
    const v = value as Record<string, unknown>;
    return (
      typeof v['token'] === 'string' &&
      typeof v['userName'] === 'string' &&
      typeof v['email'] === 'string' &&
      typeof v['role'] === 'string' &&
      typeof v['tenant'] === 'string' &&
      (v['vendorId'] === null || typeof v['vendorId'] === 'string')
    );
  }

  #initials(name: string): string {
    const parts = name.trim().split(/\s+/).filter(Boolean);
    if (parts.length === 0) return '??';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }
}
