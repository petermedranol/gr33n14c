import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { AdminUser } from '../../../../core/models/admin-user.model';

export interface CreateUserPayload {
  email: string;
  name: string;
  password: string;
  is_active: boolean;
}

export interface UpdateUserPayload {
  email: string;
  name: string;
  is_active: boolean;
  password?: string;
}

@Injectable({ providedIn: 'root' })
export class UsersService {
  private http = inject(HttpClient);

  list(): Observable<AdminUser[]> {
    return this.http.get<AdminUser[]>('/api/users', { withCredentials: true });
  }

  create(payload: CreateUserPayload): Observable<AdminUser> {
    return this.http.post<AdminUser>('/api/users', payload, { withCredentials: true });
  }

  update(id: number, payload: UpdateUserPayload): Observable<AdminUser> {
    return this.http.put<AdminUser>(`/api/users/${id}`, payload, { withCredentials: true });
  }

  remove(id: number): Observable<void> {
    return this.http.delete<void>(`/api/users/${id}`, { withCredentials: true });
  }

  uploadPhoto(id: number, file: File): Observable<unknown> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post(`/api/users/${id}/photo`, form, { withCredentials: true });
  }

  deletePhoto(id: number): Observable<void> {
    return this.http.delete<void>(`/api/users/${id}/photo`, { withCredentials: true });
  }
}
