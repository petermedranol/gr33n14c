import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';
import { AuthService } from '../../features/auth/services/auth.service';

export const sessionExpiredInterceptor: HttpInterceptorFn = (req, next) => {
  const router = inject(Router);
  const authService = inject(AuthService);

  // El 401 de estos endpoints es NORMAL ("no hay sesión"), no una sesión expirada:
  // el login y el sondeo que hacen los guards. Si el interceptor reaccionara a ellos
  // re-navegaría a /login cancelando la navegación del guard → bucle infinito.
  const isAuthProbe = req.url.includes('/api/login') || req.url.includes('/api/user');

  return next(req).pipe(
    catchError(err => {
      // Solo 401/419 (sesión expirada) y nunca en los sondeos de auth.
      // El 403 es "permiso denegado": no debe cerrar la sesión.
      if ((err.status === 401 || err.status === 419) && !isAuthProbe) {
        if (!router.url.includes('/login')) {
          authService.currentUser.set(null);
          authService.menuItems.set([]);
          router.navigate(['/login']);
        }
      }
      return throwError(() => err);
    })
  );
};
