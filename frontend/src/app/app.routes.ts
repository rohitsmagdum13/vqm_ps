import type { Routes } from '@angular/router';
import {
  designAdminApp,
  designAuthGuard,
  designHomeRedirect,
  designVendorOnly,
} from './vqms/services/auth.guard';

export const routes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    canActivate: [designHomeRedirect],
    children: [],
  },
  {
    path: 'login',
    loadComponent: () =>
      import('./vqms/screens/login.page').then((m) => m.LoginPage),
  },
  {
    path: 'portal',
    canActivate: [designAuthGuard, designVendorOnly],
    loadComponent: () =>
      import('./vqms/screens/portal.page').then((m) => m.PortalPage),
  },
  {
    path: 'app',
    canActivate: [designAuthGuard, designAdminApp],
    loadComponent: () => import('./vqms/shell/shell').then((m) => m.Shell),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'overview' },
      {
        path: 'overview',
        loadComponent: () =>
          import('./vqms/screens/overview.page').then((m) => m.OverviewPage),
      },
      {
        path: 'inbox',
        loadComponent: () =>
          import('./vqms/screens/inbox.page').then((m) => m.InboxPage),
      },
      {
        path: 'triage',
        loadComponent: () =>
          import('./vqms/screens/triage.page').then((m) => m.TriagePage),
      },
      {
        path: 'vendors',
        loadComponent: () =>
          import('./vqms/screens/vendors.page').then((m) => m.VendorsPage),
      },
      {
        path: 'vendors/:vendorId',
        loadComponent: () =>
          import('./vqms/screens/vendor-360.page').then((m) => m.Vendor360Page),
      },
      {
        path: 'email',
        loadComponent: () =>
          import('./vqms/screens/email.page').then((m) => m.EmailPage),
      },
      {
        path: 'mail',
        loadComponent: () =>
          import('./vqms/screens/mail.page').then((m) => m.MailPage),
      },
      {
        path: 'kb',
        loadComponent: () =>
          import('./vqms/screens/kb.page').then((m) => m.KbPage),
      },
      {
        path: 'bulk',
        loadComponent: () =>
          import('./vqms/screens/bulk.page').then((m) => m.BulkPage),
      },
      {
        path: 'audit',
        loadComponent: () =>
          import('./vqms/screens/audit.page').then((m) => m.AuditPage),
      },
      {
        path: 'admin',
        loadComponent: () =>
          import('./vqms/screens/admin.page').then((m) => m.AdminPage),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
