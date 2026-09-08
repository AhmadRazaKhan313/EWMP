"""
Tests for Payroll Phase 1: settings, salary structure/component versioning,
and PayrollComponentRule resolution.

Run:  cd backend && pytest tests/test_payroll_phase1_settings_and_versioning.py -v
"""
import asyncio
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio

TENANT = uuid.uuid4()


def _run(coro):
    return asyncio.run(coro)


# ── _component_amount resolution order ──────────────────────────────────────
# Pure-function tests, no DB needed — this is the single most important piece
# of correctness in this phase: a PayrollComponentRule must win over the
# legacy JSON override, which must win over the component's own definition.
class TestComponentAmountResolutionOrder:
    def _component(self, **overrides):
        from app.models.payroll import ComponentCalculation, ComponentType

        defaults = dict(
            id=uuid.uuid4(), code="HOUSE", calculation_type=ComponentCalculation.PERCENTAGE_OF_BASIC,
            amount=None, percentage=Decimal("20"), component_type=ComponentType.EARNING,
        )
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_uses_component_definition_when_nothing_overrides_it(self):
        from app.api.v1.hrms.payroll import _component_amount

        comp = self._component(percentage=Decimal("20"))
        result = _component_amount(comp, Decimal("100000"), Decimal("0"), overrides={}, component_rules={})
        assert result == Decimal("20000.00")

    def test_legacy_json_override_wins_over_component_definition(self):
        from app.api.v1.hrms.payroll import _component_amount

        comp = self._component(percentage=Decimal("20"))
        result = _component_amount(comp, Decimal("100000"), Decimal("0"), overrides={"HOUSE": "5000"}, component_rules={})
        assert result == Decimal("5000")

    def test_component_rule_wins_over_legacy_json_override(self):
        from app.api.v1.hrms.payroll import _component_amount
        from app.models.payroll import ComponentRuleOverrideType

        comp = self._component(percentage=Decimal("20"))
        rule = SimpleNamespace(
            override_type=ComponentRuleOverrideType.FIXED_AMOUNT, amount=Decimal("7500"), percentage=None,
        )
        result = _component_amount(
            comp, Decimal("100000"), Decimal("0"),
            overrides={"HOUSE": "5000"}, component_rules={comp.id: rule},
        )
        assert result == Decimal("7500")

    def test_component_rule_percentage_of_basic(self):
        from app.api.v1.hrms.payroll import _component_amount
        from app.models.payroll import ComponentRuleOverrideType

        comp = self._component(percentage=Decimal("20"))
        rule = SimpleNamespace(
            override_type=ComponentRuleOverrideType.PERCENTAGE_OF_BASIC, amount=None, percentage=Decimal("30"),
        )
        result = _component_amount(comp, Decimal("100000"), Decimal("0"), overrides={}, component_rules={comp.id: rule})
        assert result == Decimal("30000.00")

    def test_component_rule_percentage_of_gross(self):
        from app.api.v1.hrms.payroll import _component_amount
        from app.models.payroll import ComponentRuleOverrideType

        comp = self._component(percentage=Decimal("20"))
        rule = SimpleNamespace(
            override_type=ComponentRuleOverrideType.PERCENTAGE_OF_GROSS, amount=None, percentage=Decimal("10"),
        )
        result = _component_amount(comp, Decimal("100000"), Decimal("50000"), overrides={}, component_rules={comp.id: rule})
        assert result == Decimal("5000.00")

    def test_a_rule_for_a_different_component_does_not_apply(self):
        """component_rules is keyed by component id — a rule for some OTHER
        component must never leak onto this one."""
        from app.api.v1.hrms.payroll import _component_amount
        from app.models.payroll import ComponentRuleOverrideType

        comp = self._component(percentage=Decimal("20"))
        other_rule = SimpleNamespace(
            override_type=ComponentRuleOverrideType.FIXED_AMOUNT, amount=Decimal("999999"), percentage=None,
        )
        result = _component_amount(
            comp, Decimal("100000"), Decimal("0"),
            overrides={}, component_rules={uuid.uuid4(): other_rule},
        )
        assert result == Decimal("20000.00")  # falls through to component's own definition

    def test_formula_type_still_returns_zero_stub_pending_phase2(self):
        from app.api.v1.hrms.payroll import _component_amount
        from app.models.payroll import ComponentCalculation

        comp = self._component(calculation_type=ComponentCalculation.FORMULA, formula="BASIC * 0.1")
        result = _component_amount(comp, Decimal("100000"), Decimal("0"), overrides={}, component_rules={})
        assert result == Decimal("0")


# ── PayrollSettings get-or-create + validation ──────────────────────────────
class _FakeResult:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class _FakeDB:
    def __init__(self, results):
        self._queue = list(results)
        self.added = []

    async def execute(self, stmt):
        if not self._queue:
            raise AssertionError("FakeDB: ran out of queued results.")
        return self._queue.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass


class TestPayrollSettingsGetOrCreate:
    def test_creates_defaults_when_no_settings_row_exists_yet(self):
        from app.api.v1.hrms.payroll import _get_or_create_settings

        db = _FakeDB([_FakeResult(scalar=None)])
        settings = _run(_get_or_create_settings(db, TENANT))

        assert settings.tenant_id == TENANT
        assert db.added == [settings]

    def test_returns_existing_row_without_creating_a_duplicate(self):
        from app.api.v1.hrms.payroll import _get_or_create_settings
        from app.models.payroll import PayrollSettings

        existing = PayrollSettings(tenant_id=TENANT)
        db = _FakeDB([_FakeResult(scalar=existing)])
        settings = _run(_get_or_create_settings(db, TENANT))

        assert settings is existing
        assert db.added == []


class TestPayrollSettingsValidation:
    def test_rejects_fixed_divisor_method_with_no_divisor_set(self):
        from app.api.v1.hrms.payroll import update_payroll_settings, PayrollSettingsUpdate
        from app.core.exceptions import ValidationError
        from app.models.payroll import PayrollSettings, WorkingDaysMethod

        existing = PayrollSettings(tenant_id=TENANT)  # no fixed_monthly_divisor set
        db = _FakeDB([_FakeResult(scalar=existing)])
        body = PayrollSettingsUpdate(working_days_method=WorkingDaysMethod.FIXED_DIVISOR)
        user = SimpleNamespace(id=uuid.uuid4())

        with pytest.raises(ValidationError):
            _run(update_payroll_settings(body, user, TENANT, db))

    def test_accepts_fixed_divisor_method_when_divisor_provided_in_same_request(self):
        from app.api.v1.hrms.payroll import update_payroll_settings, PayrollSettingsUpdate
        from app.models.payroll import PayrollSettings, WorkingDaysMethod, PayrollFrequency, RoundingMode

        existing = PayrollSettings(
            tenant_id=TENANT, frequency=PayrollFrequency.MONTHLY, period_start_day=1,
            pay_date_offset_days=0, working_days_method=WorkingDaysMethod.WORKING_DAYS,
            rounding_mode=RoundingMode.HALF_UP, decimal_precision=2, default_currency="USD",
            allow_negative_net_salary=False, proration_method=WorkingDaysMethod.CALENDAR_DAYS,
        )
        db = _FakeDB([_FakeResult(scalar=existing)])
        body = PayrollSettingsUpdate(
            working_days_method=WorkingDaysMethod.FIXED_DIVISOR, fixed_monthly_divisor=Decimal("30"),
        )
        user = SimpleNamespace(id=uuid.uuid4())

        result = _run(update_payroll_settings(body, user, TENANT, db))
        assert result["working_days_method"] == "fixed_divisor"
        assert result["fixed_monthly_divisor"] == "30"


# ── Structure/component versioning — real in-memory async DB ───────────────
# Uses a real SQLAlchemy session (SQLite) rather than fakes: the bug this
# guards against (copy-vs-move of components onto a new structure version)
# is about actual relationship/FK behavior across two structure rows, which
# a fake queued-results DB can't meaningfully exercise.
class TestTaxBracketValidation:
    def test_rejects_overlapping_brackets(self):
        from app.api.v1.hrms.payroll import create_tax_rule, TaxRuleCreate, TaxBracketInput
        from app.core.exceptions import ValidationError

        body = TaxRuleCreate(
            name="Bad Rule", country="Testland", tax_year="2026", effective_from=date(2026, 1, 1),
            brackets=[
                TaxBracketInput(min_amount=Decimal("0"), max_amount=Decimal("60000"), rate_percentage=Decimal("10")),
                TaxBracketInput(min_amount=Decimal("50000"), max_amount=None, rate_percentage=Decimal("20")),  # overlaps!
            ],
        )
        user = SimpleNamespace(id=uuid.uuid4())
        with pytest.raises(ValidationError, match="overlap"):
            _run(create_tax_rule(body, user, TENANT, _FakeDB([])))

    def test_rejects_rate_over_100(self):
        from app.api.v1.hrms.payroll import create_tax_rule, TaxRuleCreate, TaxBracketInput
        from app.core.exceptions import ValidationError

        body = TaxRuleCreate(
            name="Bad Rule", country="Testland", tax_year="2026", effective_from=date(2026, 1, 1),
            brackets=[TaxBracketInput(min_amount=Decimal("0"), max_amount=None, rate_percentage=Decimal("150"))],
        )
        user = SimpleNamespace(id=uuid.uuid4())
        with pytest.raises(ValidationError):
            _run(create_tax_rule(body, user, TENANT, _FakeDB([])))

    def test_rejects_max_amount_not_greater_than_min(self):
        from app.api.v1.hrms.payroll import create_tax_rule, TaxRuleCreate, TaxBracketInput
        from app.core.exceptions import ValidationError

        body = TaxRuleCreate(
            name="Bad Rule", country="Testland", tax_year="2026", effective_from=date(2026, 1, 1),
            brackets=[TaxBracketInput(min_amount=Decimal("50000"), max_amount=Decimal("40000"), rate_percentage=Decimal("10"))],
        )
        user = SimpleNamespace(id=uuid.uuid4())
        with pytest.raises(ValidationError):
            _run(create_tax_rule(body, user, TENANT, _FakeDB([])))


class TestContributionRuleValidation:
    def test_rejects_rule_with_no_amounts_set_at_all(self):
        from app.api.v1.hrms.payroll import create_contribution_rule, ContributionRuleCreate
        from app.core.exceptions import ValidationError

        body = ContributionRuleCreate(name="Empty Rule", code="EMPTY")
        user = SimpleNamespace(id=uuid.uuid4())
        with pytest.raises(ValidationError):
            _run(create_contribution_rule(body, user, TENANT, _FakeDB([])))

    def test_rejects_min_base_greater_than_max_base(self):
        from app.api.v1.hrms.payroll import create_contribution_rule, ContributionRuleCreate
        from app.core.exceptions import ValidationError

        body = ContributionRuleCreate(
            name="Bad Base", code="BADBASE", employee_percentage=Decimal("5"),
            min_base=Decimal("50000"), max_base=Decimal("10000"),
        )
        user = SimpleNamespace(id=uuid.uuid4())
        with pytest.raises(ValidationError):
            _run(create_contribution_rule(body, user, TENANT, _FakeDB([])))

    def test_accepts_valid_rule(self):
        from app.api.v1.hrms.payroll import create_contribution_rule, ContributionRuleCreate

        body = ContributionRuleCreate(name="Pension", code="PENSION", employee_percentage=Decimal("5"), employer_percentage=Decimal("8"))
        user = SimpleNamespace(id=uuid.uuid4())
        result = _run(create_contribution_rule(body, user, TENANT, _FakeDB([])))
        assert result["code"] == "PENSION"
        assert result["employee_percentage"] == "5"


class TestFormulaValidationEndpoint:
    def test_valid_formula_reports_no_errors(self):
        from app.api.v1.hrms.payroll import validate_formula_endpoint

        user = SimpleNamespace(id=uuid.uuid4())
        result = _run(validate_formula_endpoint("BASIC * 0.1", [], user))
        assert result["valid"] is True

    def test_syntax_error_is_reported(self):
        from app.api.v1.hrms.payroll import validate_formula_endpoint

        user = SimpleNamespace(id=uuid.uuid4())
        result = _run(validate_formula_endpoint("BASIC * ", [], user))
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_unknown_component_code_is_reported(self):
        from app.api.v1.hrms.payroll import validate_formula_endpoint

        user = SimpleNamespace(id=uuid.uuid4())
        result = _run(validate_formula_endpoint("BASIC + NOT_A_REAL_CODE", ["BASIC", "HOUSE"], user))
        assert result["valid"] is False


class TestStructureVersioningCopiesNotMoves:
    @pytest_asyncio.fixture
    async def db_session(self):
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker
        from app.core.database import Base
        import app.models.payroll  # noqa: F401 — register tables on Base.metadata

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session() as session:
            yield session
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_editing_a_structure_leaves_the_old_versions_components_intact(self, db_session):
        """
        Regression test: update_salary_structure originally MOVED the
        current components onto the new structure version (repointing
        salary_structure_id). Any EmployeeSalary still assigned to the OLD
        structure id would then find zero components there on its next
        payroll run — silently zeroing that employee's gross salary. Fixed
        to COPY components instead, leaving the old structure's component
        set untouched.
        """
        from app.models.payroll import SalaryStructure, SalaryComponent, ComponentType, ComponentCalculation
        from app.api.v1.hrms.payroll import update_salary_structure, SalaryStructureUpdate

        structure = SalaryStructure(tenant_id=TENANT, name="Standard", code="STD", is_active=True)
        db_session.add(structure)
        await db_session.flush()

        component = SalaryComponent(
            tenant_id=TENANT, salary_structure_id=structure.id, name="Basic", code="BASIC",
            component_type=ComponentType.EARNING, calculation_type=ComponentCalculation.FIXED,
            amount=Decimal("50000"),
        )
        db_session.add(component)
        await db_session.flush()
        old_structure_id = structure.id

        user = SimpleNamespace(id=uuid.uuid4())
        result = await update_salary_structure(
            structure.id, SalaryStructureUpdate(name="Standard v2"), user, TENANT, db_session
        )
        new_structure_id = uuid.UUID(result["id"])
        assert new_structure_id != old_structure_id

        # The OLD structure's original component must still be there,
        # still pointing at the OLD structure id, untouched.
        from sqlalchemy import select
        old_components = (
            await db_session.execute(
                select(SalaryComponent).where(SalaryComponent.salary_structure_id == old_structure_id)
            )
        ).scalars().all()
        assert len(old_components) == 1
        assert old_components[0].id == component.id
        assert old_components[0].is_current is True

        # The NEW structure must have its OWN (copied) component row.
        new_components = (
            await db_session.execute(
                select(SalaryComponent).where(SalaryComponent.salary_structure_id == new_structure_id)
            )
        ).scalars().all()
        assert len(new_components) == 1
        assert new_components[0].id != component.id  # a real copy, not the same row
        assert new_components[0].code == "BASIC"
        assert new_components[0].amount == Decimal("50000")

    @pytest.mark.asyncio
    async def test_editing_a_component_supersedes_the_old_version_without_duplicating_it(self, db_session):
        """
        Regression test: the payroll-run component query originally didn't
        filter by is_current, so after editing a component both the old
        and new version would be pulled in and double-counted. Confirms
        exactly one CURRENT component remains queryable per structure.
        """
        from app.models.payroll import SalaryStructure, SalaryComponent, ComponentType, ComponentCalculation
        from app.api.v1.hrms.payroll import update_salary_component, SalaryComponentUpdate
        from sqlalchemy import select

        structure = SalaryStructure(tenant_id=TENANT, name="Standard", code="STD", is_active=True)
        db_session.add(structure)
        await db_session.flush()
        component = SalaryComponent(
            tenant_id=TENANT, salary_structure_id=structure.id, name="House Allowance", code="HOUSE",
            component_type=ComponentType.EARNING, calculation_type=ComponentCalculation.PERCENTAGE_OF_BASIC,
            percentage=Decimal("20"),
        )
        db_session.add(component)
        await db_session.flush()

        user = SimpleNamespace(id=uuid.uuid4())
        result = await update_salary_component(
            component.id, SalaryComponentUpdate(percentage=Decimal("25")), user, TENANT, db_session
        )
        new_component_id = uuid.UUID(result["id"])

        current_components = (
            await db_session.execute(
                select(SalaryComponent).where(
                    SalaryComponent.salary_structure_id == structure.id,
                    SalaryComponent.is_current == True,  # noqa: E712
                )
            )
        ).scalars().all()

        assert len(current_components) == 1, (
            "Exactly one CURRENT component should exist after an edit — "
            "if this fails, the old and new versions are both being counted "
            "in payroll generation (double-counting bug)."
        )
        assert current_components[0].id == new_component_id
        assert current_components[0].percentage == Decimal("25")
