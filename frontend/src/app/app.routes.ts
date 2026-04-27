import type { Routes } from '@angular/router';
import { adminOnly, authGuard, vendorOnly } from './core/auth/auth.guard';

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
      { path: '', redirectTo: 'portal', pathMatch: 'full' },
      {
        path: 'portal',
        canActivate: [vendorOnly],
        loadComponent: () => import('./features/portal/portal.page').then((m) => m.PortalPage),
      },
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
          import('./features/admin-vendors/admin-vendors.page').then(
            (m) => m.AdminVendorsPage,
          ),
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
      {
        path: 'queries',
        canActivate: [vendorOnly],
        loadComponent: () => import('./features/queries/queries.page').then((m) => m.QueriesPage),
      },
      {
        path: 'queries/:id',
        canActivate: [vendorOnly],
        loadComponent: () =>
          import('./features/queries/detail-panel/query-detail.page').then(
            (m) => m.QueryDetailPage,
          ),
      },
      {
        path: 'wizard',
        canActivate: [vendorOnly],
        loadComponent: () => import('./features/wizard/wizard.page').then((m) => m.WizardPage),
      },
      {
        path: 'preferences',
        loadComponent: () =>
          import('./features/preferences/preferences.page').then((m) => m.PreferencesPage),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
