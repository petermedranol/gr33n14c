import { Injectable, inject, signal } from '@angular/core';
import { UserSettingsService } from './user-settings.service';

/**
 * Sidebar state service.
 * - isSidebarOpen: overlay visibility on mobile (open = visible over content)
 * - isSidebarCollapsed: collapsed to icon-rail vs expanded with text (desktop)
 * Both are persisted via UserSettingsService.
 */
@Injectable({ providedIn: 'root' })
export class SidebarService {
  private settings = inject(UserSettingsService);

  /** Mobile overlay: visible/hidden */
  isSidebarOpen = signal(true);

  /** Desktop: collapsed to icon-rail (true) or expanded with labels (false) */
  isSidebarCollapsed = signal(false);

  private initialized = false;

  init(): void {
    if (this.initialized) return;
    this.initialized = true;

    if (this.isMobile()) {
      this.isSidebarOpen.set(false);
      this.isSidebarCollapsed.set(false);
      return;
    }

    this.isSidebarOpen.set(Boolean(this.settings.get<boolean>('sidebarOpen', true)));
    this.isSidebarCollapsed.set(Boolean(this.settings.get<boolean>('sidebarCollapsed', false)));
  }

  /** Toggle the mobile overlay open/closed */
  toggle(): void {
    const next = !this.isSidebarOpen();
    this.isSidebarOpen.set(next);
    if (!this.isMobile()) {
      this.settings.set('sidebarOpen', next);
    }
  }

  /** Toggle between collapsed icon-rail and expanded sidebar (desktop) */
  toggleCollapse(): void {
    const next = !this.isSidebarCollapsed();
    this.isSidebarCollapsed.set(next);
    this.settings.set('sidebarCollapsed', next);
  }

  private isMobile(): boolean {
    return typeof window !== 'undefined' && window.innerWidth < 1024;
  }
}
