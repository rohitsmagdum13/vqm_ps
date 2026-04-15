import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { tap } from 'rxjs';
import { AuthService } from '../services/auth.service';

/** Checks every HTTP response for the X-New-Token header.
 *  When the backend auto-refreshes a near-expiry JWT, it sends
 *  the new token in this header. We update localStorage so
 *  subsequent requests use the fresh token. */
export const tokenRefreshInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);

  return next(req).pipe(
    tap((event: any) => {
      if (event.headers) {
        const newToken = event.headers.get('X-New-Token');
        if (newToken) {
          auth.updateToken(newToken);
        }
      }
    })
  );
};
