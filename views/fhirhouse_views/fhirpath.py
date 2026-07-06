"""Restricted FHIRPath parser — the subset SQL-on-FHIR ViewDefinitions actually use.

Grammar (precedence low→high): `or` → `and` → equality (= !=) → relational
(< > <= >=) → additive (+ -) → multiplicative (* /) → postfix path → primary.
Paths are chains of fields, indexers, and function calls, optionally rooted at a
parenthesized expression (e.g. `(gender = 'male').not()`).

Anything outside the subset raises FhirPathError — the compiler surfaces that as
CompileError (fail loud), which is also exactly what the shared suite's
`expectError` validation tests demand.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


class FhirPathError(ValueError):
    pass


@dataclass
class Lit:
    value: object  # str | int | float | bool


@dataclass
class Const:
    name: str


@dataclass
class Bin:
    op: str
    left: object
    right: object


@dataclass
class Step:
    kind: str          # "field" | "call" | "index"
    name: str = ""     # field/function name
    args: tuple = ()   # call args (AST nodes) or (index-expr,) for kind="index"


@dataclass
class Path:
    base: object       # None (context root) or an AST node (parenthesized base)
    steps: list


_TOKEN = re.compile(
    r"\s*(?:(?P<string>'(?:[^'\\]|\\.)*')"
    r"|(?P<number>\d+(?:\.\d+)?)"
    r"|(?P<const>%[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<ident>\$this|[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<op><=|>=|!=|[=<>+\-*/().,\[\]])"
    r")"
)


def _tokenize(src: str) -> list[tuple[str, str]]:
    out, pos = [], 0
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m or m.end() == pos:
            raise FhirPathError(f"unexpected character at {pos}: {src[pos:pos + 10]!r}")
        pos = m.end()
        for kind in ("string", "number", "const", "ident", "op"):
            if m.group(kind) is not None:
                out.append((kind, m.group(kind)))
                break
    return out


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]):
        self.toks = tokens
        self.i = 0

    def peek(self) -> tuple[str, str] | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self, kind: str | None = None, value: str | None = None):
        t = self.peek()
        if t is None or (kind and t[0] != kind) or (value and t[1] != value):
            raise FhirPathError(f"expected {value or kind}, got {t}")
        self.i += 1
        return t

    # precedence-climbing
    def expression(self):
        return self._or()

    def _or(self):
        node = self._and()
        while (t := self.peek()) and t == ("ident", "or"):
            self.take()
            node = Bin("or", node, self._and())
        return node

    def _and(self):
        node = self._eq()
        while (t := self.peek()) and t == ("ident", "and"):
            self.take()
            node = Bin("and", node, self._eq())
        return node

    def _eq(self):
        node = self._rel()
        while (t := self.peek()) and t[0] == "op" and t[1] in ("=", "!="):
            op = self.take()[1]
            node = Bin(op, node, self._rel())
        return node

    def _rel(self):
        node = self._add()
        while (t := self.peek()) and t[0] == "op" and t[1] in ("<", ">", "<=", ">="):
            op = self.take()[1]
            node = Bin(op, node, self._add())
        return node

    def _add(self):
        node = self._mul()
        while (t := self.peek()) and t[0] == "op" and t[1] in ("+", "-"):
            op = self.take()[1]
            node = Bin(op, node, self._mul())
        return node

    def _mul(self):
        node = self._postfix()
        while (t := self.peek()) and t[0] == "op" and t[1] in ("*", "/"):
            op = self.take()[1]
            node = Bin(op, node, self._postfix())
        return node

    def _postfix(self):
        node = self._primary()
        steps: list[Step] = []
        while (t := self.peek()) is not None:
            if t == ("op", "."):
                self.take()
                steps.append(self._step())
            elif t == ("op", "["):
                self.take()
                idx = self.expression()
                self.take("op", "]")
                steps.append(Step("index", args=(idx,)))
            else:
                break
        if isinstance(node, Path):
            node.steps.extend(steps)
            return node
        return Path(base=node, steps=steps) if steps else node

    def _step(self) -> Step:
        name = self.take("ident")[1]
        if (t := self.peek()) and t == ("op", "("):
            return Step("call", name, tuple(self._args()))
        return Step("field", name)

    def _args(self) -> list:
        self.take("op", "(")
        args = []
        if self.peek() != ("op", ")"):
            args.append(self.expression())
            while self.peek() == ("op", ","):
                self.take()
                args.append(self.expression())
        self.take("op", ")")
        return args

    def _primary(self):
        t = self.peek()
        if t is None:
            raise FhirPathError("unexpected end of expression")
        kind, val = t
        if kind == "string":
            self.take()
            return Lit(val[1:-1].replace("\\'", "'"))
        if kind == "number":
            self.take()
            return Lit(float(val) if "." in val else int(val))
        if kind == "const":
            self.take()
            return Const(val[1:])
        if kind == "op" and val == "(":
            self.take()
            node = self.expression()
            self.take("op", ")")
            return node
        if kind == "ident":
            if val in ("true", "false"):
                self.take()
                return Lit(val == "true")
            step = self._step_after_ident()
            return Path(base=None, steps=[step])
        raise FhirPathError(f"unexpected token {t}")

    def _step_after_ident(self) -> Step:
        return self._step()


def parse(src: str):
    if not isinstance(src, str) or not src.strip():
        raise FhirPathError(f"FHIRPath must be a non-empty string, got {src!r}")
    p = _Parser(_tokenize(src))
    node = p.expression()
    if p.peek() is not None:
        raise FhirPathError(f"trailing tokens after expression: {p.toks[p.i:]}")
    return node
