import { Injectable } from '@angular/core';

/**
 * Persists UI preferences in localStorage under a single key, so state like the
 * sidebar and expanded menu groups survives reloads. Mirrors sicaad's
 * UserSettingsService (local store; server sync can be added later).
 */
@Injectable({ providedIn: 'root' })
export class UserSettingsService {
  private readonly KEY = 'greeniac_user_settings';

  getAll(): Record<string, unknown> {
    try {
      const raw = localStorage.getItem(this.KEY);
      return raw ? JSON.parse(raw) : {};
    } catch {
      return {};
    }
  }

  get<T>(setting: string, fallback: T): T {
    const settings = this.getAll();
    return settings[setting] !== undefined ? (settings[setting] as T) : fallback;
  }

  set(setting: string, value: unknown): void {
    const settings = this.getAll();
    settings[setting] = value;
    localStorage.setItem(this.KEY, JSON.stringify(settings));
  }

  remove(): void {
    localStorage.removeItem(this.KEY);
  }
}
