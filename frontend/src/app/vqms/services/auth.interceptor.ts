import { HttpErrorResponse, type HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, tap, throwError } from 'rxjs';
import { environment } from '../../../environments/environment';
import { SessionService } from './session.service';

const API_BASE = environment.apiBaseUrl;

/**
 * Attach `Authorization: Bearer <token>` to API requests, honour the
 * server's `X-New-Token` refresh header, and force the user back to
 * /login on 401 (token expired or blacklisted).
 *
 * Only requests targeting the configured API base URL are touched —
 * static asset and CDN requests pass through untouched.
 */
export const designAuthInterceptor: HttpInterceptorFn = (req, next) => {
  const session = inject(SessionService);
  const router = inject(Router);

  if (!req.url.startsWith(API_BASE)) {
    return next(req);
  }

  const isLogin = req.url.startsWith(`${API_BASE}/auth/login`);
  const token = session.token();

  const authedReq =
    !isLogin && token
      ? req.clone({ setHeaders: { Authorization: `Bearer ${token}` } })
      : req;

  return next(authedReq).pipe(
    tap((event) => {
      // HttpEventType.Response === 4
      if ('headers' in event && event.type === 4) {
        const newToken = event.headers.get('X-New-Token');
        if (newToken) {
          session.updateToken(newToken);
        }
      }
    }),
    catchError((err: unknown) => {
      if (err instanceof HttpErrorResponse && err.status === 401 && !isLogin) {
        session.forceSignOut();
        void router.navigate(['/login']);
      }
      return throwError(() => err);
    }),
  );
};
