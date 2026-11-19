import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { map } from 'rxjs';
import { AuthService } from '../services/auth.service';

export const loginGuard: CanActivateFn = (_route, _state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (authService.isAuthenticated()) {
    return router.createUrlTree(['/app/home']);
  }

  return authService.checkAuthentication().pipe(
    map(authenticated => {
      if (authenticated) {
        return router.createUrlTree(['/app/home']);
      }
      return true;
    })
  );
};
