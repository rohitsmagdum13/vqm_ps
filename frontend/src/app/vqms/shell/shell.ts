import {
  ChangeDetectionStrategy,
  Component,
  HostListener,
  computed,
  inject,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterOutlet, type Event as RouterEvent } from '@angular/router';
import { filter, map, startWith } from 'rxjs/operators';
import { Icon } from '../ui/icon';
import { Logo } from '../ui/logo';
import { Mono } from '../ui/mono';
import { Avatar } from '../ui/avatar';
import { Forbidden } from '../ui/forbidden';
import { CommandPalette } from './command-palette';
import { QueryDetailDrawer } from '../screens/query-detail-drawer';
import { NAV } from './nav';
import { DrawerService } from '../services/drawer.service';
import { QueriesStore } from '../services/queries.store';
import { RoleService } from '../services/role.service';
import { SessionService } from '../services/session.service';
import { ThemeService } from '../services/theme.service';

@Component({
  selector: 'vq-shell',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterOutlet,
    Icon,
    Logo,
    Mono,
    Avatar,
    Forbidden,
    CommandPalette,
    QueryDetailDrawer,
  ],
  template: `
    <div class="flex h-screen overflow-hidden">
      <!-- Sidebar -->
      <aside
        class="flex flex-col border-r hairline"
        style="width: 232px; background: var(--panel);"
      >
        <div class="px-4 py-4 border-b hairline">
          <div class="flex items-center gap-2">
            <vq-logo [size]="22" />
            <span class="ink" style="font-size:14px; font-weight:600; letter-spacing:-.01em;">VQMS</span>
            <vq-mono [size]="10" cssClass="muted ml-auto">v0.7.4</vq-mono>
          </div>
          <div class="muted mt-2" style="font-size:10.5px; letter-spacing:.06em; text-transform:uppercase;">
            Hexaware · prod
          </div>
        </div>

        <div class="p-3">
          <button
            class="w-full flex items-center gap-2 px-2.5 py-1.5"
            style="background: var(--bg); border: 1px solid var(--line); border-radius: 4px; font-size: 12px; color: var(--muted); cursor: pointer;"
            (click)="openPalette()"
          >
            <vq-icon name="search" [size]="13" />
            <span>Search…</span>
            <vq-mono [size]="10" cssClass="ml-auto">⌘K</vq-mono>
          </button>
        </div>

        <nav class="flex-1 px-2 overflow-y-auto">
          @for (n of navItems(); track n.id) {
            <div
              class="nav-item"
              [class.active]="activeId() === n.id"
              (click)="go(n.route)"
            >
              <vq-icon [name]="n.icon" [size]="14" />
              <span class="flex-1">{{ n.label }}</span>
              @if (badgeFor(n.id) > 0) {
                <span
                  class="mono"
                  [style.background]="activeId() === n.id ? 'var(--accent)' : 'var(--line)'"
                  [style.color]="activeId() === n.id ? 'white' : 'var(--muted)'"
                  style="font-size: 10.5px; padding: 1px 6px; border-radius: 999px;"
                >{{ badgeFor(n.id) }}</span>
              }
            </div>
          }
        </nav>

        <div class="p-3 border-t hairline">
          <div class="flex items-center gap-2">
            <vq-avatar [name]="userName()" [size]="28" />
            <div class="flex-1 min-w-0">
              <div class="ink truncate" style="font-size:12.5px; font-weight:500;">{{ userName() }}</div>
              <vq-mono [size]="10" cssClass="muted">{{ role() }}</vq-mono>
            </div>
            <button class="btn btn-ghost" (click)="toggleDark()" title="Toggle dark mode">
              <vq-icon [name]="dark() ? 'sun' : 'moon'" [size]="13" />
            </button>
          </div>
        </div>
      </aside>

      <!-- Main -->
      <main class="flex-1 flex flex-col overflow-hidden">
        <div
          class="flex items-center justify-between px-6 py-2.5 border-b hairline"
          style="background: var(--panel);"
        >
          <div class="flex items-center gap-2 muted" style="font-size:12px;">
            <span class="ink-2">VQMS</span>
            <vq-icon name="chevron-right" [size]="11" />
            <span>{{ breadcrumbLabel() }}</span>
          </div>
          <div class="flex items-center gap-2">
            <span
              class="chip"
              [style.background]="rolePillBg()"
              [style.color]="rolePillFg()"
              [style.border-color]="'transparent'"
            >
              <vq-icon name="user" [size]="10" /> {{ role() }}
            </span>
            <span class="chip">
              <span
                class="pulse-dot"
                style="display:inline-block; width:6px; height:6px; background: var(--ok); border-radius:999px; margin-right:6px;"
              ></span>
              All systems operational
            </span>
            <button class="btn btn-ghost" (click)="openPalette()">
              <vq-icon name="search" [size]="13" />
            </button>
            <button class="btn btn-ghost"><vq-icon name="bell" [size]="13" /></button>
            <button class="btn btn-ghost" (click)="toggleDark()">
              <vq-icon [name]="dark() ? 'sun' : 'moon'" [size]="13" />
            </button>
            <button class="btn btn-ghost" (click)="signOut()" title="Sign out">
              <vq-icon name="log-out" [size]="13" />
            </button>
          </div>
        </div>

        <div class="flex-1 overflow-y-auto bg-bg">
          @if (canAccessActive()) {
            <router-outlet />
          } @else {
            <vq-forbidden [role]="role()" [view]="activeId()" (goHome)="goHome()" />
          }
        </div>
      </main>

      @if (paletteOpen()) {
        <vq-command-palette />
      }

      <vq-query-detail-drawer />
    </div>
  `,
})
export class Shell {
  readonly #role = inject(RoleService);
  readonly #session = inject(SessionService);
  readonly #theme = inject(ThemeService);
  readonly #drawer = inject(DrawerService);
  readonly #router = inject(Router);
  readonly #queries = inject(QueriesStore);

  protected readonly role = this.#role.role;
  protected readonly userName = this.#session.userName;
  protected readonly dark = this.#theme.dark;
  protected readonly paletteOpen = this.#drawer.paletteOpen;

  protected readonly navItems = computed(() => {
    const allowed = this.#role.allowed();
    return NAV.filter((n) => allowed.includes(n.id));
  });

  /**
   * Reactive copy of the current URL — computed signals can't read
   * `Router.url` directly because it isn't a signal, so the active
   * nav highlight would freeze on the URL the page was first rendered
   * with. Subscribing to `NavigationEnd` events via `toSignal` makes
   * the highlight update on every successful navigation.
   */
  readonly #currentUrl = toSignal(
    this.#router.events.pipe(
      filter((e: RouterEvent): e is NavigationEnd => e instanceof NavigationEnd),
      map((e: NavigationEnd) => e.urlAfterRedirects),
      startWith(this.#router.url),
    ),
    { initialValue: this.#router.url },
  );

  protected readonly activeId = computed<string>(() => {
    const url = this.#currentUrl();
    const seg = url.split('/').filter(Boolean);
    return seg[1] ?? 'overview';
  });

  protected readonly canAccessActive = computed<boolean>(() =>
    this.#role.canAccess(this.activeId()),
  );

  protected goHome(): void {
    const allowed = this.#role.allowed();
    const target = allowed[0] ?? 'overview';
    void this.#router.navigate(['/app', target]);
  }

  protected readonly breadcrumbLabel = computed<string>(() => {
    const id = this.activeId();
    return NAV.find((n) => n.id === id)?.label ?? '';
  });

  protected readonly rolePillBg = computed<string>(() => {
    const r = this.role();
    if (r === 'Admin') return 'var(--accent-soft)';
    if (r === 'Reviewer') return 'color-mix(in oklch, var(--info) 12%, var(--panel))';
    return 'var(--bg)';
  });

  protected readonly rolePillFg = computed<string>(() => {
    const r = this.role();
    if (r === 'Admin') return 'var(--accent)';
    if (r === 'Reviewer') return 'var(--info)';
    return 'var(--ink-2)';
  });

  protected badgeFor(id: string): number {
    const item = NAV.find((n) => n.id === id);
    return item?.badge ? item.badge(this.#queries.list()) : 0;
  }

  protected go(path: string): void {
    this.#router.navigateByUrl(path);
  }

  protected toggleDark(): void {
    this.#theme.toggle();
  }

  protected openPalette(): void {
    this.#drawer.showPalette();
  }

  protected async signOut(): Promise<void> {
    await this.#session.signOutAsync();
    void this.#router.navigate(['/login']);
  }

  @HostListener('window:keydown', ['$event'])
  protected onKey(e: KeyboardEvent): void {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      this.#drawer.showPalette();
    }
    if (e.key === 'Escape') {
      this.#drawer.closePalette();
      this.#drawer.closeQuery();
    }
  }
}
