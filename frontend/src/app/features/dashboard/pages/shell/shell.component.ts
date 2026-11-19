import { Component, inject, signal } from '@angular/core';
import { RouterOutlet, RouterLink, RouterLinkActive, Router, NavigationEnd } from '@angular/router';
import { CommonModule } from '@angular/common';
import { LucideAngularModule } from 'lucide-angular';
import { filter } from 'rxjs';
import { AuthService } from '../../../auth/services/auth.service';
import { MenuItem } from '../../../../core/models/menu.model';
import { SidebarService } from '../../../../core/services/sidebar.service';
import { UserSettingsService } from '../../../../core/services/user-settings.service';
import { HeaderService } from '../../../../core/services/header.service';
import { UserAvatarComponent } from '../../../../shared/components/user-avatar/user-avatar.component';

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive, CommonModule, UserAvatarComponent, LucideAngularModule],
  templateUrl: './shell.component.html',
  styleUrl: './shell.component.scss'
})
export class ShellComponent {
  authService = inject(AuthService);
  header = inject(HeaderService);
  sidebar = inject(SidebarService);
  private settings = inject(UserSettingsService);
  private router = inject(Router);

  /** Expanded groups in the sidebar nav */
  expandedItems = signal<Set<number>>(new Set());

  /** Active flyout item id (hover) for collapsed mode */
  activeFlyout = signal<number | null>(null);

  constructor() {
    this.sidebar.init();
    this.expandedItems.set(new Set(this.settings.get<number[]>('expandedMenus', [])));

    // Persist the last visited /app/... route so login can restore it.
    this.router.events.pipe(
      filter(e => e instanceof NavigationEnd)
    ).subscribe(e => {
      const url = (e as NavigationEnd).urlAfterRedirects;
      if (url.startsWith('/app/')) {
        this.settings.set('lastRoute', url);
      }
    });
  }

  get user() {
    return this.authService.currentUser();
  }

  get menuItems(): MenuItem[] {
    return this.authService.menuItems();
  }

  get isCollapsed(): boolean {
    return this.sidebar.isSidebarCollapsed();
  }

  get isMobileOpen(): boolean {
    return this.sidebar.isSidebarOpen();
  }

  /** Hamburger in topbar: on mobile opens the overlay; on desktop toggles collapse */
  toggleSidebar(): void {
    if (window.innerWidth < 1024) {
      this.sidebar.toggle();
    } else {
      this.sidebar.toggleCollapse();
    }
  }

  /** Round toggle button inside the sidebar */
  toggleCollapse(): void {
    this.sidebar.toggleCollapse();
  }

  toggleExpand(id: number): void {
    this.expandedItems.update(set => {
      const next = new Set(set);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      this.settings.set('expandedMenus', [...next]);
      return next;
    });
  }

  isExpanded(id: number): boolean {
    return this.expandedItems().has(id);
  }

  private flyoutHideTimer: ReturnType<typeof setTimeout> | null = null;

  showFlyout(id: number): void {
    if (this.flyoutHideTimer) {
      clearTimeout(this.flyoutHideTimer);
      this.flyoutHideTimer = null;
    }
    this.activeFlyout.set(id);
  }

  /** Hide after a short delay so moving the cursor into the flyout doesn't close it. */
  scheduleHideFlyout(): void {
    if (this.flyoutHideTimer) clearTimeout(this.flyoutHideTimer);
    this.flyoutHideTimer = setTimeout(() => this.activeFlyout.set(null), 300);
  }

  hideFlyout(): void {
    if (this.flyoutHideTimer) {
      clearTimeout(this.flyoutHideTimer);
      this.flyoutHideTimer = null;
    }
    this.activeFlyout.set(null);
  }

  isFlyoutActive(id: number): boolean {
    return this.activeFlyout() === id;
  }

  logout(): void {
    this.authService.logout();
  }
}
