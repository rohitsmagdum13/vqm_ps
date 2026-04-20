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
        path: 'queries',
        loadComponent: () => import('./features/queries/queries.page').then((m) => m.QueriesPage),
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
        canActivate: [vendorOnly],
        loadComponent: () => import('./features/wizard/wizard.page').then((m) => m.WizardPage),
      },
      {
        path: 'email',
        canActivate: [adminOnly],
        loadComponent: () => import('./features/email/email.page').then((m) => m.EmailPage),
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
