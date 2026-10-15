/**
 * Mirrors backend/app/schemas/auth.py — kept in sync manually (no shared
 * package between backend and desktop-app yet).
 */
export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface UserInToken {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  full_name: string;
  avatar_url: string | null;
  is_platform_admin: boolean;
  organization_id: string | null;
  organization_slug: string | null;
  roles: string[];
  permissions: string[];
  must_change_password: boolean;
}

/** POST /auth/login response — NOTE the nested `tokens` key. This is the
 * exact shape whose mismatch with the flat /auth/refresh response caused a
 * suspected (and here, avoided) bug — see shared/api-client.ts. */
export interface AuthResponse {
  tokens: TokenResponse;
  user: UserInToken;
}

export interface MeResponse {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  full_name: string;
  avatar_url: string | null;
  phone: string | null;
  bio: string | null;
  is_platform_admin: boolean;
  is_2fa_enabled: boolean;
  organization_id: string | null;
  roles: string[];
  permissions: string[];
  has_full_access: boolean;
  has_employee_profile: boolean;
  must_change_password: boolean;
  preferences: Record<string, unknown>;
}

/** PATCH /auth/me body — only these four are editable here; email, roles,
 * and org membership go through an admin-facing flow instead. */
export interface ProfileUpdatePayload {
  first_name?: string;
  last_name?: string;
  phone?: string;
  bio?: string;
}
