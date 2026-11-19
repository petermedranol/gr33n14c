import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { AuthService } from '../../../auth/services/auth.service';
import { HeaderService } from '../../../../core/services/header.service';

@Component({
  selector: 'app-home',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './home.component.html',
  styleUrl: './home.component.scss'
})
export class HomeComponent implements OnInit, OnDestroy {
  authService = inject(AuthService);
  private header = inject(HeaderService);

  get user() {
    return this.authService.currentUser();
  }

  ngOnInit(): void {
    this.header.set({ title: 'Panel de control', icon: 'layout-dashboard' });
  }

  ngOnDestroy(): void {
    this.header.clear();
  }
}
