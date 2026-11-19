/** Result from GET /api/users/search */
export interface UserSearchResult {
  id: number;
  name: string;
  email: string;
  display: string;
}

/** Access level entry from GET /api/access-levels */
export interface AccessLevel {
  key: string;
  name: string;
}

/** Hierarchical menu node from GET /api/menus/hierarchy */
export interface MenuHierarchyNode {
  id: number;
  parent_id: number | null;
  label: string;
  icon: string | null;
  route: string | null;
  description: string | null;
  order: number;
  is_free: boolean;
  has_access_levels: boolean;
  level: number;
  children: MenuHierarchyNode[];
}

/** User access record from GET /api/users/{id}/accesses */
export interface UserAccess {
  menu_id: number;
  access_level: string;
}

/** Change entry for PUT /api/users/{id}/accesses */
export interface AccessChange {
  menu_id: number;
  action: 'add' | 'update' | 'delete';
  access_level?: string;
}

/** Preset profile from GET /api/access-presets */
export interface AccessPreset {
  id: number;
  name: string;
  description: string | null;
  menus: { menu_id: number; access_level: string }[];
}
