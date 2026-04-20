import { HttpErrorResponse, type HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, tap, throwError } from 'rxjs';
import { environment } from '../../../environments/environment';
import { AuthService } from './auth.service';

const API_BASE = environment.apiBaseUrl;

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const router = inject(Router);

  if (!req.url.startsWith(API_BASE)) {
    return next(req);
  }

  const isLogin = req.url.startsWith(`${API_BASE}/auth/login`);
  const token = auth.token();

  const authedReq =
    !isLogin && token
      ? req.clone({ setHeaders: { Authorization: `Bearer ${token}` } })
      : req;

  return next(authedReq).pipe(
    tap((event) => {
      if ('headers' in event && event.type === 4) {
        const newToken = event.headers.get('X-New-Token');
        if (newToken) {
          auth.updateToken(newToken);
        }
      }
    }),
    catchError((err: unknown) => {
      if (err instanceof HttpErrorResponse && err.status === 401 && !isLogin) {
        void auth.logout().finally(() => {
          void router.navigate(['/login']);
        });
      }
      return throwError(() => err);
    }),
  );
};
