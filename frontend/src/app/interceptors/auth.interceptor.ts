import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { AuthService } from '../services/auth.service';

/** Adds Authorization Bearer token and X-Vendor-ID header
 *  to all outgoing HTTP requests (except login). */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);

  // Don't add headers to the login request
  if (req.url.includes('/auth/login')) {
    return next(req);
  }

  const token = auth.getToken();
  const vendorId = auth.getVendorId();

  let headers = req.headers;
  if (token) {
    headers = headers.set('Authorization', `Bearer ${token}`);
  }
  if (vendorId) {
    headers = headers.set('X-Vendor-ID', vendorId);
  }

  return next(req.clone({ headers }));
};
