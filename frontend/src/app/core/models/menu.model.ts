/** Navigation menu item used by the sidebar/auth service */
export interface MenuItem {
  id: number;
  label: string;
  icon: string;
  route: string;
  order: number;
  children: MenuItem[];
}

/** Full admin menu record returned by GET /api/menus/manage */
export interface AdminMenu {
  id: number;
  parent_id: number | null;
  label: string;
  icon: string | null;
  route: string | null;
  description: string | null;
  order: number;
  is_free: boolean;
  has_access_levels: boolean;
  is_active: boolean;
}
