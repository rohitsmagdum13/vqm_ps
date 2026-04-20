import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { AuthService } from '../../auth/auth.service';
import { UserMenu } from '../user-menu/user-menu';
import type { NavItem } from '../../../shared/models/nav';

const VENDOR_NAV: readonly NavItem[] = [
  { id: 'portal', route: '/portal', lbl: 'My Portal', ico: '🏠', badge: null },
  { id: 'wizard', route: '/wizard', lbl: 'New Query', ico: '✏️', badge: null },
  { id: 'queries', route: '/queries', lbl: 'My Queries', ico: '📋', badge: '6' },
  { id: 'prefs', route: '/preferences', lbl: 'Preferences', ico: '⚙️', badge: null },
];

const ADMIN_NAV: readonly NavItem[] = [
  { id: 'admin-dash', route: '/admin', lbl: 'Dashboard', ico: '📊', badge: null, exact: true },
  { id: 'admin-vendors', route: '/admin/vendors', lbl: 'Vendors', ico: '🏭', badge: null },
  { id: 'queries', route: '/queries', lbl: 'All Queries', ico: '📋', badge: '12' },
  { id: 'email', route: '/email', lbl: 'Email', ico: '✉️', badge: null },
  { id: 'prefs', route: '/preferences', lbl: 'Settings', ico: '⚙️', badge: null },
];

@Component({
  selector: 'app-top-nav',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, RouterLinkActive, UserMenu],
  template: `
    <header
      class="h-14 bg-surface border-b border-border-light flex items-center px-6 gap-6 sticky top-0 z-40 shadow-sm"
    >
      <div class="flex items-center gap-2 font-semibold text-fg tracking-tight">
        <span
          class="h-8 w-8 rounded-[var(--radius-sm)] grid place-items-center bg-primary text-surface font-mono text-xs"
        >VQ</span>
        <span class="hidden sm:inline">VQMS</span>
      </div>

      <nav class="flex-1 flex items-center gap-1 overflow-x-auto" role="navigation">
        @for (item of items(); track item.id) {
          <a
            [routerLink]="item.route"
            routerLinkActive="!text-primary !bg-primary/8 !border-primary/20"
            [routerLinkActiveOptions]="{ exact: !!item.exact }"
            class="flex items-center gap-2 px-3 py-1.5 rounded-[var(--radius-sm)] text-sm font-medium text-fg-dim hover:text-fg hover:bg-surface-2 border border-transparent transition whitespace-nowrap"
          >
            <span aria-hidden="true">{{ item.ico }}</span>
            <span>{{ item.lbl }}</span>
            @if (item.badge) {
              <span
                class="ml-1 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-primary/10 text-primary text-[10px] font-mono"
              >{{ item.badge }}</span>
            }
          </a>
        }
      </nav>

      <app-user-menu />
    </header>
  `,
})
export class TopNav {
  readonly #auth = inject(AuthService);

  protected readonly items = computed<readonly NavItem[]>(() =>
    this.#auth.role() === 'admin' ? ADMIN_NAV : VENDOR_NAV,
  );
}
