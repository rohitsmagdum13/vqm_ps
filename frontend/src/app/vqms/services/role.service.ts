import { Injectable, computed, signal } from '@angular/core';

export type Role = 'Admin' | 'Reviewer' | 'Vendor';

export interface Capabilities {
  readonly approve: boolean;
  readonly reroute: boolean;
  readonly escalate: boolean;
  readonly bulk: boolean;
  readonly editVendor: boolean;
  readonly manageUsers: boolean;
  readonly toggleFlags: boolean;
  readonly forceClose: boolean;
  readonly copilot: boolean;
  readonly triageDecide: boolean;
}

const CAPS: Readonly<Record<Role, Capabilities>> = {
  Admin: {
    approve: true,
    reroute: true,
    escalate: true,
    bulk: true,
    editVendor: true,
    manageUsers: true,
    toggleFlags: true,
    forceClose: true,
    copilot: true,
    triageDecide: true,
  },
  Reviewer: {
    approve: false,
    reroute: false,
    escalate: false,
    bulk: false,
    editVendor: false,
    manageUsers: false,
    toggleFlags: false,
    forceClose: false,
    copilot: true,
    triageDecide: true,
  },
  Vendor: {
    approve: false,
    reroute: false,
    escalate: false,
    bulk: false,
    editVendor: false,
    manageUsers: false,
    toggleFlags: false,
    forceClose: false,
    copilot: false,
    triageDecide: false,
  },
};

const ROLE_NAV: Readonly<Record<Role, readonly string[]>> = {
  Admin: ['overview', 'inbox', 'mail', 'triage', 'vendors', 'email', 'kb', 'bulk', 'audit', 'admin'],
  Reviewer: ['overview', 'triage', 'kb'],
  Vendor: [],
};

const STORAGE_KEY = 'vqms.design.role';

@Injectable({ providedIn: 'root' })
export class RoleService {
  readonly #role = signal<Role>(this.#load());

  readonly role = this.#role.asReadonly();
  readonly caps = computed<Capabilities>(() => CAPS[this.#role()]);
  readonly allowed = computed<readonly string[]>(() => ROLE_NAV[this.#role()]);

  setRole(role: Role): void {
    this.#role.set(role);
    try {
      localStorage.setItem(STORAGE_KEY, role);
    } catch {
      // storage unavailable
    }
  }

  canAccess(view: string): boolean {
    return this.allowed().includes(view);
  }

  #load(): Role {
    try {
      const v = localStorage.getItem(STORAGE_KEY);
      if (v === 'Admin' || v === 'Reviewer' || v === 'Vendor') return v;
    } catch {
      // ignore
    }
    return 'Admin';
  }
}
