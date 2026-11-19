import { Component, Input, computed, signal } from '@angular/core';
import { CommonModule } from '@angular/common';

/** Deterministic color palette — same as user-autocomplete */
const AVATAR_COLORS = [
  '#2d7a3a', '#1b6e5e', '#1a5c8a', '#5b3fa8', '#8a2d5f',
  '#c06b1a', '#7a2d2d', '#2d7a6e', '#3a5c2d', '#5c3d1a'
];

function avatarColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].charAt(0).toUpperCase();
  return (parts[0].charAt(0) + parts[parts.length - 1].charAt(0)).toUpperCase();
}

/**
 * Reusable circular avatar.
 * Shows a real photo when userId is provided; falls back to colored initials
 * if the image fails to load or no userId is given.
 */
@Component({
  selector: 'app-user-avatar',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './user-avatar.component.html',
  styleUrl: './user-avatar.component.scss'
})
export class UserAvatarComponent {
  @Input() userId?: number;
  @Input() name = '';
  @Input() size = 40;
  /** Bump this value (e.g. Date.now()) to force the browser to re-fetch the photo. */
  @Input() version?: number | string;

  /** Set to true when the img fails to load, switching to initials fallback. */
  imgError = signal(false);

  get showImg(): boolean {
    return !!this.userId && !this.imgError();
  }

  get photoSrc(): string {
    const v = this.version != null ? `?v=${this.version}` : '';
    return `/api/users/${this.userId}/photo${v}`;
  }

  get bgColor(): string {
    return avatarColor(this.name || '?');
  }

  get initials(): string {
    return this.name ? initials(this.name) : '?';
  }

  onImgError(): void {
    this.imgError.set(true);
  }
}
