"""Finance Budget: planned amounts per category for a week, a month or a financial year.

"Actual" is never stored: it is read from the posted ledger each time (see services/finance_budget.py).
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TenantModel


class FinBudgetPlan(TenantModel):
    __tablename__ = "fin_budget_plans"
    __table_args__ = (
        UniqueConstraint("tenant_id", "period_type", "period_start", "kind", "category", name="uq_fin_budget_plan"),
        CheckConstraint("period_type in ('week','month','year')", name="ck_fin_budget_plan_period"),
        CheckConstraint("kind in ('income','expense')", name="ck_fin_budget_plan_kind"),
        CheckConstraint("planned >= 0", name="ck_fin_budget_plan_planned"),
    )

    period_type: Mapped[str] = mapped_column(String(5), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(String(7), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    planned: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")


class FinBudgetOpening(TenantModel):
    """A hand-entered starting balance for one period. Without one, the cash/bank/wallet balance from the ledger is used."""
    __tablename__ = "fin_budget_openings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "period_type", "period_start", name="uq_fin_budget_opening"),
        CheckConstraint("period_type in ('week','month','year')", name="ck_fin_budget_opening_period"),
    )

    period_type: Mapped[str] = mapped_column(String(5), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    starting_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
