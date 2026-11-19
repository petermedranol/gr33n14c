import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Observable, Subject, forkJoin, takeUntil } from 'rxjs';
import { AccessService } from '../../../../core/services/access.service';
import { UserSearchResult, AccessLevel, MenuHierarchyNode, UserAccess, AccessChange, AccessPreset } from '../../../../core/models/access.model';
import { UserAutocompleteComponent } from '../../../../shared/components/user-autocomplete/user-autocomplete.component';
import { HeaderService } from '../../../../core/services/header.service';
import { LucideAngularModule } from 'lucide-angular';

/** Menu node enriched with computed display level for the template */
interface TreeNode extends MenuHierarchyNode {
  displayLevel: number;
  children: TreeNode[];
}

@Component({
  selector: 'app-accesses',
  standalone: true,
  imports: [CommonModule, FormsModule, UserAutocompleteComponent, LucideAngularModule],
  templateUrl: './accesses.component.html',
  styleUrl: './accesses.component.scss'
})
export class AccessesComponent implements OnInit, OnDestroy {
  private svc = inject(AccessService);
  private header = inject(HeaderService);
  private destroy$ = new Subject<void>();

  // ── Autocomplete ────────────────────────────────────────────
  searchFn: (q: string) => Observable<UserSearchResult[]> = (q) => this.svc.searchUsers(q);

  // ── Selected user ───────────────────────────────────────────
  selectedUser: UserSearchResult | null = null;

  // ── Menu tree ────────────────────────────────────────────────
  menus: TreeNode[] = [];
  menusLoading = true;

  // ── Access levels ────────────────────────────────────────────
  accessLevels: AccessLevel[] = [];

  // ── User accesses (current editing state + snapshot) ─────────
  userAccesses: Record<number, string> = {};
  originalUserAccesses: Record<number, string> = {};

  // ── Save state ───────────────────────────────────────────────
  saving = false;
  saveSuccess: string | null = null;
  saveError: string | null = null;
  accessesLoading = false;

  // ── Presets ──────────────────────────────────────────────────
  presets: AccessPreset[] = [];
  presetsLoading = false;
  showPresetModal = false;
  selectedPresetId: number | null = null;

  // ── Clone profile ─────────────────────────────────────────────
  showCloneModal = false;
  cloneSourceUser: UserSearchResult | null = null;
  cloneSearchFn: (q: string) => Observable<UserSearchResult[]> = (q) => this.svc.searchUsers(q);
  cloningProfile = false;

  // ── Toolbar ──────────────────────────────────────────────────
  menuSearch = '';
  statusFilter: 'all' | 'with' | 'without' = 'all';
  collapsedMenus = new Set<number>();

  ngOnInit(): void {
    this.header.set({ title: 'Accesos', subtitle: 'Gestión de permisos por usuario', icon: 'lock' });
    forkJoin({
      menus: this.svc.menusHierarchy(),
      levels: this.svc.accessLevels()
    }).pipe(takeUntil(this.destroy$)).subscribe({
      next: ({ menus, levels }) => {
        this.menus = this.enrichTree(menus, 0);
        this.accessLevels = levels;
        this.menusLoading = false;
      },
      error: () => { this.menusLoading = false; }
    });

    this.loadPresets();
  }

  private loadPresets(): void {
    this.presetsLoading = true;
    this.svc.accessPresets().pipe(takeUntil(this.destroy$)).subscribe({
      next: (presets) => { this.presets = presets; this.presetsLoading = false; },
      error: () => { this.presetsLoading = false; }
    });
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
    this.header.clear();
  }

  // ── Autocomplete handlers ────────────────────────────────────
  onUserSelected(user: UserSearchResult): void {
    this.selectedUser = user;
    this.loadUserAccesses(user.id);
  }

  onUserCleared(): void {
    this.selectedUser = null;
    this.userAccesses = {};
    this.originalUserAccesses = {};
    this.saveSuccess = null;
    this.saveError = null;
  }

  private loadUserAccesses(userId: number): void {
    this.accessesLoading = true;
    this.saveSuccess = null;
    this.saveError = null;
    this.svc.getUserAccesses(userId).pipe(takeUntil(this.destroy$)).subscribe({
      next: (accesses: UserAccess[]) => {
        const map: Record<number, string> = {};
        accesses.forEach(a => { map[a.menu_id] = a.access_level; });
        this.userAccesses = map;
        this.originalUserAccesses = { ...map };
        this.accessesLoading = false;
      },
      error: () => { this.accessesLoading = false; }
    });
  }

  // ── Tree helpers ─────────────────────────────────────────────
  private enrichTree(nodes: MenuHierarchyNode[], depth: number): TreeNode[] {
    return nodes.map(n => ({
      ...n,
      displayLevel: depth,
      children: this.enrichTree(n.children ?? [], depth + 1)
    }));
  }

  /** A menu is assignable if it is restricted (is_free=false) OR if it is free but has_access_levels */
  isAssignable(node: MenuHierarchyNode): boolean {
    return !node.is_free || !!node.has_access_levels;
  }

  hasAccess(menuId: number): boolean {
    return menuId in this.userAccesses;
  }

  getAccessLevel(menuId: number): string {
    return this.userAccesses[menuId] ?? '';
  }

  // ── Checkbox toggle with cascade ─────────────────────────────
  onMenuToggle(node: TreeNode, event: Event): void {
    const checked = (event.target as HTMLInputElement).checked;
    this.toggleMenuAccess(node, checked);

    // After unchecking, clear ancestors that have no remaining checked descendants
    if (!checked) {
      const ancestor = this.findRestrictedAncestor(node);
      if (ancestor && !this.hasAnyAccessibleDescendant(ancestor)) {
        delete this.userAccesses[ancestor.id];
      }
    }
  }

  private toggleMenuAccess(node: TreeNode, checked: boolean): void {
    if (checked) {
      if (this.isAssignable(node)) {
        this.userAccesses[node.id] = this.userAccesses[node.id] ?? this.defaultLevel();
      }
      // Auto-check all restricted ancestors
      let ancestor = this.findRestrictedAncestor(node);
      while (ancestor) {
        if (!this.hasAccess(ancestor.id)) {
          this.userAccesses[ancestor.id] = this.defaultLevel();
        }
        ancestor = this.findRestrictedAncestor(ancestor);
      }
      // Check all descendants
      this.walkDescendants(node.children, child => {
        if (this.isAssignable(child)) {
          this.userAccesses[child.id] = this.userAccesses[child.id] ?? this.defaultLevel();
        }
      });
    } else {
      delete this.userAccesses[node.id];
      // Uncheck all descendants
      this.walkDescendants(node.children, child => {
        delete this.userAccesses[child.id];
      });
    }
  }

  private defaultLevel(): string {
    return this.accessLevels.length ? this.accessLevels[0].key : 'capturista';
  }

  private walkDescendants(nodes: TreeNode[], fn: (n: TreeNode) => void): void {
    for (const n of nodes) {
      fn(n);
      if (n.children?.length) this.walkDescendants(n.children, fn);
    }
  }

  private findMenuById(nodes: TreeNode[], id: number): TreeNode | null {
    for (const n of nodes) {
      if (n.id === id) return n;
      const found = this.findMenuById(n.children, id);
      if (found) return found;
    }
    return null;
  }

  private findRestrictedAncestor(node: MenuHierarchyNode): TreeNode | null {
    if (!node.parent_id) return null;
    const parent = this.findMenuById(this.menus, node.parent_id);
    if (!parent) return null;
    if (this.isAssignable(parent)) return parent;
    return this.findRestrictedAncestor(parent);
  }

  private hasAnyAccessibleDescendant(node: TreeNode): boolean {
    if (!node.children?.length) return false;
    for (const child of node.children) {
      if (this.isAssignable(child) && this.hasAccess(child.id)) return true;
      if (this.hasAnyAccessibleDescendant(child)) return true;
    }
    return false;
  }

  updateAccessLevel(menuId: number, event: Event): void {
    const val = (event.target as HTMLSelectElement).value;
    this.userAccesses[menuId] = val;
  }

  // ── Delta save ───────────────────────────────────────────────
  hasChanges(): boolean {
    const curr = Object.keys(this.userAccesses).map(Number).sort();
    const orig = Object.keys(this.originalUserAccesses).map(Number).sort();
    if (curr.length !== orig.length || JSON.stringify(curr) !== JSON.stringify(orig)) return true;
    return curr.some(id => this.userAccesses[id] !== this.originalUserAccesses[id]);
  }

  pendingChangesCount(): number {
    const ids = new Set([
      ...Object.keys(this.userAccesses).map(Number),
      ...Object.keys(this.originalUserAccesses).map(Number)
    ]);
    let n = 0;
    ids.forEach(id => { if (this.userAccesses[id] !== this.originalUserAccesses[id]) n++; });
    return n;
  }

  saveAccesses(): void {
    if (!this.selectedUser || !this.hasChanges() || this.saving) return;

    const cambios: AccessChange[] = [];
    const currKeys = Object.keys(this.userAccesses).map(Number);
    const origKeys = Object.keys(this.originalUserAccesses).map(Number);

    // Deleted
    for (const id of origKeys) {
      if (!currKeys.includes(id)) cambios.push({ menu_id: id, action: 'delete' });
    }
    // Added or updated
    for (const id of currKeys) {
      if (!origKeys.includes(id)) {
        cambios.push({ menu_id: id, action: 'add', access_level: this.userAccesses[id] });
      } else if (this.userAccesses[id] !== this.originalUserAccesses[id]) {
        cambios.push({ menu_id: id, action: 'update', access_level: this.userAccesses[id] });
      }
    }

    this.saving = true;
    this.saveError = null;
    this.saveSuccess = null;

    this.svc.saveUserAccesses(this.selectedUser.id, cambios).pipe(takeUntil(this.destroy$)).subscribe({
      next: () => {
        this.originalUserAccesses = { ...this.userAccesses };
        this.saving = false;
        this.saveSuccess = 'Accesos guardados correctamente.';
        setTimeout(() => { this.saveSuccess = null; }, 4000);
      },
      error: (err: any) => {
        this.saving = false;
        this.saveError = err.error?.detail ?? 'Error al guardar los accesos. Intenta de nuevo.';
      }
    });
  }

  // ── Apply preset (UI-only, no backend call) ───────────────────
  openPresetModal(): void {
    if (!this.selectedUser) return;
    this.selectedPresetId = null;
    this.showPresetModal = true;
  }

  closePresetModal(): void {
    this.showPresetModal = false;
    this.selectedPresetId = null;
  }

  confirmApplyPreset(): void {
    const preset = this.presets.find(p => p.id === this.selectedPresetId);
    if (!preset) return;
    // Replace local userAccesses from preset; do NOT touch originalUserAccesses
    // so the delta diff will detect all changes when "Guardar Cambios" is pressed.
    const newMap: Record<number, string> = {};
    preset.menus.forEach(m => { newMap[m.menu_id] = m.access_level; });
    this.userAccesses = newMap;
    this.showPresetModal = false;
    this.selectedPresetId = null;
  }

  // ── Clone profile (UI-only, no backend call) ──────────────────
  openCloneModal(): void {
    if (!this.selectedUser) return;
    this.cloneSourceUser = null;
    this.showCloneModal = true;
  }

  closeCloneModal(): void {
    this.showCloneModal = false;
    this.cloneSourceUser = null;
  }

  onCloneSourceSelected(user: UserSearchResult): void {
    this.cloneSourceUser = user;
  }

  onCloneSourceCleared(): void {
    this.cloneSourceUser = null;
  }

  confirmCloneProfile(): void {
    if (!this.cloneSourceUser || !this.selectedUser) return;
    if (this.cloneSourceUser.id === this.selectedUser.id) return; // guard: same user

    this.cloningProfile = true;
    this.svc.getUserAccesses(this.cloneSourceUser.id).pipe(takeUntil(this.destroy$)).subscribe({
      next: (accesses: UserAccess[]) => {
        // Replace local userAccesses from source user; do NOT touch originalUserAccesses
        const newMap: Record<number, string> = {};
        accesses.forEach(a => { newMap[a.menu_id] = a.access_level; });
        this.userAccesses = newMap;
        this.cloningProfile = false;
        this.showCloneModal = false;
        this.cloneSourceUser = null;
      },
      error: () => { this.cloningProfile = false; }
    });
  }

  // ── Toolbar: search + filter ──────────────────────────────────
  get isFiltering(): boolean {
    return this.searchTokens().length > 0 || this.statusFilter !== 'all';
  }

  private searchTokens(): string[] {
    return this.normalize(this.menuSearch).split(/\s+/).filter(Boolean);
  }

  private normalize(text: string): string {
    return text.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  }

  getVisibleTree(): TreeNode[] {
    if (!this.isFiltering) return this.menus;
    return this.filterNodes(this.menus, this.searchTokens(), false);
  }

  private filterNodes(nodes: TreeNode[], tokens: string[], textInherited: boolean): TreeNode[] {
    const result: TreeNode[] = [];
    for (const node of nodes) {
      const textOk = textInherited || tokens.length === 0 || this.matchesText(node, tokens);
      const children = this.filterNodes(node.children ?? [], tokens, textOk && tokens.length > 0);
      if ((textOk && this.matchesStatus(node)) || children.length) {
        result.push({ ...node, children });
      }
    }
    return result;
  }

  private matchesText(node: MenuHierarchyNode, tokens: string[]): boolean {
    const hay = this.normalize(`${node.label} ${node.description ?? ''} ${node.route ?? ''}`);
    return tokens.every(t => hay.includes(t));
  }

  private matchesStatus(node: MenuHierarchyNode): boolean {
    if (this.statusFilter === 'all') return true;
    if (!this.isAssignable(node)) return false;
    return this.statusFilter === 'with' ? this.hasAccess(node.id) : !this.hasAccess(node.id);
  }

  countMatches(nodes: TreeNode[] = this.getVisibleTree()): number {
    return nodes.reduce((n, m) =>
      n + (this.isDirectMatch(m) ? 1 : 0) + this.countMatches(m.children ?? []), 0);
  }

  isDirectMatch(node: TreeNode): boolean {
    if (!this.isFiltering) return false;
    const tokens = this.searchTokens();
    return (tokens.length === 0 || this.matchesText(node, tokens)) && this.matchesStatus(node);
  }

  // ── Collapse / expand ────────────────────────────────────────
  isExpanded(node: TreeNode): boolean {
    return this.isFiltering || !this.collapsedMenus.has(node.id);
  }

  toggleCollapse(node: TreeNode): void {
    if (this.collapsedMenus.has(node.id)) this.collapsedMenus.delete(node.id);
    else this.collapsedMenus.add(node.id);
  }

  collapseAll(): void {
    const walk = (nodes: TreeNode[]) => nodes.forEach(n => {
      if (n.children?.length) { this.collapsedMenus.add(n.id); walk(n.children); }
    });
    walk(this.menus);
  }

  expandAll(): void {
    this.collapsedMenus.clear();
  }

  clearFilters(): void {
    this.menuSearch = '';
    this.statusFilter = 'all';
  }

  /** Highlight matching text — returns plain string with <mark> tags */
  highlight(text: string): string {
    const tokens = this.searchTokens();
    if (!tokens.length || !text) return this.escapeHtml(text);

    const normalized = text.split('').map(c => {
      const n = this.normalize(c);
      return n.length === 1 ? n : c;
    }).join('');

    const marks = new Array(text.length).fill(false);
    for (const token of tokens) {
      let i = normalized.indexOf(token);
      while (i !== -1) {
        for (let k = i; k < i + token.length; k++) marks[k] = true;
        i = normalized.indexOf(token, i + token.length);
      }
    }
    if (!marks.includes(true)) return this.escapeHtml(text);

    let html = '';
    let open = false;
    text.split('').forEach((c, i) => {
      if (marks[i] && !open)  { html += '<mark class="hl">'; open = true; }
      if (!marks[i] && open) { html += '</mark>'; open = false; }
      html += this.escapeHtml(c);
    });
    if (open) html += '</mark>';
    return html;
  }

  private escapeHtml(t: string): string {
    return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
}
