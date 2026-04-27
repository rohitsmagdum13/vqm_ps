import type { Routes } from '@angular/router';
import { adminOnly, authGuard, homeRedirect, vendorOnly } from './core/auth/auth.guard';

/**
 * URL shape:
 *   /login                     — public login page
 *   /admin                     — admin dashboard (and /admin/* for sub-pages)
 *   /preferences               — both roles
 *   /:vendorId/portal          — vendor home (e.g. /V-001/portal)
 *   /:vendorId/queries         — vendor's queries list
 *   /:vendorId/queries/:id     — vendor's query detail
 *   /:vendorId/wizard          — new-query wizard
 *
 * The `vendorOnly` guard enforces that `:vendorId` matches the
 * session's vendor — a vendor cannot read another vendor's data by
 * URL-typing.
 */
export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () => import('./features/login/login.page').then((m) => m.LoginPage),
  },
  {
    path: '',
    canActivate: [authGuard],
    loadComponent: () => import('./core/layout/shell/shell').then((m) => m.Shell),
    children: [
      // Empty path — pick the right home based on role.
      { path: '', pathMatch: 'full', canActivate: [homeRedirect], children: [] },

      // Preferences is shared between roles, no vendor prefix needed.
      {
        path: 'preferences',
        loadComponent: () =>
          import('./features/preferences/preferences.page').then((m) => m.PreferencesPage),
      },

      // ── Admin routes (flat, no vendor prefix) ────────────────────
      {
        path: 'admin',
        canActivate: [adminOnly],
        loadComponent: () =>
          import('./features/admin-dashboard/admin-dashboard.page').then(
            (m) => m.AdminDashboardPage,
          ),
      },
      {
        path: 'admin/vendors',
        canActivate: [adminOnly],
        loadComponent: () =>
          import('./features/admin-vendors/admin-vendors.page').then((m) => m.AdminVendorsPage),
      },
      {
        path: 'admin/queries',
        canActivate: [adminOnly],
        loadComponent: () => import('./features/queries/queries.page').then((m) => m.QueriesPage),
      },
      {
        path: 'admin/queries/:id',
        canActivate: [adminOnly],
        loadComponent: () =>
          import('./features/queries/detail-panel/query-detail.page').then(
            (m) => m.QueryDetailPage,
          ),
      },
      {
        path: 'admin/email',
        canActivate: [adminOnly],
        loadComponent: () => import('./features/email/email.page').then((m) => m.EmailPage),
      },
      {
        path: 'admin/triage',
        canActivate: [adminOnly],
        loadComponent: () =>
          import('./features/admin-triage/admin-triage.page').then((m) => m.AdminTriagePage),
      },
      {
        path: 'admin/triage/:id',
        canActivate: [adminOnly],
        loadComponent: () =>
          import('./features/admin-triage/triage-detail.page').then((m) => m.TriageDetailPage),
      },
      {
        path: 'admin/path-b',
        canActivate: [adminOnly],
        loadComponent: () =>
          import('./features/admin-path-b/admin-path-b.page').then((m) => m.AdminPathBPage),
      },
      {
        path: 'admin/path-b/:id',
        canActivate: [adminOnly],
        loadComponent: () =>
          import('./features/admin-path-b/investigation-detail.page').then(
            (m) => m.InvestigationDetailPage,
          ),
      },
      {
        path: 'admin/draft-approvals',
        canActivate: [adminOnly],
        loadComponent: () =>
          import('./features/admin-drafts/admin-drafts.page').then((m) => m.AdminDraftsPage),
      },
      {
        path: 'admin/draft-approvals/:id',
        canActivate: [adminOnly],
        loadComponent: () =>
          import('./features/admin-drafts/draft-detail.page').then((m) => m.DraftDetailPage),
      },
      {
        path: 'admin/ops',
        canActivate: [adminOnly],
        loadComponent: () =>
          import('./features/admin-ops/admin-ops.page').then((m) => m.AdminOpsPage),
      },

      // ── Vendor routes (scoped under /:vendorId) ──────────────────
      // The :vendorId segment lives in the URL bar so a vendor can
      // see their identity at a glance. The `vendorOnly` guard
      // verifies the segment matches the session and rejects any
      // foreign-vendor URL with a redirect.
      {
        path: ':vendorId',
        canActivate: [vendorOnly],
        children: [
          { path: '', pathMatch: 'full', redirectTo: 'portal' },
          {
            path: 'portal',
            loadComponent: () =>
              import('./features/portal/portal.page').then((m) => m.PortalPage),
          },
          {
            path: 'queries',
            loadComponent: () =>
              import('./features/queries/queries.page').then((m) => m.QueriesPage),
          },
          {
            path: 'queries/:id',
            loadComponent: () =>
              import('./features/queries/detail-panel/query-detail.page').then(
                (m) => m.QueryDetailPage,
              ),
          },
          {
            path: 'wizard',
            loadComponent: () =>
              import('./features/wizard/wizard.page').then((m) => m.WizardPage),
          },
        ],
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
