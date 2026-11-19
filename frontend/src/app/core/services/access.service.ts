import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { UserSearchResult, AccessLevel, MenuHierarchyNode, UserAccess, AccessChange, AccessPreset } from '../models/access.model';

@Injectable({ providedIn: 'root' })
export class AccessService {
  private http = inject(HttpClient);

  searchUsers(query: string): Observable<UserSearchResult[]> {
    const params = new HttpParams().set('query', query);
    return this.http.get<UserSearchResult[]>('/api/users/search', { params, withCredentials: true });
  }

  menusHierarchy(): Observable<MenuHierarchyNode[]> {
    return this.http.get<MenuHierarchyNode[]>('/api/menus/hierarchy', { withCredentials: true });
  }

  accessLevels(): Observable<AccessLevel[]> {
    return this.http.get<AccessLevel[]>('/api/access-levels', { withCredentials: true });
  }

  getUserAccesses(userId: number): Observable<UserAccess[]> {
    return this.http.get<UserAccess[]>(`/api/users/${userId}/accesses`, { withCredentials: true });
  }

  saveUserAccesses(userId: number, cambios: AccessChange[]): Observable<unknown> {
    return this.http.put(`/api/users/${userId}/accesses`, { cambios }, { withCredentials: true });
  }

  accessPresets(): Observable<AccessPreset[]> {
    return this.http.get<AccessPreset[]>('/api/access-presets', { withCredentials: true });
  }
}
