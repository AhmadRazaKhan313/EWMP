"""Model registry — all models imported for Alembic autogenerate."""
from app.models.base import Base, TenantModel, PlatformModel  # noqa: F401
from app.models.organization import Organization  # noqa: F401
from app.models.user import RefreshSession, User, user_roles  # noqa: F401
from app.models.rbac import Role, Permission, role_permissions  # noqa: F401
from app.models.employee import Employee  # noqa: F401
from app.models.documents import EmployeeDocument  # noqa: F401
from app.models.organization_structure import Department, Designation, Branch, Team  # noqa: F401
from app.models.attendance import AttendanceRecord, LeaveType, LeaveBalance, LeaveRequest, Holiday, Shift  # noqa: F401
from app.models.devices import Device, DeviceMetric, DeviceScreenshot, DeviceAlert, DeviceAllowedApp, Asset, AssetAssignment  # noqa: F401
from app.models.payroll import SalaryStructure, SalaryComponent, EmployeeSalary, PayrollRun, Payslip, PayslipLine  # noqa: F401
from app.models.workflows import WorkflowDefinition, WorkflowRun, WorkflowRunLog, AuditLog, Notification, APIKey, Webhook  # noqa: F401
from app.models.recruitment import JobPosting, Applicant  # noqa: F401
from app.models.performance import Goal, PerformanceReview  # noqa: F401
from app.models.helpdesk import SupportTicket  # noqa: F401
from app.models.onboarding import OnboardingTemplate, OnboardingTemplateTask, Offer, OnboardingCase, OnboardingCaseTask, OnboardingCaseDocument  # noqa: F401
from app.models.break_policy import BreakPolicy, BreakOverride, BreakUnlockRequest  # noqa: F401
from app.models.finance import FinAccount, FinJournalEntry, FinJournalLine, FinExchangeRate, FinTaxRate  # noqa: F401
from app.models.finance_sales import FinCustomer, FinInvoice, FinInvoiceLine, FinPayment, FinPaymentAllocation  # noqa: F401
from app.models.finance_purchases import FinVendor, FinBill, FinBillLine, FinBillPayment, FinBillPaymentAllocation  # noqa: F401
from app.models.finance_budget import FinBudgetPlan, FinBudgetOpening  # noqa: F401
from app.models.finance_banking import FinBankStatement, FinBankLine, FinBankReconciliation  # noqa: F401
from app.models.finance_close import FinPeriodClose  # noqa: F401
