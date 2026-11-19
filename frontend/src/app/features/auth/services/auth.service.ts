import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { Observable, map, tap, catchError, of } from 'rxjs';
import { User } from '../../../core/models/user.model';
import { MenuItem } from '../../../core/models/menu.model';

interface LoginResponse {
  message: string;
  user: User;
  preferences: { menuItems: MenuItem[] };
}

interface UserResponse {
  user: User;
  preferences: { menuItems: MenuItem[] };
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private http = inject(HttpClient);
  private router = inject(Router);

  currentUser = signal<User | null>(null);
  menuItems = signal<MenuItem[]>([]);

  login(email: string, password: string, remember: boolean): Observable<LoginResponse> {
    return this.http.post<LoginResponse>('/api/login', { email, password, remember }, { withCredentials: true }).pipe(
      tap(res => {
        this.currentUser.set(res.user);
        this.menuItems.set(res.preferences?.menuItems ?? []);
      })
    );
  }

  logout(): void {
    this.http.post('/api/logout', {}, { withCredentials: true }).subscribe({
      complete: () => {
        this.currentUser.set(null);
        this.menuItems.set([]);
        this.router.navigate(['/login']);
      },
      error: () => {
        this.currentUser.set(null);
        this.menuItems.set([]);
        this.router.navigate(['/login']);
      }
    });
  }

  checkAuthentication(): Observable<boolean> {
    return this.http.get<UserResponse>('/api/user', { withCredentials: true }).pipe(
      tap(res => {
        this.currentUser.set(res.user);
        this.menuItems.set(res.preferences?.menuItems ?? []);
      }),
      map(() => true),
      catchError(() => {
        this.currentUser.set(null);
        this.menuItems.set([]);
        return of(false);
      })
    );
  }

  isAuthenticated(): boolean {
    return this.currentUser() !== null;
  }

  hasRoute(url: string): boolean {
    const alwaysAllowed = ['/app/home', '/app'];
    if (alwaysAllowed.some(r => url.startsWith(r))) {
      return true;
    }
    return this.searchMenuItems(this.menuItems(), url);
  }

  private searchMenuItems(items: MenuItem[], url: string): boolean {
    for (const item of items) {
      if (item.route && url.includes(item.route)) {
        return true;
      }
      if (item.children?.length && this.searchMenuItems(item.children, url)) {
        return true;
      }
    }
    return false;
  }
}
