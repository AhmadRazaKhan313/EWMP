// ── API Response Envelope ─────────────────────────────────────────────────────
export interface APIError {
  error: string;
  message: string;
  detail: unknown | null;
  request_id: string | null;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// ── Auth ──────────────────────────────────────────────────────────────────────
export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in: number;
}

export interface AuthUser {
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
  has_full_access: boolean;
}

export interface AuthResponse {
  tokens: TokenResponse;
  user: AuthUser;
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
  preferences: Record<string, unknown>;
}

// ── Employee ──────────────────────────────────────────────────────────────────
export type EmploymentStatus =
  | "active"
  | "on_leave"
  | "probation"
  | "notice_period"
  | "terminated"
  | "resigned";

export type EmploymentType =
  | "full_time"
  | "part_time"
  | "contract"
  | "intern"
  | "freelance";

export interface EmployeeListItem {
  id: string;
  employee_code: string;
  first_name: string;
  last_name: string;
  full_name: string;
  avatar_url: string | null;
  employment_status: EmploymentStatus;
  employment_type: EmploymentType;
  date_of_joining: string;
  department_id: string | null;
  designation_id: string | null;
  branch_id: string | null;
  work_phone: string | null;
  is_remote: boolean;
  years_of_service: number;
}

export interface EmployeeDetail extends EmployeeListItem {
  user_id: string;
  email: string | null;
  date_of_birth: string | null;
  gender: string | null;
  marital_status: string | null;
  nationality: string | null;
  blood_group: string | null;
  personal_email: string | null;
  personal_phone: string | null;
  address: Record<string, string> | null;
  national_id: string | null;
  passport_number: string | null;
  passport_expiry: string | null;
  emergency_contact: Record<string, string> | null;
  work_location: string | null;
  is_remote: boolean;
  current_salary: string | null;
  currency: string;
  manager_id: string | null;
  team_id: string | null;
  notice_period_days: number;
  custom_fields: Record<string, unknown>;
}

// ── Attendance ────────────────────────────────────────────────────────────────
export type AttendanceStatus =
  | "present"
  | "absent"
  | "late"
  | "half_day"
  | "on_leave"
  | "holiday"
  | "weekend"
  | "work_from_home";

export interface AttendanceRecord {
  id: string;
  employee_id: string;
  date: string;
  check_in: string | null;
  check_out: string | null;
  status: AttendanceStatus;
  total_minutes: number | null;
  overtime_minutes: number | null;
  late_minutes: number | null;
  is_regularized: boolean;
}

// ── Device ────────────────────────────────────────────────────────────────────
export type DeviceStatus =
  | "online"
  | "offline"
  | "idle"
  | "locked"
  | "sleeping"
  | "decommissioned";

export interface Device {
  id: string;
  hostname: string;
  device_name: string | null;
  os_type: string;
  os_name: string | null;
  os_version: string | null;
  status: DeviceStatus;
  last_seen_at: string | null;
  health_score: number | null;
  cpu_usage_percent: number | null;
  ram_usage_percent: number | null;
  disk_usage_percent: number | null;
  assigned_employee_id: string | null;
  public_ip: string | null;
  local_ip: string | null;
}

export interface DeviceLatestMetric {
  recorded_at: string;
  cpu_usage_percent: number | null;
  ram_usage_percent: number | null;
  ram_used_gb: number | null;
  disk_usage_percent: number | null;
  disk_used_gb: number | null;
  battery_percent: number | null;
  battery_is_charging: boolean | null;
  uptime_seconds: number | null;
  active_user: string | null;
}

export interface DeviceAssignedEmployee {
  id: string;
  full_name: string | null;
  employee_code: string;
}

export interface DeviceDetail {
  id: string;
  hostname: string;
  device_name: string | null;
  serial_number: string | null;
  asset_tag: string | null;
  status: DeviceStatus;
  is_enrolled: boolean;
  agent_version: string | null;
  os_type: string;
  os_name: string | null;
  os_version: string | null;
  os_build: string | null;
  bios_version: string | null;
  motherboard: string | null;
  cpu_model: string | null;
  cpu_cores: number | null;
  cpu_threads: number | null;
  ram_total_gb: number | null;
  disk_total_gb: number | null;
  gpu_model: string | null;
  public_ip: string | null;
  local_ip: string | null;
  mac_address: string | null;
  last_seen_at: string | null;
  last_heartbeat_at: string | null;
  health_score: number | null;
  health_issues: string[];
  installed_apps: unknown[];
  assigned_employee: DeviceAssignedEmployee | null;
  branch_id: string | null;
  notes: string | null;
  latest_metric: DeviceLatestMetric | null;
}

export interface DeviceMetricPoint {
  recorded_at: string;
  cpu_usage_percent: number | null;
  ram_usage_percent: number | null;
  disk_usage_percent: number | null;
  battery_percent: number | null;
}

export interface DeviceProcess {
  pid: number;
  name: string;
  memory_percent: number;
  cpu_percent: number | null;
}

export interface DeviceScreenshotItem {
  id: string;
  captured_at: string;
  width: number | null;
  height: number | null;
  file_size_bytes: number;
  requested_by_id: string | null;
}

export interface DeviceAlertItem {
  id: string;
  alert_type: "flagged_app_usage" | "flagged_browsing";
  matched_term: string;
  detail: string;
  occurred_at: string;
  is_acknowledged: boolean;
}

export interface RecentAlertItem extends DeviceAlertItem {
  device_id: string;
  device_name: string;
}

export interface AllowedAppItem {
  id: string;
  domain_or_app: string;
  reason: string | null;
  allowed_by_id: string | null;
  created_at: string;
}

// ── Notification ──────────────────────────────────────────────────────────────
export interface Notification {
  id: string;
  title: string;
  body: string | null;
  type: string;
  icon: string | null;
  action_url: string | null;
  is_read: boolean;
  created_at: string;
}

// ── Navigation ────────────────────────────────────────────────────────────────
export interface NavItem {
  label: string;
  href: string;
  icon: string;
  permission?: string;
  badge?: number | string;
  children?: NavItem[];
}

// ── UI ────────────────────────────────────────────────────────────────────────
export type SortDirection = "asc" | "desc";

export interface TableSort {
  column: string;
  direction: SortDirection;
}

export interface TableFilters {
  [key: string]: string | string[] | boolean | null | undefined;
}