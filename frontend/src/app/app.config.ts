import { ApplicationConfig, importProvidersFrom, provideBrowserGlobalErrorListeners, provideZoneChangeDetection } from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import {
  LucideAngularModule,
  Sprout, Camera, User, Users, Download, X, RotateCw,
  LayoutDashboard, KeyRound, SquareMenu, Play, Trash2,
  House, Settings, Lock, Leaf, Warehouse, Images,
  Plus, Pencil, Save, Check, Search, RefreshCw, LogOut,
  ChevronLeft, ChevronRight, ChevronDown, Cloud,
  ArrowUp, ArrowDown, ArrowLeft, ArrowRight, ZoomIn, ZoomOut,
  MapPin, Route, Square, Pause, Maximize, AudioLines, SlidersHorizontal,
  Volume2, VolumeX,
} from 'lucide-angular';

import { routes } from './app.routes';
import { authInterceptor } from './shared/interceptors/auth.interceptor';
import { csrfInterceptor } from './shared/interceptors/csrf.interceptor';
import { sessionExpiredInterceptor } from './shared/interceptors/session-expired.interceptor';

export const appConfig: ApplicationConfig = {
  providers: [
    // Zone-based change detection (zone.js) so components using plain fields
    // updated in async callbacks refresh correctly, like the reference app.
    provideZoneChangeDetection({ eventCoalescing: true }),
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes),
    provideHttpClient(
      withInterceptors([authInterceptor, csrfInterceptor, sessionExpiredInterceptor])
    ),
    importProvidersFrom(
      LucideAngularModule.pick({
        Sprout, Camera, User, Users, Download, X, RotateCw,
        LayoutDashboard, KeyRound, SquareMenu, Play, Trash2,
        House, Settings, Lock, Leaf, Warehouse, Images,
        Plus, Pencil, Save, Check, Search, RefreshCw, LogOut,
        ChevronLeft, ChevronRight, ChevronDown, Cloud,
        ArrowUp, ArrowDown, ArrowLeft, ArrowRight, ZoomIn, ZoomOut,
        MapPin, Route, Square, Pause, Maximize, AudioLines, SlidersHorizontal,
        Volume2, VolumeX,
      })
    )
  ]
};
