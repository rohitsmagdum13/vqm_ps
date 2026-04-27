import { inject } from '@angular/core';
import { Router, type ActivatedRouteSnapshot, type CanActivateFn } from '@angular/router';
import { AuthService } from './auth.service';

/**
 * Walk an ActivatedRouteSnapshot tree to find the closest `:vendorId`
 * route param. Vendor routes nest the param on the parent so each
 * child page (portal, queries, wizard, …) sees the same value via
 * snapshot.params or any ancestor's params.
 */
function findVendorIdParam(route: ActivatedRouteSnapshot): string | null {
  let current: ActivatedRouteSnapshot | null = route;
  while (current) {
    const v = current.params['vendorId'];
    if (typeof v === 'string' && v.length > 0) return v;
    current = current.parent;
  }
  return null;
}

export const authGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  return auth.isAuthed() ? true : router.createUrlTree(['/login']);
};

/**
 * Vendor-only routes. In addition to the role check, this guard
 * verifies the `:vendorId` URL segment matches the session vendor —
 * a vendor cannot peek at another vendor's portal by typing
 * `/V-007/queries` while logged in as V-001. URL-tampering is
 * redirected to the user's own portal home, not silently allowed.
 */
export const vendorOnly: CanActivateFn = (route) => {
  const auth = inject(AuthService);
  const router = inject(Router);

  if (auth.role() !== 'vendor') {
    return router.createUrlTree(['/admin']);
  }

  const sessionVendorId = auth.vendorId();
  if (!sessionVendorId) {
    // VENDOR role with no vendor mapping — backend should have
    // rejected the login, but be defensive on the client too.
    return router.createUrlTree(['/login']);
  }

  const urlVendorId = findVendorIdParam(route);
  if (urlVendorId === null) {
    // Route reached the guard without a :vendorId segment — send the
    // user to their canonical portal home.
    return router.createUrlTree(['/', sessionVendorId, 'portal']);
  }

  // Compare case-insensitively so `/v-001/portal` works the same as
  // `/V-001/portal`. On mismatch, redirect to the user's own home —
  // never reveal whether the foreign vendor exists.
  if (urlVendorId.toLowerCase() !== sessionVendorId.toLowerCase()) {
    return router.createUrlTree(['/', sessionVendorId, 'portal']);
  }

  return true;
};

export const adminOnly: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  if (auth.role() === 'admin') return true;
  // Non-admins get sent to their role-appropriate home (vendors land
  // on /<vendorId>/portal, signed-out users on /login).
  return router.createUrlTree(auth.homePath());
};

/**
 * Empty-path landing guard. `/` resolves to `/admin` for admins or
 * `/<vendorId>/portal` for vendors. Used by the route at path `''`
 * so the URL bar shows a meaningful page instead of a blank root.
 */
export const homeRedirect: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  return router.createUrlTree(auth.homePath());
};
