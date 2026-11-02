"""Default onboarding / offboarding templates and requested documents (N-01)."""

# (order, title, owner_role, phase, due_offset_days, depends_on_order, kind, provision_key, link_url, description)
ONBOARDING_TASKS = [
    (0, "Send welcome message", "hr", "pre_boarding", -5, None, "manual", "welcome", None,
     "Send the new hire a warm welcome with the first-day details."),
    (1, "Fill in personal details (pre-boarding form)", "employee", "pre_boarding", -5, None, "form", None, None, None),
    (2, "Upload required documents", "employee", "pre_boarding", -3, None, "document", None, None, None),
    (3, "Acknowledge company policies", "employee", "pre_boarding", -2, None, "acknowledge", None, None, None),
    (4, "Verify submitted documents", "hr", "pre_boarding", -1, 2, "manual", None, None, None),
    (5, "Create login account", "hr", "pre_boarding", -1, None, "provision", "account", "/employees/{employee_id}", None),
    (6, "Assign laptop and equipment", "it", "pre_boarding", -1, None, "provision", "asset", "/assets", None),
    (7, "Enroll the device", "it", "day_1", 0, 6, "provision", "device", "/devices", None),
    (8, "Assign shift", "hr", "day_1", 0, None, "provision", "shift", "/shifts", None),
    (9, "Assign leave policy and balances", "hr", "day_1", 0, None, "provision", "leave_policy", "/leave", None),
    (10, "Set salary structure and pay items", "hr", "day_1", 0, None, "provision", "salary", "/employees/{employee_id}", None),
    (11, "Introduce the buddy and the team", "manager", "day_1", 0, None, "manual", None, None, None),
    (12, "Share the first-week plan", "manager", "first_week", 1, None, "manual", None, None, None),
    (13, "Complete orientation / training", "employee", "first_week", 5, None, "manual", None, None, None),
    (14, "30-day check-in", "manager", "probation", 30, None, "manual", None, None, None),
    (15, "60-day check-in", "manager", "probation", 60, None, "manual", None, None, None),
    (16, "90-day review and confirmation decision", "manager", "probation", 90, None, "manual", None, None, None),
]

OFFBOARDING_TASKS = [
    (0, "Confirm resignation and last working day", "hr", "exit", -14, None, "manual", None, None, None),
    (1, "Hand over work to the team", "manager", "exit", -7, None, "manual", None, None, None),
    (2, "Exit interview", "hr", "exit", -2, None, "manual", None, None, None),
    (3, "Return laptop, ID card and other assets", "it", "exit", 0, None, "provision", "asset", "/assets", None),
    (4, "Revoke system access", "it", "exit", 0, 3, "provision", "access", "/employees/{employee_id}", None),
    (5, "Clearance from departments", "hr", "exit", 0, None, "manual", None, None, None),
    (6, "Prepare final settlement", "hr", "exit", 3, 5, "provision", "salary", "/payroll", None),
]

# (document_type, title, is_required) — document_type matches DocumentType values.
DEFAULT_DOCUMENTS = [
    ("national_id", "CNIC / National ID (front and back)", True),
    ("photo", "Passport-size photo", True),
    ("educational_certificate", "Latest degree / educational certificate", True),
    ("resume_cv", "Resume / CV", False),
    ("bank_document", "Bank account proof (cheque or statement)", False),
]
