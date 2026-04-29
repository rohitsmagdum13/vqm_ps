import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { AuthApi, type BackendRole, type LoginResponseDto } from './auth.api';
import type { Role } from './role.service';

const STORAGE_KEY = 'vqms.design.session';

interface DesignSession {
  readonly authed: boolean;
  readonly token: string | null;
  readonly role: Role;
  readonly backendRole: BackendRole | null;
  readonly userName: string;
  readonly email: string;
  readonly tenant: string;
  readonly vendorId: string | null;
  readonly vendorName: string | null;
}

const DEFAULT: DesignSession = {
  authed: false,
  token: null,
  role: 'Admin',
  backendRole: null,
  userName: 'Anika Verma',
  email: 'anika.verma@hexaware.com',
  tenant: 'hexaware',
  vendorId: null,
  vendorName: null,
};

const ROLE_MAP: Readonly<Record<BackendRole, Role>> = {
  ADMIN: 'Admin',
  REVIEWER: 'Reviewer',
  VENDOR: 'Vendor',
};

@Injectable({ providedIn: 'root' })
export class SessionService {
  readonly #api = inject(AuthApi);
  readonly #session = signal<DesignSession>(this.#load());

  readonly session = this.#session.asReadonly();
  readonly authed = computed<boolean>(() => this.#session().authed);
  readonly token = computed<string | null>(() => this.#session().token);
  readonly role = computed<Role>(() => this.#session().role);
  readonly userName = computed<string>(() => this.#session().userName);
  readonly email = computed<string>(() => this.#session().email);
  readonly vendorId = computed<string | null>(() => this.#session().vendorId);
  readonly vendorName = computed<string | null>(() => this.#session().vendorName);

  /**
   * Authenticate against POST /auth/login. Throws if credentials reject,
   * the network is unreachable, or the backend role differs from the
   * role the user picked (matches the validation in the legacy AuthService).
   */
  async loginWithCredentials(
    usernameOrEmail: string,
    password: string,
    expectedRole: Role,
  ): Promise<DesignSession> {
    let dto: LoginResponseDto;
    try {
      dto = await firstValueFrom(
        this.#api.login({ username_or_email: usernameOrEmail, password }),
      );
    } catch (err: unknown) {
      throw new Error(this.#humanizeError(err));
    }

    const mappedRole = ROLE_MAP[dto.role];
    if (!mappedRole) {
      throw new Error(`Role ${dto.role} is not supported by this portal`);
    }
    if (mappedRole !== expectedRole) {
      throw new Error(
        `This account is a ${mappedRole}. Please pick the ${mappedRole} role to sign in.`,
      );
    }

    const session: DesignSession = {
      authed: true,
      token: dto.token,
      role: mappedRole,
      backendRole: dto.role,
      userName: dto.full_name ?? dto.user_name,
      email: dto.email,
      tenant: dto.tenant,
      vendorId: dto.vendor_id,
      vendorName: dto.vendor_id ? dto.full_name ?? dto.user_name : null,
    };
    this.#session.set(session);
    this.#persist(session);
    return session;
  }

  /**
   * Hits POST /auth/logout to blacklist the token, then clears local
   * state. Network failures are swallowed — local sign-out always
   * proceeds so a flaky backend can't trap a user in a stale session.
   */
  async signOutAsync(): Promise<void> {
    const token = this.token();
    if (token) {
      try {
        await firstValueFrom(this.#api.logout(token));
      } catch {
        // Swallow — clearing local state is the priority.
      }
    }
    this.#clear();
  }

  /** Replace the JWT in place — used by the auth interceptor when the
   * server hands back an X-New-Token refresh header. */
  updateToken(newToken: string): void {
    const cur = this.#session();
    if (!cur.authed) return;
    const next: DesignSession = { ...cur, token: newToken };
    this.#session.set(next);
    this.#persist(next);
  }

  /** Local-only sign out used by the auth interceptor on 401 — does NOT
   * call /auth/logout (the token is already invalid server-side). */
  forceSignOut(): void {
    this.#clear();
  }

  #clear(): void {
    this.#session.set(DEFAULT);
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
  }

  #humanizeError(err: unknown): string {
    if (err instanceof HttpErrorResponse) {
      if (err.status === 0) {
        return 'Cannot reach the server. Is the backend running on the configured port?';
      }
      if (err.status === 401) {
        const detail =
          err.error && typeof err.error === 'object' && 'detail' in err.error
            ? String((err.error as { detail: unknown }).detail)
            : 'Invalid credentials.';
        return detail;
      }
      return `Login failed (${err.status}).`;
    }
    if (err instanceof Error) return err.message;
    return 'Unexpected error during sign in.';
  }

  #load(): DesignSession {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return DEFAULT;
      const parsed = JSON.parse(raw) as Partial<DesignSession>;
      if (
        parsed &&
        typeof parsed === 'object' &&
        parsed.authed === true &&
        typeof parsed.token === 'string' &&
        (parsed.role === 'Admin' || parsed.role === 'Reviewer' || parsed.role === 'Vendor')
      ) {
        return { ...DEFAULT, ...parsed } as DesignSession;
      }
    } catch {
      // ignore
    }
    return DEFAULT;
  }

  #persist(s: DesignSession): void {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
    } catch {
      // ignore
    }
  }
}
