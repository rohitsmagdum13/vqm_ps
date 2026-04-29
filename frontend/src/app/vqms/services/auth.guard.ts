import { inject } from '@angular/core';
import { type CanActivateFn, Router } from '@angular/router';
import { SessionService } from './session.service';

export const designAuthGuard: CanActivateFn = () => {
  const session = inject(SessionService);
  const router = inject(Router);
  if (session.authed()) return true;
  router.navigate(['/login']);
  return false;
};

export const designVendorOnly: CanActivateFn = () => {
  const session = inject(SessionService);
  const router = inject(Router);
  if (!session.authed()) {
    router.navigate(['/login']);
    return false;
  }
  if (session.role() !== 'Vendor') {
    router.navigate(['/app/overview']);
    return false;
  }
  return true;
};

export const designAdminApp: CanActivateFn = () => {
  const session = inject(SessionService);
  const router = inject(Router);
  if (!session.authed()) {
    router.navigate(['/login']);
    return false;
  }
  if (session.role() === 'Vendor') {
    router.navigate(['/portal']);
    return false;
  }
  return true;
};

export const designHomeRedirect: CanActivateFn = () => {
  const session = inject(SessionService);
  const router = inject(Router);
  if (!session.authed()) {
    router.navigate(['/login']);
    return false;
  }
  if (session.role() === 'Vendor') {
    router.navigate(['/portal']);
  } else {
    router.navigate(['/app/overview']);
  }
  return false;
};
