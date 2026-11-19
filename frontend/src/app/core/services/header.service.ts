import { Injectable, TemplateRef, signal } from '@angular/core';

/**
 * Lets each module publish its page title/subtitle and action buttons into the
 * shell's top bar, instead of rendering a header inside the page body.
 *
 * Usage in a page component:
 *   private header = inject(HeaderService);
 *   ngOnInit()      { this.header.set({ title: 'Cámaras en vivo', subtitle: '…', icon: '📸' }); }
 *   ngAfterViewInit() { this.header.setActions(this.actionsTpl); }  // optional buttons
 *   ngOnDestroy()   { this.header.clear(); }
 */
@Injectable({ providedIn: 'root' })
export class HeaderService {
  readonly title = signal<string>('');
  readonly subtitle = signal<string>('');
  readonly icon = signal<string>('');
  readonly actions = signal<TemplateRef<unknown> | null>(null);

  set(opts: { title: string; subtitle?: string; icon?: string }): void {
    this.title.set(opts.title);
    this.subtitle.set(opts.subtitle ?? '');
    this.icon.set(opts.icon ?? '');
  }

  setActions(tpl: TemplateRef<unknown> | null): void {
    this.actions.set(tpl);
  }

  clear(): void {
    this.title.set('');
    this.subtitle.set('');
    this.icon.set('');
    this.actions.set(null);
  }
}
