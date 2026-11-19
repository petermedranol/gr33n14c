import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { AdminMenu } from '../../../../core/models/menu.model';

export interface MenuPayload {
  parent_id?: number | null;
  label: string;
  icon?: string | null;
  route?: string | null;
  description?: string | null;
  order: number;
  is_free: boolean;
  has_access_levels: boolean;
  is_active: boolean;
}

@Injectable({ providedIn: 'root' })
export class MenusService {
  private http = inject(HttpClient);

  list(): Observable<AdminMenu[]> {
    return this.http.get<AdminMenu[]>('/api/menus/manage', { withCredentials: true });
  }

  create(payload: MenuPayload): Observable<AdminMenu> {
    return this.http.post<AdminMenu>('/api/menus', payload, { withCredentials: true });
  }

  update(id: number, payload: MenuPayload): Observable<AdminMenu> {
    return this.http.put<AdminMenu>(`/api/menus/${id}`, payload, { withCredentials: true });
  }

  remove(id: number): Observable<void> {
    return this.http.delete<void>(`/api/menus/${id}`, { withCredentials: true });
  }
}
