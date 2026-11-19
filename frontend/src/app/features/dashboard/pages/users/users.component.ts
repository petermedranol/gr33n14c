import { Component, OnInit, OnDestroy, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder, FormGroup, Validators, AbstractControl } from '@angular/forms';
import { AdminUser } from '../../../../core/models/admin-user.model';
import { UsersService, CreateUserPayload, UpdateUserPayload } from './users.service';
import { UserAvatarComponent } from '../../../../shared/components/user-avatar/user-avatar.component';
import { HeaderService } from '../../../../core/services/header.service';
import { LucideAngularModule } from 'lucide-angular';

@Component({
  selector: 'app-users',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, UserAvatarComponent, LucideAngularModule],
  templateUrl: './users.component.html',
  styleUrl: './users.component.scss'
})
export class UsersComponent implements OnInit, OnDestroy {
  private fb = inject(FormBuilder);
  private svc = inject(UsersService);
  private header = inject(HeaderService);

  // ── Page state ──────────────────────────────────────────
  users = signal<AdminUser[]>([]);
  loading = signal(true);
  error = signal<string | null>(null);

  // ── Create/Edit modal state ──────────────────────────────
  modalOpen = signal(false);
  editingUser = signal<AdminUser | null>(null);
  saving = signal(false);
  formError = signal<string | null>(null);
  form!: FormGroup;

  // ── Photo upload state ───────────────────────────────────
  /** File chosen in the file input (not yet uploaded). */
  pendingPhoto = signal<File | null>(null);
  /** Preview URL for the chosen file (revoked on close/change). */
  photoPreviewUrl = signal<string | null>(null);
  /** Cache-bust token; bumped after every successful upload/delete. */
  avatarVersion = signal<number>(0);

  // ── Lifecycle ────────────────────────────────────────────
  ngOnInit(): void {
    this.header.set({ title: 'Usuarios', subtitle: 'Gestión de cuentas de acceso al sistema', icon: 'users' });
    this.loadUsers();
  }

  ngOnDestroy(): void {
    this.header.clear();
  }

  private loadUsers(): void {
    this.loading.set(true);
    this.error.set(null);
    this.svc.list().subscribe({
      next: users => {
        this.users.set(users);
        this.loading.set(false);
      },
      error: err => {
        this.error.set(err.error?.detail ?? 'Error al cargar usuarios. Intenta de nuevo.');
        this.loading.set(false);
      }
    });
  }

  private refreshUsers(): void {
    this.svc.list().subscribe({
      next: users => this.users.set(users),
      error: () => {}
    });
  }

  // ── Create/Edit modal helpers ─────────────────────────────
  openCreate(): void {
    this.editingUser.set(null);
    this.formError.set(null);
    this.form = this.buildForm(null);
    this.modalOpen.set(true);
  }

  openEdit(user: AdminUser): void {
    this.editingUser.set(user);
    this.formError.set(null);
    this.form = this.buildForm(user);
    this.clearPhotoPreview();
    this.modalOpen.set(true);
  }

  closeModal(): void {
    if (this.saving()) return;
    this.clearPhotoPreview();
    this.modalOpen.set(false);
  }

  // ── Photo helpers ─────────────────────────────────────────
  onPhotoFileChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0] ?? null;
    this.clearPhotoPreview();
    if (file) {
      this.pendingPhoto.set(file);
      this.photoPreviewUrl.set(URL.createObjectURL(file));
    }
  }

  private clearPhotoPreview(): void {
    const url = this.photoPreviewUrl();
    if (url) URL.revokeObjectURL(url);
    this.photoPreviewUrl.set(null);
    this.pendingPhoto.set(null);
  }

  removePhoto(): void {
    const editing = this.editingUser();
    if (!editing) return;
    if (!confirm('¿Quitar la foto de este usuario?')) return;
    this.svc.deletePhoto(editing.id).subscribe({
      next: () => {
        this.avatarVersion.set(Date.now());
        this.clearPhotoPreview();
      },
      error: () => {}
    });
  }

  private buildForm(user: AdminUser | null): FormGroup {
    const isEdit = user !== null;
    const passwordValidators = isEdit
      ? [Validators.minLength(6)]
      : [Validators.required, Validators.minLength(6)];

    return this.fb.group({
      name:      [user?.name ?? '', Validators.required],
      email:     [user?.email ?? '', [Validators.required, Validators.email]],
      password:  ['', passwordValidators],
      is_active: [user?.is_active ?? true]
    });
  }

  isInvalid(field: string): boolean {
    const ctrl: AbstractControl | null = this.form.get(field);
    return !!(ctrl && ctrl.invalid && ctrl.touched);
  }

  // ── Form submit ───────────────────────────────────────────
  submitForm(): void {
    this.form.markAllAsTouched();
    if (this.form.invalid) return;

    this.saving.set(true);
    this.formError.set(null);

    const val = this.form.value;
    const editing = this.editingUser();

    if (editing) {
      const payload: UpdateUserPayload = {
        email: val.email,
        name: val.name,
        is_active: val.is_active
      };
      if (val.password?.trim()) {
        payload.password = val.password.trim();
      }

      this.svc.update(editing.id, payload).subscribe({
        next: () => {
          this.uploadPendingPhotoThenClose(editing.id);
        },
        error: err => {
          this.saving.set(false);
          this.formError.set(err.error?.detail ?? 'Error al actualizar el usuario.');
        }
      });
    } else {
      const payload: CreateUserPayload = {
        email: val.email,
        name: val.name,
        password: val.password,
        is_active: val.is_active
      };

      this.svc.create(payload).subscribe({
        next: (created: AdminUser) => {
          this.uploadPendingPhotoThenClose(created.id);
        },
        error: err => {
          this.saving.set(false);
          this.formError.set(err.error?.detail ?? 'Error al crear el usuario.');
        }
      });
    }
  }

  /** Upload photo (if any was chosen) then close the modal and refresh. */
  private uploadPendingPhotoThenClose(userId: number): void {
    const file = this.pendingPhoto();
    if (file) {
      this.svc.uploadPhoto(userId, file).subscribe({
        next: () => {
          this.avatarVersion.set(Date.now());
          this.clearPhotoPreview();
          this.saving.set(false);
          this.modalOpen.set(false);
          this.refreshUsers();
        },
        error: () => {
          // Photo upload failed but user data was saved — close anyway.
          this.clearPhotoPreview();
          this.saving.set(false);
          this.modalOpen.set(false);
          this.refreshUsers();
        }
      });
    } else {
      this.saving.set(false);
      this.modalOpen.set(false);
      this.refreshUsers();
    }
  }

  // ── Delete ────────────────────────────────────────────────
  confirmDelete(user: AdminUser): void {
    const ok = confirm(`¿Eliminar al usuario "${user.name}" (${user.email})? Esta acción no se puede deshacer.`);
    if (!ok) return;

    this.svc.remove(user.id).subscribe({
      next: () => this.refreshUsers(),
      error: err => this.error.set(err.error?.detail ?? 'Error al eliminar el usuario.')
    });
  }
}
