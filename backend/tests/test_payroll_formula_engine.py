"""
Tests for the payroll formula engine (app/services/payroll_formula.py).

Run:  cd backend && pytest tests/test_payroll_formula_engine.py -v
"""
from decimal import Decimal

import pytest

from app.services.payroll_formula import (
    FormulaSyntaxError,
    FormulaEvaluationError,
    CircularFormulaDependencyError,
    evaluate_formula,
    validate_formula,
    topological_sort_formulas,
    extract_variables,
    parse,
)


class TestArithmetic:
    def test_multiplication(self):
        assert evaluate_formula("BASIC * 0.10", {"BASIC": Decimal("100000")}) == Decimal("10000.00")

    def test_addition_of_multiple_variables(self):
        ctx = {"BASIC": Decimal("100000"), "HOUSING": Decimal("20000"), "TRANSPORT": Decimal("10000")}
        assert evaluate_formula("BASIC + HOUSING + TRANSPORT", ctx) == Decimal("130000")

    def test_subtraction(self):
        assert evaluate_formula("BASIC - 5000", {"BASIC": Decimal("100000")}) == Decimal("95000")

    def test_division(self):
        assert evaluate_formula("BASIC / 2", {"BASIC": Decimal("100000")}) == Decimal("50000")

    def test_division_by_zero_raises_formula_error_not_python_exception(self):
        with pytest.raises(FormulaEvaluationError):
            evaluate_formula("BASIC / 0", {"BASIC": Decimal("100000")})

    def test_operator_precedence(self):
        # 2 + 3 * 4 = 14, not 20
        assert evaluate_formula("2 + 3 * 4", {}) == Decimal("14")

    def test_parentheses_override_precedence(self):
        assert evaluate_formula("(2 + 3) * 4", {}) == Decimal("20")

    def test_unary_minus(self):
        assert evaluate_formula("-BASIC", {"BASIC": Decimal("100")}) == Decimal("-100")

    def test_case_insensitive_variable_names(self):
        # tokenizer upper-cases identifiers, so "basic" and "BASIC" are the same variable
        assert evaluate_formula("basic * 2", {"BASIC": Decimal("100")}) == Decimal("200")


class TestComparisons:
    @pytest.mark.parametrize("expr,expected", [
        ("100 > 50", "1"), ("50 > 100", "0"),
        ("100 < 50", "0"), ("50 < 100", "1"),
        ("100 >= 100", "1"), ("100 <= 100", "1"),
        ("100 == 100", "1"), ("100 != 100", "0"),
    ])
    def test_comparison_operators(self, expr, expected):
        assert evaluate_formula(expr, {}) == Decimal(expected)


class TestFunctions:
    def test_if_true_branch(self):
        assert evaluate_formula(
            "IF(BASIC > 100000, BASIC * 0.10, BASIC * 0.05)", {"BASIC": Decimal("150000")}
        ) == Decimal("15000.00")

    def test_if_false_branch(self):
        assert evaluate_formula(
            "IF(BASIC > 100000, BASIC * 0.10, BASIC * 0.05)", {"BASIC": Decimal("50000")}
        ) == Decimal("2500.00")

    def test_if_wrong_arg_count_raises(self):
        with pytest.raises(FormulaEvaluationError):
            evaluate_formula("IF(1, 2)", {})

    def test_and_or_not(self):
        assert evaluate_formula("AND(1, 1)", {}) == Decimal("1")
        assert evaluate_formula("AND(1, 0)", {}) == Decimal("0")
        assert evaluate_formula("OR(0, 1)", {}) == Decimal("1")
        assert evaluate_formula("OR(0, 0)", {}) == Decimal("0")
        assert evaluate_formula("NOT(0)", {}) == Decimal("1")

    def test_min_max(self):
        assert evaluate_formula("MIN(5, 3, 8)", {}) == Decimal("3")
        assert evaluate_formula("MAX(5, 3, 8)", {}) == Decimal("8")

    def test_min_caps_overtime_pay(self):
        assert evaluate_formula(
            "MIN(OVERTIME_HOURS * 500, 5000)", {"OVERTIME_HOURS": Decimal("20")}
        ) == Decimal("5000")
        assert evaluate_formula(
            "MIN(OVERTIME_HOURS * 500, 5000)", {"OVERTIME_HOURS": Decimal("5")}
        ) == Decimal("2500")

    def test_sum(self):
        assert evaluate_formula("SUM(1, 2, 3, 4)", {}) == Decimal("10")

    def test_abs(self):
        assert evaluate_formula("ABS(-500)", {}) == Decimal("500")

    def test_floor_and_ceil(self):
        assert evaluate_formula("FLOOR(7.8)", {}) == Decimal("7")
        assert evaluate_formula("CEIL(7.2)", {}) == Decimal("8")

    def test_round_default_zero_digits(self):
        assert evaluate_formula("ROUND(7.5)", {}) == Decimal("8")

    def test_round_with_ndigits(self):
        assert evaluate_formula("ROUND(GROSS * 0.05, 2)", {"GROSS": Decimal("123456.789")}) == Decimal("6172.84")

    def test_unknown_function_is_a_syntax_error(self):
        with pytest.raises(FormulaSyntaxError):
            parse("EXEC(BASIC)")


class TestSecurity:
    """The formula engine must NEVER be able to do anything beyond the
    arithmetic/functions defined above — no attribute access, no
    dunder-method reaching for __import__, no way to touch the filesystem,
    network, or Python runtime via a stored formula string."""

    @pytest.mark.parametrize("malicious_expr", [
        "__import__('os').system('rm -rf /')",
        "eval('1+1')",
        "exec('import os')",
        "().__class__.__bases__[0]",
        "open('/etc/passwd').read()",
        "BASIC.__class__",
    ])
    def test_cannot_execute_arbitrary_python(self, malicious_expr):
        # Every one of these must fail to PARSE or EVALUATE cleanly as a
        # FormulaError — never silently succeed, and never raise some other
        # raw Python exception that might indicate the string reached
        # actual Python evaluation machinery.
        with pytest.raises((FormulaSyntaxError, FormulaEvaluationError)):
            evaluate_formula(malicious_expr, {"BASIC": Decimal("100")})


class TestValidation:
    def test_valid_formula_returns_no_errors(self):
        assert validate_formula("BASIC * 0.10", {"BASIC"}) == []

    def test_syntax_error_is_reported(self):
        errors = validate_formula("BASIC * ", {"BASIC"})
        assert len(errors) == 1

    def test_unknown_variable_is_reported(self):
        errors = validate_formula("BASIC + UNKNOWN_CODE", {"BASIC"})
        assert any("UNKNOWN_CODE" in e for e in errors)

    def test_skips_variable_check_when_known_variables_not_given(self):
        assert validate_formula("BASIC + ANYTHING") == []


class TestExtractVariables:
    def test_extracts_plain_variables(self):
        assert extract_variables(parse("BASIC + HOUSING")) == {"BASIC", "HOUSING"}

    def test_extracts_variables_inside_function_calls(self):
        assert extract_variables(parse("IF(BASIC > 100, HOUSING, TRANSPORT)")) == {
            "BASIC", "HOUSING", "TRANSPORT",
        }

    def test_function_names_are_not_treated_as_variables(self):
        assert "ROUND" not in extract_variables(parse("ROUND(BASIC, 2)"))


class TestTopologicalSort:
    def test_simple_dependency_chain(self):
        order = topological_sort_formulas({"GROSS": "BASIC + HOUSE", "HOUSE": "BASIC * 0.2"})
        assert order.index("HOUSE") < order.index("GROSS")

    def test_independent_formulas_both_included(self):
        order = topological_sort_formulas({"A": "BASIC * 0.1", "B": "BASIC * 0.2"})
        assert set(order) == {"A", "B"}

    def test_detects_direct_two_node_cycle(self):
        with pytest.raises(CircularFormulaDependencyError):
            topological_sort_formulas({"A": "B + 1", "B": "A + 1"})

    def test_detects_longer_cycle(self):
        with pytest.raises(CircularFormulaDependencyError):
            topological_sort_formulas({"A": "B + 1", "B": "C + 1", "C": "A + 1"})

    def test_diamond_dependency_is_not_a_false_positive_cycle(self):
        # GROSS depends on both HOUSE and TRANSPORT, which both depend on
        # BASIC (not in the formula set) — this is valid, not circular.
        order = topological_sort_formulas({
            "GROSS": "HOUSE + TRANSPORT",
            "HOUSE": "BASIC * 0.2",
            "TRANSPORT": "BASIC * 0.1",
        })
        assert order.index("HOUSE") < order.index("GROSS")
        assert order.index("TRANSPORT") < order.index("GROSS")

    def test_bad_formula_syntax_reports_which_component_code(self):
        with pytest.raises(FormulaSyntaxError, match="BADCOMP"):
            topological_sort_formulas({"BADCOMP": "BASIC * "})
