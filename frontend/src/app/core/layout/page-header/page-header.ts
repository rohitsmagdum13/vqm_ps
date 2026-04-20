import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router } from '@angular/router';
import { filter, map, startWith } from 'rxjs/operators';
import { AuthService } from '../../auth/auth.service';

type ScreenKey =
  | 'portal'
  | 'admin'
  | 'wizard'
  | 'queries'
  | 'queries-detail'
  | 'email'
  | 'preferences';

interface PageMeta {
  readonly title: string;
  readonly crumb: string;
}

function firstSegment(url: string): string {
  const clean = url.split('?')[0].split('#')[0];
  const parts = clean.split('/').filter(Boolean);
  return parts[0] ?? '';
}

function isDetailRoute(url: string): boolean {
  const clean = url.split('?')[0].split('#')[0];
  const parts = clean.split('/').filter(Boolean);
  return parts[0] === 'queries' && parts.length >= 2;
}

function screenKey(url: string, role: 'vendor' | 'admin'): ScreenKey {
  const seg = firstSegment(url);
  if (isDetailRoute(url)) return 'queries-detail';
  switch (seg) {
    case 'admin':
      return 'admin';
    case 'wizard':
      return 'wizard';
    case 'queries':
      return 'queries';
    case 'email':
      return 'email';
    case 'preferences':
      return 'preferences';
    default:
      return role === 'admin' ? 'admin' : 'portal';
  }
}

const TITLE: Readonly<Record<ScreenKey, (role: 'vendor' | 'admin') => string>> = {
  portal: () => 'My Portal',
  admin: () => 'Dashboard',
  wizard: () => 'New Query',
  queries: (r) => (r === 'admin' ? 'All Queries' : 'My Queries'),
  'queries-detail': () => 'Query Detail',
  email: () => 'Email',
  preferences: (r) => (r === 'admin' ? 'Settings' : 'Preferences'),
};

const CRUMB_LEAF: Readonly<Record<ScreenKey, (role: 'vendor' | 'admin') => string>> = {
  portal: () => 'home',
  admin: () => 'dashboard',
  wizard: () => 'new-query',
  queries: () => 'queries',
  'queries-detail': () => 'queries / detail',
  email: () => 'email',
  preferences: (r) => (r === 'admin' ? 'settings' : 'preferences'),
};

@Component({
  selector: 'app-page-header',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="flex items-end justify-between gap-4 pb-4 mb-4 border-b border-border-light">
      <div>
        <h1 class="text-xl font-semibold text-fg tracking-tight">{{ meta().title }}</h1>
        <div class="text-[11px] font-mono text-fg-dim uppercase tracking-wider mt-1">
          {{ meta().crumb }}
        </div>
      </div>
    </div>
  `,
})
export class PageHeader {
  readonly #router = inject(Router);
  readonly #auth = inject(AuthService);

  readonly #url = toSignal(
    this.#router.events.pipe(
      filter((e): e is NavigationEnd => e instanceof NavigationEnd),
      map((e) => e.urlAfterRedirects),
      startWith(this.#router.url),
    ),
    { initialValue: this.#router.url },
  );

  protected readonly meta = computed<PageMeta>(() => {
    const role = this.#auth.role();
    const key = screenKey(this.#url(), role);
    const title = TITLE[key](role);
    const crumb = `vqms / ${role} / ${CRUMB_LEAF[key](role)}`;
    return { title, crumb };
  });
}
