import { Routes } from '@angular/router';
import { LoginComponent } from './features/auth/pages/login/login.component';
import { ShellComponent } from './features/dashboard/pages/shell/shell.component';
import { HomeComponent } from './features/dashboard/pages/home/home.component';
import { CameraComponent } from './features/dashboard/pages/camera/camera.component';
import { UsersComponent } from './features/dashboard/pages/users/users.component';
import { MenusComponent } from './features/dashboard/pages/menus/menus.component';
import { AccessesComponent } from './features/dashboard/pages/accesses/accesses.component';
import { authGuard } from './features/auth/guards/auth.guard';
import { loginGuard } from './features/auth/guards/login.guard';
import { permissionGuard } from './guards/permission.guard';

export const routes: Routes = [
  {
    path: 'login',
    component: LoginComponent,
    canActivate: [loginGuard]
  },
  {
    path: 'app',
    component: ShellComponent,
    canActivate: [authGuard],
    children: [
      { path: 'home', component: HomeComponent },
      { path: 'camera', component: CameraComponent, canActivate: [permissionGuard] },
      { path: 'users', component: UsersComponent, canActivate: [permissionGuard] },
      { path: 'menus', component: MenusComponent, canActivate: [permissionGuard] },
      { path: 'accesses', component: AccessesComponent, canActivate: [permissionGuard] },
      { path: '', redirectTo: 'home', pathMatch: 'full' }
    ]
  },
  { path: '', redirectTo: '/app/home', pathMatch: 'full' },
  { path: '**', redirectTo: '/login' }
];
