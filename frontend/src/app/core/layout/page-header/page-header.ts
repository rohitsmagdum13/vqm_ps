import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router } from '@angular/router';
import { filter, map, startWith } from 'rxjs/operators';
import { AuthService } from '../../auth/auth.service';

type ScreenKey =
  | 'portal'
  | 'admin'
  | 'admin-vendors'
  | 'admin-triage'
  | 'admin-triage-detail'
  | 'admin-path-b'
  | 'admin-path-b-detail'
  | 'admin-drafts'
  | 'admin-drafts-detail'
  | 'admin-ops'
  | 'wizard'
  | 'queries'
  | 'queries-detail'
  | 'email'
  | 'preferences';

interface PageMeta {
  readonly title: string;
  readonly crumb: string;
}

function pathSegments(url: string): readonly string[] {
  const clean = url.split('?')[0].split('#')[0];
  return clean.split('/').filter(Boolean);
}

function isDetailRoute(url: string): boolean {
  const parts = pathSegments(url);
  // /queries/:id  or  /admin/queries/:id
  if (parts[0] === 'queries' && parts.length >= 2) return true;
  if (parts[0] === 'admin' && parts[1] === 'queries' && parts.length >= 3) return true;
  return false;
}

function screenKey(url: string, role: 'vendor' | 'admin'): ScreenKey {
  const parts = pathSegments(url);
  if (isDetailRoute(url)) return 'queries-detail';

  // Admin-prefixed routes
  if (parts[0] === 'admin') {
    const isDetail = parts.length >= 3;
    switch (parts[1]) {
      case undefined:
        return 'admin';
      case 'vendors':
        return 'admin-vendors';
      case 'queries':
        return 'queries';
      case 'email':
        return 'email';
      case 'triage':
        return isDetail ? 'admin-triage-detail' : 'admin-triage';
      case 'path-b':
        return isDetail ? 'admin-path-b-detail' : 'admin-path-b';
      case 'draft-approvals':
        return isDetail ? 'admin-drafts-detail' : 'admin-drafts';
      case 'ops':
        return 'admin-ops';
      default:
        return 'admin';
    }
  }

  switch (parts[0]) {
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
  'admin-vendors': () => 'Vendor Accounts',
  'admin-triage': () => 'Triage Queue',
  'admin-triage-detail': () => 'Triage Detail',
  'admin-path-b': () => 'Investigations',
  'admin-path-b-detail': () => 'Investigation Detail',
  'admin-drafts': () => 'Draft Approvals',
  'admin-drafts-detail': () => 'Draft Detail',
  'admin-ops': () => 'Operations',
  wizard: () => 'New Query',
  queries: (r) => (r === 'admin' ? 'All Queries' : 'My Queries'),
  'queries-detail': () => 'Query Detail',
  email: () => 'Email',
  preferences: (r) => (r === 'admin' ? 'Settings' : 'Preferences'),
};

const CRUMB_LEAF: Readonly<Record<ScreenKey, (role: 'vendor' | 'admin') => string>> = {
  portal: () => 'home',
  admin: () => 'dashboard',
  'admin-vendors': () => 'vendors',
  'admin-triage': () => 'triage',
  'admin-triage-detail': () => 'triage / detail',
  'admin-path-b': () => 'investigations',
  'admin-path-b-detail': () => 'investigations / detail',
  'admin-drafts': () => 'drafts',
  'admin-drafts-detail': () => 'drafts / detail',
  'admin-ops': () => 'ops',
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
