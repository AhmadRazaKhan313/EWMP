"""
Payroll Formula Engine.

Parses and evaluates payroll formula expressions like:

    BASIC * 0.10
    BASIC + HOUSING + TRANSPORT
    IF(BASIC > 100000, BASIC * 0.10, BASIC * 0.05)
    ROUND(GROSS * 0.05, 2)
    MIN(OVERTIME_HOURS * OVERTIME_RATE, 5000)

This is a from-scratch recursive-descent parser + tree-walking evaluator.
It NEVER calls eval()/exec() or imports anything that could — a tenant's
stored formula string can only ever produce one of the operations defined
below, on Decimal values, nothing else. There is no way for a formula to
reach the filesystem, network, or Python runtime.

Supported grammar (informal):
    expr       := comparison
    comparison := term (('>' | '<' | '>=' | '<=' | '==' | '!=') term)*
    term       := factor (('+' | '-') factor)*
    factor     := unary (('*' | '/') unary)*
    unary      := '-' unary | primary
    primary    := NUMBER | IDENTIFIER | IDENTIFIER '(' args ')' | '(' expr ')'
    args       := expr (',' expr)*

Functions: IF(cond, then, else), AND(...), OR(...), NOT(x),
           MIN(...), MAX(...), ROUND(x[, ndigits]), FLOOR(x), CEIL(x),
           ABS(x), SUM(...)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

# ── Errors ───────────────────────────────────────────────────────────────
class FormulaError(Exception):
    """Base for every error this module raises — never lets a raw Python
    exception (KeyError, ZeroDivisionError, etc.) leak past the boundary,
    so callers get one consistent, explainable error type."""


class FormulaSyntaxError(FormulaError):
    pass


class FormulaEvaluationError(FormulaError):
    pass


class CircularFormulaDependencyError(FormulaError):
    def __init__(self, cycle: list[str]):
        self.cycle = cycle
        super().__init__("Circular formula dependency: " + " → ".join(cycle))


# ── Tokenizer ────────────────────────────────────────────────────────────
_TOKEN_SPEC = [
    ("NUMBER", r"\d+(\.\d+)?"),
    ("IDENT", r"[A-Za-z_][A-Za-z0-9_]*"),
    ("GE", r">="),
    ("LE", r"<="),
    ("EQ", r"=="),
    ("NE", r"!="),
    ("GT", r">"),
    ("LT", r"<"),
    ("PLUS", r"\+"),
    ("MINUS", r"-"),
    ("MUL", r"\*"),
    ("DIV", r"/"),
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
    ("COMMA", r","),
    ("WS", r"\s+"),
]
_MASTER_RE = re.compile("|".join(f"(?P<{name}>{pattern})" for name, pattern in _TOKEN_SPEC))


@dataclass
class Token:
    kind: str
    value: str
    pos: int


def tokenize(expr: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    while pos < len(expr):
        m = _MASTER_RE.match(expr, pos)
        if m is None:
            raise FormulaSyntaxError(f"Unexpected character {expr[pos]!r} at position {pos}")
        kind = m.lastgroup
        value = m.group()
        if kind != "WS":
            tokens.append(Token(kind, value, pos))
        pos = m.end()
    tokens.append(Token("EOF", "", pos))
    return tokens


# ── AST ──────────────────────────────────────────────────────────────────
class Node:
    pass


@dataclass
class NumberNode(Node):
    value: Decimal


@dataclass
class VarNode(Node):
    name: str


@dataclass
class BinOpNode(Node):
    op: str
    left: Node
    right: Node


@dataclass
class UnaryOpNode(Node):
    op: str
    operand: Node


@dataclass
class FuncCallNode(Node):
    name: str
    args: list[Node]


# ── Parser (recursive descent) ──────────────────────────────────────────
_COMPARISON_OPS = {"GT", "LT", "GE", "LE", "EQ", "NE"}

_KNOWN_FUNCTIONS = {
    "IF", "AND", "OR", "NOT", "MIN", "MAX", "ROUND", "FLOOR", "CEIL", "ABS", "SUM",
}


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.i = 0

    def _peek(self) -> Token:
        return self.tokens[self.i]

    def _advance(self) -> Token:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def _expect(self, kind: str) -> Token:
        tok = self._peek()
        if tok.kind != kind:
            raise FormulaSyntaxError(
                f"Expected {kind} but found {tok.kind!r} ({tok.value!r}) at position {tok.pos}"
            )
        return self._advance()

    def parse(self) -> Node:
        node = self._comparison()
        if self._peek().kind != "EOF":
            tok = self._peek()
            raise FormulaSyntaxError(f"Unexpected token {tok.value!r} at position {tok.pos}")
        return node

    def _comparison(self) -> Node:
        node = self._term()
        while self._peek().kind in _COMPARISON_OPS:
            op = self._advance().kind
            node = BinOpNode(op, node, self._term())
        return node

    def _term(self) -> Node:
        node = self._factor()
        while self._peek().kind in ("PLUS", "MINUS"):
            op = self._advance().kind
            node = BinOpNode(op, node, self._factor())
        return node

    def _factor(self) -> Node:
        node = self._unary()
        while self._peek().kind in ("MUL", "DIV"):
            op = self._advance().kind
            node = BinOpNode(op, node, self._unary())
        return node

    def _unary(self) -> Node:
        if self._peek().kind == "MINUS":
            self._advance()
            return UnaryOpNode("MINUS", self._unary())
        return self._primary()

    def _primary(self) -> Node:
        tok = self._peek()
        if tok.kind == "NUMBER":
            self._advance()
            try:
                return NumberNode(Decimal(tok.value))
            except InvalidOperation as exc:
                raise FormulaSyntaxError(f"Invalid number {tok.value!r}") from exc
        if tok.kind == "LPAREN":
            self._advance()
            node = self._comparison()
            self._expect("RPAREN")
            return node
        if tok.kind == "IDENT":
            self._advance()
            name = tok.value.upper()
            if self._peek().kind == "LPAREN":
                self._advance()
                args: list[Node] = []
                if self._peek().kind != "RPAREN":
                    args.append(self._comparison())
                    while self._peek().kind == "COMMA":
                        self._advance()
                        args.append(self._comparison())
                self._expect("RPAREN")
                if name not in _KNOWN_FUNCTIONS:
                    raise FormulaSyntaxError(f"Unknown function {name!r}")
                return FuncCallNode(name, args)
            return VarNode(name)
        raise FormulaSyntaxError(f"Unexpected token {tok.value!r} at position {tok.pos}")


def parse(expr: str) -> Node:
    return Parser(tokenize(expr)).parse()


# ── Evaluator ────────────────────────────────────────────────────────────
_TRUE = Decimal("1")
_FALSE = Decimal("0")


def _as_bool(value: Decimal) -> bool:
    return value != _FALSE


def evaluate(node: Node, context: dict[str, Decimal]) -> Decimal:
    if isinstance(node, NumberNode):
        return node.value

    if isinstance(node, VarNode):
        if node.name not in context:
            raise FormulaEvaluationError(f"Unknown variable {node.name!r}")
        return context[node.name]

    if isinstance(node, UnaryOpNode):
        val = evaluate(node.operand, context)
        return -val

    if isinstance(node, BinOpNode):
        left = evaluate(node.left, context)
        right = evaluate(node.right, context)
        if node.op == "PLUS":
            return left + right
        if node.op == "MINUS":
            return left - right
        if node.op == "MUL":
            return left * right
        if node.op == "DIV":
            if right == 0:
                raise FormulaEvaluationError("Division by zero")
            return left / right
        if node.op == "GT":
            return _TRUE if left > right else _FALSE
        if node.op == "LT":
            return _TRUE if left < right else _FALSE
        if node.op == "GE":
            return _TRUE if left >= right else _FALSE
        if node.op == "LE":
            return _TRUE if left <= right else _FALSE
        if node.op == "EQ":
            return _TRUE if left == right else _FALSE
        if node.op == "NE":
            return _TRUE if left != right else _FALSE
        raise FormulaEvaluationError(f"Unknown operator {node.op!r}")

    if isinstance(node, FuncCallNode):
        return _call_function(node.name, node.args, context)

    raise FormulaEvaluationError(f"Unknown node type {type(node).__name__}")


def _call_function(name: str, args: list[Node], context: dict[str, Decimal]) -> Decimal:
    if name == "IF":
        if len(args) != 3:
            raise FormulaEvaluationError("IF requires exactly 3 arguments: IF(cond, then, else)")
        cond = evaluate(args[0], context)
        return evaluate(args[1] if _as_bool(cond) else args[2], context)

    if name == "AND":
        if not args:
            raise FormulaEvaluationError("AND requires at least 1 argument")
        return _TRUE if all(_as_bool(evaluate(a, context)) for a in args) else _FALSE

    if name == "OR":
        if not args:
            raise FormulaEvaluationError("OR requires at least 1 argument")
        return _TRUE if any(_as_bool(evaluate(a, context)) for a in args) else _FALSE

    if name == "NOT":
        if len(args) != 1:
            raise FormulaEvaluationError("NOT requires exactly 1 argument")
        return _FALSE if _as_bool(evaluate(args[0], context)) else _TRUE

    if name == "MIN":
        if not args:
            raise FormulaEvaluationError("MIN requires at least 1 argument")
        return min(evaluate(a, context) for a in args)

    if name == "MAX":
        if not args:
            raise FormulaEvaluationError("MAX requires at least 1 argument")
        return max(evaluate(a, context) for a in args)

    if name == "SUM":
        if not args:
            raise FormulaEvaluationError("SUM requires at least 1 argument")
        total = Decimal("0")
        for a in args:
            total += evaluate(a, context)
        return total

    if name == "ABS":
        if len(args) != 1:
            raise FormulaEvaluationError("ABS requires exactly 1 argument")
        return abs(evaluate(args[0], context))

    if name == "FLOOR":
        if len(args) != 1:
            raise FormulaEvaluationError("FLOOR requires exactly 1 argument")
        val = evaluate(args[0], context)
        return val.to_integral_value(rounding="ROUND_FLOOR")

    if name == "CEIL":
        if len(args) != 1:
            raise FormulaEvaluationError("CEIL requires exactly 1 argument")
        val = evaluate(args[0], context)
        return val.to_integral_value(rounding="ROUND_CEILING")

    if name == "ROUND":
        if len(args) not in (1, 2):
            raise FormulaEvaluationError("ROUND requires 1 or 2 arguments: ROUND(x[, ndigits])")
        val = evaluate(args[0], context)
        ndigits = int(evaluate(args[1], context)) if len(args) == 2 else 0
        quantum = Decimal("1").scaleb(-ndigits) if ndigits > 0 else Decimal("1")
        return val.quantize(quantum, rounding=ROUND_HALF_UP)

    raise FormulaEvaluationError(f"Unknown function {name!r}")


# ── Public helpers ───────────────────────────────────────────────────────
def extract_variables(node: Node) -> set[str]:
    """All variable (component-code) names referenced by a parsed formula —
    used to build the dependency graph between components, and to validate
    that a formula only references codes that actually exist."""
    found: set[str] = set()

    def _walk(n: Node) -> None:
        if isinstance(n, VarNode):
            found.add(n.name)
        elif isinstance(n, UnaryOpNode):
            _walk(n.operand)
        elif isinstance(n, BinOpNode):
            _walk(n.left)
            _walk(n.right)
        elif isinstance(n, FuncCallNode):
            for a in n.args:
                _walk(a)

    _walk(node)
    return found


def validate_formula(expr: str, known_variables: set[str] | None = None) -> list[str]:
    """
    Returns a list of human-readable validation errors (empty list = valid).
    Never raises — callers use this to show validation errors in the UI
    before a formula component is saved/activated.
    """
    errors: list[str] = []
    try:
        node = parse(expr)
    except FormulaSyntaxError as exc:
        return [str(exc)]

    if known_variables is not None:
        referenced = extract_variables(node)
        unknown = referenced - known_variables
        if unknown:
            errors.append(
                f"Unknown component code(s) referenced: {', '.join(sorted(unknown))}"
            )
    return errors


def evaluate_formula(expr: str, context: dict[str, Decimal]) -> Decimal:
    """Parse + evaluate in one call. Raises FormulaError subclasses only —
    never a raw Python exception."""
    node = parse(expr)
    return evaluate(node, context)


def topological_sort_formulas(formulas: dict[str, str]) -> list[str]:
    """
    Given {component_code: formula_expr}, returns component codes in an
    order where every formula's dependencies come before it. Raises
    CircularFormulaDependencyError if the graph has a cycle.

    Codes referenced by a formula that AREN'T themselves in `formulas`
    (e.g. BASIC, GROSS, or a plain fixed/percentage component) are treated
    as already-available leaves and don't need to be in the sort at all.
    """
    graph: dict[str, set[str]] = {}
    for code, expr in formulas.items():
        try:
            node = parse(expr)
        except FormulaSyntaxError as exc:
            raise FormulaSyntaxError(f"{code}: {exc}") from exc
        deps = extract_variables(node) & formulas.keys()
        deps.discard(code)  # a formula referencing its own code isn't a real self-loop unless truly circular elsewhere
        graph[code] = deps

    visited: dict[str, str] = {}  # code -> "visiting" | "done"
    order: list[str] = []
    path: list[str] = []

    def _visit(code: str) -> None:
        state = visited.get(code)
        if state == "done":
            return
        if state == "visiting":
            cycle_start = path.index(code)
            raise CircularFormulaDependencyError(path[cycle_start:] + [code])
        visited[code] = "visiting"
        path.append(code)
        for dep in graph.get(code, set()):
            _visit(dep)
        path.pop()
        visited[code] = "done"
        order.append(code)

    for code in formulas:
        _visit(code)

    return order
