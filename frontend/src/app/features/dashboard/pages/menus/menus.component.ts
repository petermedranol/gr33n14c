import { Component, OnInit, OnDestroy, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder, FormGroup, Validators, AbstractControl } from '@angular/forms';
import { AdminMenu } from '../../../../core/models/menu.model';
import { MenusService, MenuPayload } from './menus.service';
import { HeaderService } from '../../../../core/services/header.service';
import { LucideAngularModule } from 'lucide-angular';

/** AdminMenu enriched with display indentation level */
interface MenuRow {
  menu: AdminMenu;
  indent: number;
}

@Component({
  selector: 'app-menus',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, LucideAngularModule],
  templateUrl: './menus.component.html',
  styleUrl: './menus.component.scss'
})
export class MenusComponent implements OnInit, OnDestroy {
  private fb = inject(FormBuilder);
  private svc = inject(MenusService);
  private header = inject(HeaderService);

  // ── Page state ──────────────────────────────────────────
  menuRows = signal<MenuRow[]>([]);
  allMenus = signal<AdminMenu[]>([]);
  loading = signal(true);
  error = signal<string | null>(null);

  // ── Modal state ──────────────────────────────────────────
  modalOpen = signal(false);
  editingMenu = signal<AdminMenu | null>(null);
  saving = signal(false);
  formError = signal<string | null>(null);
  form!: FormGroup;

  // ── Lifecycle ────────────────────────────────────────────
  ngOnInit(): void {
    this.header.set({ title: 'Menús', subtitle: 'Configuración de menús del sistema', icon: 'square-menu' });
    this.loadAll();
  }

  ngOnDestroy(): void {
    this.header.clear();
  }

  private loadAll(): void {
    this.loading.set(true);
    this.error.set(null);
    this.svc.list().subscribe({
      next: menus => {
        this.allMenus.set(menus);
        this.menuRows.set(this.buildRows(menus));
        this.loading.set(false);
      },
      error: err => {
        this.error.set(err.error?.detail ?? 'Error al cargar menús. Intenta de nuevo.');
        this.loading.set(false);
      }
    });
  }

  private refreshMenus(): void {
    this.svc.list().subscribe({
      next: menus => {
        this.allMenus.set(menus);
        this.menuRows.set(this.buildRows(menus));
      },
      error: () => {}
    });
  }

  /** Build an ordered, indented list of MenuRow from a flat AdminMenu array */
  private buildRows(menus: AdminMenu[]): MenuRow[] {
    const parents = menus.filter(m => m.parent_id === null).sort((a, b) => a.order - b.order);
    const rows: MenuRow[] = [];

    for (const parent of parents) {
      rows.push({ menu: parent, indent: 0 });
      const children = menus
        .filter(m => m.parent_id === parent.id)
        .sort((a, b) => a.order - b.order);
      for (const child of children) {
        rows.push({ menu: child, indent: 1 });
      }
    }

    // Any orphaned menus
    const covered = new Set(rows.map(r => r.menu.id));
    for (const m of menus) {
      if (!covered.has(m.id)) {
        rows.push({ menu: m, indent: 0 });
      }
    }

    return rows;
  }

  /** Parent menus available in the form's parent selector (exclude self when editing) */
  parentOptions(): AdminMenu[] {
    const editing = this.editingMenu();
    return this.allMenus().filter(m =>
      m.parent_id === null && (!editing || m.id !== editing.id)
    );
  }

  // ── Modal helpers ─────────────────────────────────────────
  openCreate(): void {
    this.editingMenu.set(null);
    this.formError.set(null);
    this.form = this.buildForm(null);
    this.modalOpen.set(true);
  }

  openEdit(menu: AdminMenu): void {
    this.editingMenu.set(menu);
    this.formError.set(null);
    this.form = this.buildForm(menu);
    this.modalOpen.set(true);
  }

  closeModal(): void {
    if (this.saving()) return;
    this.modalOpen.set(false);
  }

  private buildForm(menu: AdminMenu | null): FormGroup {
    return this.fb.group({
      parent_id:         [menu?.parent_id ?? null],
      label:             [menu?.label ?? '', Validators.required],
      icon:              [menu?.icon ?? ''],
      route:             [menu?.route ?? ''],
      description:       [menu?.description ?? ''],
      order:             [menu?.order ?? 0, [Validators.required, Validators.min(0)]],
      is_free:           [menu?.is_free ?? false],
      has_access_levels: [menu?.has_access_levels ?? false],
      is_active:         [menu?.is_active ?? true]
    });
  }

  isInvalid(field: string): boolean {
    const ctrl: AbstractControl | null = this.form.get(field);
    return !!(ctrl && ctrl.invalid && ctrl.touched);
  }

  get isFreeValue(): boolean { return !!this.form.get('is_free')?.value; }
  get hasAccessLevelsValue(): boolean { return !!this.form.get('has_access_levels')?.value; }

  // ── Form submit ───────────────────────────────────────────
  submitForm(): void {
    this.form.markAllAsTouched();
    if (this.form.invalid) return;

    this.saving.set(true);
    this.formError.set(null);

    const val = this.form.getRawValue();
    const payload: MenuPayload = {
      parent_id:         val.parent_id ? Number(val.parent_id) : null,
      label:             val.label.trim(),
      icon:              val.icon?.trim() || null,
      route:             val.route?.trim() || null,
      description:       val.description?.trim() || null,
      order:             Number(val.order),
      is_free:           !!val.is_free,
      has_access_levels: !!val.has_access_levels,
      is_active:         !!val.is_active
    };

    const editing = this.editingMenu();
    const request$ = editing ? this.svc.update(editing.id, payload) : this.svc.create(payload);

    request$.subscribe({
      next: () => {
        this.saving.set(false);
        this.modalOpen.set(false);
        this.refreshMenus();
      },
      error: err => {
        this.saving.set(false);
        this.formError.set(err.error?.detail ?? 'Error al guardar el menú.');
      }
    });
  }

  // ── Delete ────────────────────────────────────────────────
  confirmDelete(menu: AdminMenu): void {
    const ok = confirm(`¿Eliminar el menú "${menu.label}"? Esta acción no se puede deshacer.`);
    if (!ok) return;

    this.svc.remove(menu.id).subscribe({
      next: () => this.refreshMenus(),
      error: err => this.error.set(err.error?.detail ?? 'Error al eliminar el menú.')
    });
  }
}
