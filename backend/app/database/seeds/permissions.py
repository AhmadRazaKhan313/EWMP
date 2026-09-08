"""
Permission registry.

This is the single source of truth for all permission codenames in the platform.
Run via: python manage.py seed --permissions

Format: (resource, action, label, category, is_sensitive)
"""

PERMISSION_REGISTRY: list[dict] = [
    # ── Employees ────────────────────────────────────────────────
    {"resource": "employees", "action": "view",         "label": "View Employees",            "category": "HR Management",      "is_sensitive": False},
    {"resource": "employees", "action": "create",       "label": "Create Employees",          "category": "HR Management",      "is_sensitive": False},
    {"resource": "employees", "action": "update",       "label": "Update Employee Details",   "category": "HR Management",      "is_sensitive": False},
    {"resource": "employees", "action": "delete",       "label": "Delete Employees",          "category": "HR Management",      "is_sensitive": True},
    {"resource": "employees", "action": "export",       "label": "Export Employee Data",      "category": "HR Management",      "is_sensitive": True},
    {"resource": "employees", "action": "view_salary",  "label": "View Employee Salary",      "category": "HR Management",      "is_sensitive": True},
    {"resource": "employees", "action": "upload_documents", "label": "Upload Employee Documents", "category": "HR Management",  "is_sensitive": True},
    {"resource": "employees", "action": "view_documents",   "label": "View Employee Documents",   "category": "HR Management",  "is_sensitive": True},
    {"resource": "employees", "action": "delete_documents", "label": "Delete Employee Documents", "category": "HR Management",  "is_sensitive": True},

    # ── Departments / Structure ───────────────────────────────────
    {"resource": "departments",  "action": "view",    "label": "View Departments",       "category": "HR Management", "is_sensitive": False},
    {"resource": "departments",  "action": "manage",  "label": "Manage Departments",     "category": "HR Management", "is_sensitive": False},
    {"resource": "designations", "action": "manage",  "label": "Manage Designations",    "category": "HR Management", "is_sensitive": False},
    {"resource": "branches",     "action": "manage",  "label": "Manage Branches",        "category": "HR Management", "is_sensitive": False},
    {"resource": "teams",        "action": "manage",  "label": "Manage Teams",           "category": "HR Management", "is_sensitive": False},

    # ── Attendance ────────────────────────────────────────────────
    {"resource": "attendance", "action": "view",        "label": "View Attendance",           "category": "Attendance",         "is_sensitive": False},
    {"resource": "attendance", "action": "view_own",    "label": "View Own Attendance",       "category": "Attendance",         "is_sensitive": False},
    {"resource": "attendance", "action": "regularize",  "label": "Regularize Attendance",     "category": "Attendance",         "is_sensitive": False},
    {"resource": "attendance", "action": "export",      "label": "Export Attendance",         "category": "Attendance",         "is_sensitive": False},

    # ── Leave ─────────────────────────────────────────────────────
    {"resource": "leave", "action": "view",          "label": "View Leave Requests",       "category": "Leave Management",   "is_sensitive": False},
    {"resource": "leave", "action": "apply",         "label": "Apply for Leave",           "category": "Leave Management",   "is_sensitive": False},
    {"resource": "leave", "action": "approve",       "label": "Approve/Reject Leave",      "category": "Leave Management",   "is_sensitive": False},
    {"resource": "leave", "action": "manage_types",  "label": "Manage Leave Types",        "category": "Leave Management",   "is_sensitive": False},
    {"resource": "leave", "action": "manage_balance","label": "Manage Leave Balances",     "category": "Leave Management",   "is_sensitive": False},

    # ── Payroll ───────────────────────────────────────────────────
    {"resource": "payroll", "action": "view",           "label": "View Payroll",              "category": "Payroll",            "is_sensitive": True},
    {"resource": "payroll", "action": "process",        "label": "Process Payroll",           "category": "Payroll",            "is_sensitive": True},
    {"resource": "payroll", "action": "approve",        "label": "Approve Payroll Runs",      "category": "Payroll",            "is_sensitive": True},
    {"resource": "payroll", "action": "view_own",       "label": "View Own Payslip",          "category": "Payroll",            "is_sensitive": False},
    {"resource": "payroll", "action": "export",         "label": "Export Payroll Data",       "category": "Payroll",            "is_sensitive": True},
    {"resource": "payroll", "action": "manage_structure","label": "Manage Salary Structures", "category": "Payroll",            "is_sensitive": True},

    # ── Recruitment ───────────────────────────────────────────────
    {"resource": "recruitment", "action": "view",       "label": "View Recruitment",          "category": "Recruitment",        "is_sensitive": False},
    {"resource": "recruitment", "action": "manage",     "label": "Manage Jobs & Applicants",  "category": "Recruitment",        "is_sensitive": False},
    {"resource": "recruitment", "action": "interview",  "label": "Conduct Interviews",        "category": "Recruitment",        "is_sensitive": False},

    # ── Performance ───────────────────────────────────────────────
    {"resource": "performance", "action": "view",       "label": "View Performance",          "category": "Performance",        "is_sensitive": False},
    {"resource": "performance", "action": "manage",     "label": "Manage Goals & Reviews",    "category": "Performance",        "is_sensitive": False},
    {"resource": "performance", "action": "review",     "label": "Submit Performance Reviews","category": "Performance",        "is_sensitive": False},

    # ── Devices ───────────────────────────────────────────────────
    {"resource": "devices", "action": "view",           "label": "View Devices",              "category": "Device Management",  "is_sensitive": False},
    {"resource": "devices", "action": "enroll",         "label": "Enroll Devices",            "category": "Device Management",  "is_sensitive": False},
    {"resource": "devices", "action": "remote_control", "label": "Remote Control Devices",    "category": "Device Management",  "is_sensitive": True},
    {"resource": "devices", "action": "remote_commands","label": "Execute Remote Commands",   "category": "Device Management",  "is_sensitive": True},
    {"resource": "devices", "action": "decommission",   "label": "Decommission Devices",      "category": "Device Management",  "is_sensitive": True},
    {"resource": "devices", "action": "view_processes", "label": "View Running Processes",    "category": "Device Management",  "is_sensitive": True},
    {"resource": "devices", "action": "view_screen",    "label": "View Screen Captures",       "category": "Device Management",  "is_sensitive": True},
    {"resource": "devices", "action": "view_alerts",    "label": "View Activity Alerts",       "category": "Device Management",  "is_sensitive": True},

    # ── Assets ────────────────────────────────────────────────────
    {"resource": "assets", "action": "view",            "label": "View Assets",               "category": "Asset Management",   "is_sensitive": False},
    {"resource": "assets", "action": "manage",          "label": "Manage Assets",             "category": "Asset Management",   "is_sensitive": False},
    {"resource": "assets", "action": "assign",          "label": "Assign/Return Assets",      "category": "Asset Management",   "is_sensitive": False},
    {"resource": "assets", "action": "dispose",         "label": "Dispose Assets",            "category": "Asset Management",   "is_sensitive": True},

    # ── Helpdesk ──────────────────────────────────────────────────
    {"resource": "helpdesk", "action": "view",          "label": "View Tickets",              "category": "IT Helpdesk",        "is_sensitive": False},
    {"resource": "helpdesk", "action": "create",        "label": "Create Tickets",            "category": "IT Helpdesk",        "is_sensitive": False},
    {"resource": "helpdesk", "action": "manage",        "label": "Manage All Tickets",        "category": "IT Helpdesk",        "is_sensitive": False},
    {"resource": "helpdesk", "action": "assign",        "label": "Assign Tickets",            "category": "IT Helpdesk",        "is_sensitive": False},

    # ── Reports ───────────────────────────────────────────────────
    {"resource": "reports", "action": "view",           "label": "View Reports",              "category": "Reports & Analytics","is_sensitive": False},
    {"resource": "reports", "action": "create",         "label": "Create Custom Reports",     "category": "Reports & Analytics","is_sensitive": False},
    {"resource": "reports", "action": "export",         "label": "Export Reports",            "category": "Reports & Analytics","is_sensitive": True},
    {"resource": "reports", "action": "schedule",       "label": "Schedule Reports",          "category": "Reports & Analytics","is_sensitive": False},

    # ── Workflows ─────────────────────────────────────────────────
    {"resource": "workflows", "action": "view",         "label": "View Workflows",            "category": "Automation",         "is_sensitive": False},
    {"resource": "workflows", "action": "manage",       "label": "Build & Edit Workflows",    "category": "Automation",         "is_sensitive": False},
    {"resource": "workflows", "action": "activate",     "label": "Activate/Deactivate Workflows","category": "Automation",      "is_sensitive": False},

    # ── Integrations ──────────────────────────────────────────────
    {"resource": "integrations", "action": "view",      "label": "View Integrations",         "category": "Integrations",       "is_sensitive": False},
    {"resource": "integrations", "action": "manage",    "label": "Manage Integrations",       "category": "Integrations",       "is_sensitive": True},
    {"resource": "webhooks",     "action": "manage",    "label": "Manage Webhooks",           "category": "Integrations",       "is_sensitive": True},
    {"resource": "api_keys",     "action": "manage",    "label": "Manage API Keys",           "category": "Integrations",       "is_sensitive": True},

    # ── Settings ──────────────────────────────────────────────────
    {"resource": "settings", "action": "view",          "label": "View Settings",             "category": "Organization",       "is_sensitive": False},
    {"resource": "settings", "action": "manage",        "label": "Manage Organization Settings","category": "Organization",     "is_sensitive": True},
    {"resource": "roles",    "action": "manage",        "label": "Manage Roles & Permissions","category": "Organization",       "is_sensitive": True},
    {"resource": "billing",  "action": "view",          "label": "View Billing",              "category": "Organization",       "is_sensitive": True},
    {"resource": "billing",  "action": "manage",        "label": "Manage Billing",            "category": "Organization",       "is_sensitive": True},
    {"resource": "audit_logs","action": "view",         "label": "View Audit Logs",           "category": "Organization",       "is_sensitive": True},
]


def get_codename(resource: str, action: str) -> str:
    return f"{resource}.{action}"


# Build lookup dict: codename → full permission dict
PERMISSIONS_BY_CODENAME: dict[str, dict] = {
    get_codename(p["resource"], p["action"]): p
    for p in PERMISSION_REGISTRY
}
