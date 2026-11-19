import { HttpInterceptorFn } from '@angular/common/http';

function getCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp('(?:^|;\\s*)' + name + '=([^;]*)'));
  return match ? decodeURIComponent(match[1]) : null;
}

export const csrfInterceptor: HttpInterceptorFn = (req, next) => {
  const skipMethods = ['GET', 'HEAD', 'OPTIONS'];
  const isLoginRequest = req.url === '/api/login';

  if (!skipMethods.includes(req.method) && !isLoginRequest) {
    const token = getCookie('XSRF-TOKEN');
    if (token) {
      const cloned = req.clone({
        setHeaders: { 'X-XSRF-TOKEN': token }
      });
      return next(cloned);
    }
  }

  return next(req);
};
