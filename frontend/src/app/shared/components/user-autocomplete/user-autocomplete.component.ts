import {
  Component,
  Input,
  Output,
  EventEmitter,
  OnDestroy,
  OnInit,
  ChangeDetectorRef,
  inject
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Observable, Subject, debounceTime, distinctUntilChanged, switchMap, takeUntil, from, of } from 'rxjs';
import { UserSearchResult } from '../../../core/models/access.model';
import { UserAvatarComponent } from '../user-avatar/user-avatar.component';


@Component({
  selector: 'app-user-autocomplete',
  standalone: true,
  imports: [CommonModule, FormsModule, UserAvatarComponent],
  templateUrl: './user-autocomplete.component.html',
  styleUrl: './user-autocomplete.component.scss'
})
export class UserAutocompleteComponent implements OnInit, OnDestroy {
  @Input() searchFunction!: (query: string) => Observable<UserSearchResult[]> | Promise<UserSearchResult[]>;
  @Input() placeholder = 'Buscar por nombre o correo…';

  @Output() userSelected = new EventEmitter<UserSearchResult>();
  @Output() userCleared = new EventEmitter<void>();

  private cdr = inject(ChangeDetectorRef);

  query = '';
  results: UserSearchResult[] = [];
  highlighted = 0;
  showDropdown = false;
  loading = false;
  selectedUser: UserSearchResult | null = null;

  private search$ = new Subject<string>();
  private destroy$ = new Subject<void>();

  ngOnInit(): void {
    this.search$.pipe(
      debounceTime(300),
      distinctUntilChanged(),
      switchMap(q => {
        if (q.length < 2) {
          this.results = [];
          this.showDropdown = false;
          this.loading = false;
          this.cdr.markForCheck();
          return of([] as UserSearchResult[]);
        }
        this.loading = true;
        this.showDropdown = true;
        this.cdr.markForCheck();
        const r = this.searchFunction(q);
        return r instanceof Observable ? r : from(r);
      }),
      takeUntil(this.destroy$)
    ).subscribe({
      next: users => {
        this.results = users.slice(0, 10);
        this.highlighted = 0;
        this.loading = false;
        this.cdr.markForCheck();
      },
      error: () => {
        this.results = [];
        this.loading = false;
        this.showDropdown = false;
        this.cdr.markForCheck();
      }
    });
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  onInput(): void {
    if (this.selectedUser) {
      this.selectedUser = null;
    }
    this.search$.next(this.query);
  }

  onKeydown(event: KeyboardEvent): void {
    if (!this.showDropdown || !this.results.length) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      this.highlighted = Math.min(this.highlighted + 1, this.results.length - 1);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      this.highlighted = Math.max(this.highlighted - 1, 0);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      this.select(this.results[this.highlighted]);
    } else if (event.key === 'Escape') {
      this.showDropdown = false;
    }
  }

  onFocus(): void {
    if (this.results.length && this.query.length >= 2 && !this.selectedUser) {
      this.showDropdown = true;
    }
  }

  onBlur(): void {
    // Delay to allow click events to fire first
    setTimeout(() => {
      this.showDropdown = false;
      this.cdr.markForCheck();
    }, 200);
  }

  select(user: UserSearchResult): void {
    this.selectedUser = user;
    this.query = `${user.name} (${user.email})`;
    this.results = [];
    this.showDropdown = false;
    this.userSelected.emit(user);
  }

  clear(): void {
    this.selectedUser = null;
    this.query = '';
    this.results = [];
    this.showDropdown = false;
    this.loading = false;
    this.userCleared.emit();
  }

}
