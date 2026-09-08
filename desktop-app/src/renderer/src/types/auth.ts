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
  is_platform_admin: boolean;
  is_2fa_enabled: boolean;
}
