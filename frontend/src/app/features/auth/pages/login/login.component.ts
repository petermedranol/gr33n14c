import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { CommonModule } from '@angular/common';
import { AuthService } from '../../services/auth.service';
import { UserSettingsService } from '../../../../core/services/user-settings.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [FormsModule, CommonModule],
  templateUrl: './login.component.html',
  styleUrl: './login.component.scss'
})
export class LoginComponent {
  private authService = inject(AuthService);
  private router = inject(Router);
  private settings = inject(UserSettingsService);

  email = '';
  password = '';
  remember = false;
  loading = signal(false);
  errorMessage = signal('');

  onSubmit(): void {
    if (this.loading()) return;
    this.loading.set(true);
    this.errorMessage.set('');

    this.authService.login(this.email, this.password, this.remember).subscribe({
      next: () => {
        this.loading.set(false);
        const last = this.settings.get<string>('lastRoute', '/app/home');
        const dest = last.startsWith('/app/') ? last : '/app/home';
        this.router.navigate([dest]);
      },
      error: (err) => {
        this.loading.set(false);
        const msg = err?.error?.detail || err?.error?.message || 'Error al iniciar sesión. Verifica tus credenciales.';
        this.errorMessage.set(msg);
      }
    });
  }
}
