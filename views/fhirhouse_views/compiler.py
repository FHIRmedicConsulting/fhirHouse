"""ViewDefinition → one DuckDB SELECT (FH-0005 compile execution model).

Collection semantics: every FHIRPath expression lowers to a SQL expression producing
`JSON[]` (a FHIRPath collection). Field navigation auto-flattens intermediate arrays
via the `sof_get` macro (mirrors FHIRPath's collection-flattening), `where()` lowers
to `list_filter` with a lambda, `forEach`/`forEachOrNull` lower to CROSS/LEFT
`JOIN LATERAL unnest(...)`, `unionAll` to a LATERAL union subquery, and `repeat`
(recursive descent) to a bounded unroll (REPEAT_DEPTH levels).

Two render modes:
  - fidelity (default) — every column is the JSON text of its value; the runner
    parses it back, giving exact FHIR JSON typing (what the shared test suite checks).
  - typed — declared column types become native casts (what dbt materializations use).

Anything the compiler cannot lower raises CompileError (fail loud / fall back to the
ADR-0027 interpreter — never guess). The `error()` calls inside the macros enforce
the runtime rules (single-value columns, boolean where) the same way.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .fhirpath import Bin, Const, FhirPathError, Lit, Path, Step, parse

REPEAT_DEPTH = 8  # bounded unroll for `repeat:` recursive traversal

MACROS = [
    # A JSON value as a FHIRPath collection: NULL→[], array→its items, scalar→[it].
    """CREATE OR REPLACE MACRO sof_wrap(j) AS
       CASE WHEN j IS NULL THEN CAST([] AS JSON[])
            WHEN json_type(j) = 'ARRAY' THEN CAST(j AS JSON[])
            ELSE [j] END""",
    # Field navigation with FHIRPath collection flattening.
    """CREATE OR REPLACE MACRO sof_get(coll, key) AS
       flatten(list_transform(coll, jx -> sof_wrap(json_extract(jx, key))))""",
    # Singleton extraction; >1 item is the spec's collection-not-declared error.
    """CREATE OR REPLACE MACRO sof_one(coll) AS
       CASE WHEN coll IS NULL OR len(coll) = 0 THEN NULL
            WHEN len(coll) = 1 THEN coll[1]
            ELSE error('SoF: column value is a collection; declare collection: true') END""",
    "CREATE OR REPLACE MACRO sof_text(coll) AS json_extract_string(sof_one(coll), '$')",
    "CREATE OR REPLACE MACRO sof_bool(coll) AS CAST(sof_text(coll) AS BOOLEAN)",
    "CREATE OR REPLACE MACRO sof_num(coll) AS CAST(sof_text(coll) AS DOUBLE)",
    # `where:` items must evaluate to boolean (spec validation, runtime-enforced).
    """CREATE OR REPLACE MACRO sof_where(coll) AS
       CASE WHEN coll IS NULL OR len(coll) = 0 THEN false
            WHEN json_type(sof_one(coll)) = 'BOOLEAN' THEN sof_bool(coll)
            ELSE error('SoF: where clause must evaluate to boolean') END""",
]

_TYPED_CASTS = {
    "boolean": "CAST(sof_text({c}) AS BOOLEAN)",
    "integer": "CAST(sof_text({c}) AS INTEGER)",
    "unsignedInt": "CAST(sof_text({c}) AS INTEGER)",
    "positiveInt": "CAST(sof_text({c}) AS INTEGER)",
    "integer64": "CAST(sof_text({c}) AS BIGINT)",
    "decimal": "CAST(sof_text({c}) AS DOUBLE)",
    "date": "CAST(sof_text({c}) AS DATE)",
}
_ID64 = "[A-Za-z0-9\\-\\.]{1,64}"
_PIN_CACHE: dict | None = None


class CompileError(Exception):
    pass


@dataclass
class CompiledView:
    sql: str
    columns: list[str]


@dataclass
class _Scope:
    """One relational scope: column exprs + lateral joins accumulated in order."""
    columns: list[tuple[str, str]] = field(default_factory=list)  # (name, JSON[]-expr)
    joins: list[str] = field(default_factory=list)


class ViewCompiler:
    def __init__(self, view: dict, typed: bool = False):
        if not isinstance(view, dict) or not view.get("resource"):
            raise CompileError("ViewDefinition must declare `resource`")
        if not isinstance(view.get("select"), list) or not view["select"]:
            raise CompileError("ViewDefinition must have a non-empty `select`")
        self.view = view
        self.typed = typed
        self.constants = self._constants(view.get("constant", []))
        self._n = 0
        # innermost forEach/repeat iteration ordinal — %rowIndex reads the top
        self._ord_stack: list[str] = []
        # type hints for lowBoundary()/highBoundary(), in priority order: the FHIR
        # model type of the last-navigated top-level field (from the contracts pin),
        # then the last ofType(), then the declared column type
        self._oftype_hint: str | None = None
        self._col_type_hint: str | None = None
        self._last_field: str | None = None

    # ── public ──────────────────────────────────────────────────────────────────

    def compile(self, source_sql: str) -> CompiledView:
        """`source_sql` must yield columns (resource JSON, resource_key VARCHAR)."""
        scope = _Scope()
        self._select_items(self.view["select"], "sof_src.resource", scope)
        if not scope.columns:
            raise CompileError("view selects no columns")
        names = [n for n, _ in scope.columns]
        if len(set(names)) != len(names):
            raise CompileError(f"duplicate column names: {names}")
        rendered = ",\n  ".join(f"{e} AS \"{n}\"" for n, e in scope.columns)
        where = " AND ".join(
            f"sof_where({self._coll(self._parse(w.get('path')), 'sof_src.resource')})"
            for w in self.view.get("where", [])
        )
        sql = (
            f"WITH sof_src AS (\n{source_sql}\n)\n"
            f"SELECT\n  {rendered}\nFROM sof_src"
            + "".join("\n" + j for j in scope.joins)
            + (f"\nWHERE {where}" if where else "")
        )
        return CompiledView(sql=sql, columns=names)

    # ── select structure ────────────────────────────────────────────────────────

    def _select_items(self, items: list, ctx: str, scope: _Scope) -> None:
        for item in items:
            if not isinstance(item, dict):
                raise CompileError(f"select item must be an object, got {item!r}")
            item_ctx = ctx
            pushed = 0
            fe = item.get("forEach") or item.get("forEachOrNull")
            if "forEach" in item and "forEachOrNull" in item:
                raise CompileError("select item has both forEach and forEachOrNull")
            if fe is not None:
                coll = self._coll(self._parse(fe), ctx)
                alias = self._alias("fe")
                join_kind = "CROSS JOIN" if "forEach" in item else "LEFT JOIN"
                on = "" if join_kind == "CROSS JOIN" else " ON TRUE"
                # zip-unnest of the collection with its ordinals (%rowIndex support)
                scope.joins.append(
                    f"{join_kind} LATERAL (SELECT unnest({coll}) AS v, "
                    f"unnest(range(len({coll}))) AS ord) AS {alias}{on}")
                item_ctx = f"{alias}.v"
                self._ord_stack.append(f"{alias}.ord")
                pushed += 1
            if "repeat" in item:
                alias = self._repeat_joins(item["repeat"], item_ctx, scope)
                item_ctx = f"{alias}.v"
                self._ord_stack.append(f"{alias}.ord")
                pushed += 1

            for col in item.get("column", []):
                name, path = col.get("name"), col.get("path")
                if not name or not isinstance(path, str):
                    raise CompileError(f"column needs name and string path: {col!r}")
                self._oftype_hint, self._col_type_hint, self._last_field = None, col.get("type"), None
                expr = self._coll(self._parse(path), item_ctx)
                scope.columns.append((name, self._column_expr(expr, col)))

            if item.get("select"):
                self._select_items(item["select"], item_ctx, scope)

            if item.get("unionAll"):
                self._union_all(item["unionAll"], item_ctx, scope)

            if not any(k in item for k in ("column", "select", "unionAll", "forEach",
                                           "forEachOrNull", "repeat")):
                raise CompileError(f"empty select item: {item!r}")
            for _ in range(pushed):
                self._ord_stack.pop()

    def _union_all(self, branches: list, ctx: str, scope: _Scope) -> None:
        compiled = []
        names: list[str] | None = None
        for b in branches:
            s = _Scope()
            self._select_items([b], ctx, s)
            b_names = [n for n, _ in s.columns]
            if names is None:
                names = b_names
            elif b_names != names:
                raise CompileError(f"unionAll branch columns differ: {names} vs {b_names}")
            sel = ", ".join(f"{e} AS \"{n}\"" for n, e in s.columns)
            compiled.append(f"SELECT {sel} FROM (SELECT 1)" + "".join(" " + j for j in s.joins))
        if not compiled or names is None:
            raise CompileError("unionAll must have at least one branch with columns")
        alias = self._alias("u")
        scope.joins.append(
            "CROSS JOIN LATERAL (\n  " + "\n  UNION ALL\n  ".join(compiled) + f"\n) AS {alias}")
        scope.columns.extend((n, f"{alias}.\"{n}\"") for n in names)

    def _repeat_joins(self, paths: list, ctx: str, scope: _Scope) -> str:
        """`repeat:` (recursive descent) as a bounded unroll of chained single-row
        laterals — level k+1 derives from level k's alias, so SQL size stays LINEAR
        in REPEAT_DEPTH. Deeper structures need the interpreter fallback."""
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise CompileError(f"repeat must be a list of path strings: {paths!r}")
        seg_lists = [self._field_segments(p) for p in paths]

        def children(src: str) -> str:  # children of one node, in repeat-path order
            parts = []
            for segs in seg_lists:
                expr = f"sof_wrap({src})"
                for seg in segs:
                    expr = f"sof_get({expr}, '$.\"{seg}\"')"
                parts.append(expr)
            return " || ".join(parts) if len(parts) > 1 else parts[0]

        # Each level carries structs {k: ancestor-ordinal chain, n: node}; sorting the
        # flattened union by k yields DEPTH-FIRST document order (%rowIndex semantics).
        base = self._alias("rp")
        levels = []
        scope.joins.append(
            f"CROSS JOIN LATERAL (SELECT list_transform({children(ctx)}, "
            f"(x, i) -> {{'k': [i], 'n': x}}) AS s) AS {base}_l1")
        levels.append(f"{base}_l1.s")
        for i in range(2, REPEAT_DEPTH + 1):
            prev = f"{base}_l{i - 1}.s"
            scope.joins.append(
                f"CROSS JOIN LATERAL (SELECT flatten(list_transform({prev}, "
                f"p -> list_transform({children('p.n')}, "
                f"(x, i) -> {{'k': p.k || [i], 'n': x}}))) AS s) AS {base}_l{i}")
            levels.append(f"{base}_l{i}.s")
        scope.joins.append(
            f"CROSS JOIN LATERAL (SELECT list_transform(list_sort("
            f"flatten([{', '.join(levels)}])), e -> e.n) AS nodes) AS {base}_all")
        scope.joins.append(
            f"CROSS JOIN LATERAL (SELECT unnest({base}_all.nodes) AS v, "
            f"unnest(range(len({base}_all.nodes))) AS ord) AS {base}")
        return base

    def _field_segments(self, path: str) -> list[str]:
        node = self._parse(path)
        if not (isinstance(node, Path) and node.base is None
                and all(s.kind == "field" for s in node.steps)):
            raise CompileError(f"repeat path must be a simple field path: {path!r}")
        return [s.name for s in node.steps]

    # ── expression lowering (everything returns a JSON[]-producing SQL string) ──

    def _parse(self, src):
        try:
            return parse(src)
        except FhirPathError as e:
            raise CompileError(str(e)) from e

    def _coll(self, node, ctx: str) -> str:
        if isinstance(node, Lit):
            return f"sof_wrap(to_json({self._lit(node.value)}))"
        if isinstance(node, Const):
            if node.name == "rowIndex":
                # iteration index within the nearest forEach/repeat scope; 0 at root
                # and 0 on an empty forEachOrNull row (the row still has index 0)
                ord_expr = self._ord_stack[-1] if self._ord_stack else "0"
                return f"sof_wrap(to_json(CAST(coalesce({ord_expr}, 0) AS INTEGER)))"
            return self._coll(Lit(self._const(node.name)), ctx)
        if isinstance(node, Bin):
            return self._bin(node, ctx)
        if isinstance(node, Path):
            base = f"sof_wrap(to_json({ctx}))" if node.base is None else self._coll(node.base, ctx)
            # `to_json` of a JSON value is identity-ish; ctx is already JSON — wrap directly
            if node.base is None:
                base = f"sof_wrap({ctx})"
            return self._steps(base, node.steps, ctx)
        raise CompileError(f"cannot lower node {node!r}")

    def _bin(self, node: Bin, ctx: str) -> str:
        lc, rc = self._coll(node.left, ctx), self._coll(node.right, ctx)
        op = node.op
        if op in ("and", "or"):
            return f"sof_wrap(to_json(sof_bool({lc}) {op.upper()} sof_bool({rc})))"
        if op in ("+", "-", "*", "/"):
            return f"sof_wrap(to_json(sof_num({lc}) {op} sof_num({rc})))"
        numeric = self._is_numeric(node.left) or self._is_numeric(node.right)
        l_expr = f"sof_num({lc})" if numeric else f"sof_text({lc})"
        r_expr = f"sof_num({rc})" if numeric else f"sof_text({rc})"
        sql_op = {"=": "=", "!=": "<>", "<": "<", ">": ">", "<=": "<=", ">=": ">="}[op]
        return f"sof_wrap(to_json({l_expr} {sql_op} {r_expr}))"

    def _is_numeric(self, node) -> bool:
        if isinstance(node, Lit):
            return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
        if isinstance(node, Const):
            v = self._const(node.name)
            return isinstance(v, (int, float)) and not isinstance(v, bool)
        if isinstance(node, Bin):
            return node.op in ("+", "-", "*", "/")
        return False

    def _steps(self, coll: str, steps: list[Step], root_ctx: str) -> str:
        pending: str | None = None  # staged field name — ofType() rewrites it to the choice key

        def flush():
            nonlocal coll, pending
            if pending is not None:
                coll = f"sof_get({coll}, '$.\"{pending}\"')"
                self._last_field = pending
                pending = None

        for s in steps:
            if s.kind == "field":
                flush()
                if s.name != "$this":  # $this = identity
                    pending = s.name
            elif s.kind == "index":
                flush()
                idx = self._index_value(s.args[0])
                coll = f"{coll}[{idx + 1}:{idx + 1}]"
            elif s.kind == "call" and s.name == "ofType":
                if pending is None:
                    raise CompileError("ofType() must directly follow a choice-element field")
                t = self._type_arg(s)
                self._oftype_hint = t[0].lower() + t[1:]  # boundary-function type hint
                pending = pending + t  # value + Quantity → valueQuantity
                flush()
            else:
                flush()
                coll = self._call(s, coll, root_ctx)
        flush()
        return coll

    def _type_arg(self, s: Step) -> str:
        if not (s.args and isinstance(s.args[0], Path) and s.args[0].base is None
                and len(s.args[0].steps) == 1 and s.args[0].steps[0].kind == "field"):
            raise CompileError(f"{s.name}() requires a bare type name argument")
        t = s.args[0].steps[0].name
        return t[0].upper() + t[1:]

    def _call(self, s: Step, coll: str, root_ctx: str) -> str:
        name = s.name
        if name == "where":
            if len(s.args) != 1:
                raise CompileError("where() takes exactly one criteria expression")
            var = self._alias("w")
            cond = self._coll(s.args[0], var)
            return f"list_filter({coll}, {var} -> sof_where({cond}))"
        if name == "extension":
            if len(s.args) != 1 or not isinstance(s.args[0], (Lit, Const)):
                raise CompileError("extension() takes one url literal/constant")
            url = s.args[0].value if isinstance(s.args[0], Lit) else self._const(s.args[0].name)
            var = self._alias("e")
            return (f"list_filter(sof_get({coll}, '$.\"extension\"'), "
                    f"{var} -> json_extract_string({var}, '$.url') = {self._lit(url)})")
        if name == "first":
            return f"{coll}[1:1]"
        if name == "exists":
            if s.args:  # exists(criteria) == where(criteria).exists()
                var = self._alias("x")
                cond = self._coll(s.args[0], var)
                coll = f"list_filter({coll}, {var} -> sof_where({cond}))"
            return f"sof_wrap(to_json(len({coll}) > 0))"
        if name == "empty":
            return f"sof_wrap(to_json(len({coll}) = 0))"
        if name == "not":
            return f"sof_wrap(to_json(NOT sof_bool({coll})))"
        if name == "join":
            sep = ""
            if s.args:
                if not isinstance(s.args[0], Lit) or not isinstance(s.args[0].value, str):
                    raise CompileError("join() separator must be a string literal")
                sep = s.args[0].value
            var = self._alias("j")
            joined = (f"array_to_string(list_transform({coll}, "
                      f"{var} -> json_extract_string({var}, '$')), {self._lit(sep)})")
            # {}.join(...) is {} (empty collection), not '' — FHIRPath empty propagation
            return (f"(CASE WHEN len({coll}) = 0 THEN CAST([] AS JSON[]) "
                    f"ELSE sof_wrap(to_json({joined})) END)")
        if name == "getResourceKey":
            return "sof_wrap(to_json(sof_src.resource_key))"
        if name == "getReferenceKey":
            type_filter = None
            if s.args:
                a = s.args[0]
                if not (isinstance(a, Path) and a.base is None and len(a.steps) == 1
                        and a.steps[0].kind == "field"):
                    raise CompileError("getReferenceKey() argument must be a resource type name")
                type_filter = a.steps[0].name
            pat = (f"(?:^|/){type_filter}/({_ID64})$" if type_filter
                   else f"(?:^|/)[A-Za-z]+/({_ID64})$")
            v, y = self._alias("r"), self._alias("y")
            return (f"list_filter(list_transform({coll}, {v} -> "
                    f"to_json(nullif(regexp_extract(json_extract_string({v}, '$.reference'), "
                    f"'{pat}', 1), ''))), {y} -> {y} IS NOT NULL)")
        if name in ("lowBoundary", "highBoundary"):
            return self._boundary(coll, low=(name == "lowBoundary"))
        raise CompileError(f"unsupported FHIRPath function: {name}()")

    def _boundary(self, coll: str, low: bool) -> str:
        """lowBoundary()/highBoundary() — earliest/latest value consistent with the
        operand's precision. Dispatch needs the FHIR type (JSON can't distinguish a
        date from a dateTime string): last ofType() wins, else the column's type."""
        kinds = {"decimal": "decimal", "integer": "decimal", "date": "date",
                 "dateTime": "dateTime", "instant": "dateTime", "time": "time"}
        hints = [self._model_type(), self._oftype_hint, self._col_type_hint]
        kind = next((kinds[h] for h in hints if h in kinds), None)
        if kind is None:
            raise CompileError(
                f"lowBoundary()/highBoundary() needs a decimal/date/dateTime/time type "
                f"hint (model/ofType/column type); got {hints!r}")
        var = self._alias("b")
        s = f"json_extract_string({var}, '$')"
        if kind == "decimal":
            digits = f"(CASE WHEN strpos({s}, '.') > 0 THEN len({s}) - strpos({s}, '.') ELSE 0 END)"
            delta = f"(0.5 * power(10, -{digits}))"
            op = "-" if low else "+"
            scalar = f"round(CAST({s} AS DOUBLE) {op} {delta}, CAST({digits} + 1 AS INTEGER))"
        elif kind == "date":
            scalar = (f"CASE len({s}) WHEN 4 THEN {s} || '-01-01' "
                      f"WHEN 7 THEN {s} || '-01' ELSE {s} END" if low else
                      f"CASE len({s}) WHEN 4 THEN {s} || '-12-31' "
                      f"WHEN 7 THEN strftime(last_day(CAST({s} || '-01' AS DATE)), '%Y-%m-%d') "
                      f"ELSE {s} END")
        elif kind == "dateTime":
            # partial dateTimes bound at the timezone extremes (+14:00 / -12:00)
            if low:
                scalar = (f"CASE len({s}) WHEN 4 THEN {s} || '-01-01T00:00:00.000+14:00' "
                          f"WHEN 7 THEN {s} || '-01T00:00:00.000+14:00' "
                          f"WHEN 10 THEN {s} || 'T00:00:00.000+14:00' ELSE {s} END")
            else:
                scalar = (f"CASE len({s}) WHEN 4 THEN {s} || '-12-31T23:59:59.999-12:00' "
                          f"WHEN 7 THEN strftime(last_day(CAST({s} || '-01' AS DATE)), '%Y-%m-%d')"
                          f" || 'T23:59:59.999-12:00' "
                          f"WHEN 10 THEN {s} || 'T23:59:59.999-12:00' ELSE {s} END")
        else:  # time
            suffix = "':00.000'" if low else "':00.999'"
            frac = "'.000'" if low else "'.999'"
            scalar = (f"CASE len({s}) WHEN 5 THEN {s} || {suffix} "
                      f"WHEN 8 THEN {s} || {frac} ELSE {s} END")
        return f"list_transform({coll}, {var} -> to_json({scalar}))"

    def _model_type(self) -> str | None:
        """FHIR model type of the last-navigated field when it is a top-level element
        of the view's resource — resolved from the contracts pin (the same flattener
        schema the FH-0005 fast path uses). JSON alone can't tell date from dateTime."""
        if not self._last_field:
            return None
        try:
            from fhirhouse_contracts.schema import load_pin

            global _PIN_CACHE
            if _PIN_CACHE is None:
                _PIN_CACHE = load_pin()
            cols = _PIN_CACHE["top_level_columns"].get(self.view["resource"], [])
            return next((c["fhirType"] for c in cols if c["name"] == self._last_field), None)
        except Exception:
            return None  # pin unavailable → fall through to ofType/column hints

    def _index_value(self, node) -> int:
        if isinstance(node, Const):
            node = Lit(self._const(node.name))
        if isinstance(node, Lit) and isinstance(node.value, int):
            return node.value
        raise CompileError(f"indexer must be an integer literal/constant: {node!r}")

    # ── rendering / helpers ─────────────────────────────────────────────────────

    def _column_expr(self, coll: str, col: dict) -> str:
        if col.get("collection") is True:
            return f"CAST(to_json({coll}) AS VARCHAR)"
        if self.typed:
            t = col.get("type")
            if t in _TYPED_CASTS:
                return _TYPED_CASTS[t].format(c=coll)
            if t and t[0].islower():  # primitive string-ish (string, code, uri, dateTime…)
                return f"sof_text({coll})"
            return f"CAST(sof_one({coll}) AS VARCHAR)"  # complex/no type → JSON text
        return f"CAST(sof_one({coll}) AS VARCHAR)"  # fidelity mode: JSON text always

    def _constants(self, constants: list) -> dict:
        out = {}
        for c in constants:
            vals = [v for k, v in c.items() if k.startswith("value")]
            if not c.get("name") or len(vals) != 1:
                raise CompileError(f"constant needs name and exactly one value[x]: {c!r}")
            out[c["name"]] = vals[0]
        return out

    def _const(self, name: str):
        if name not in self.constants:
            raise CompileError(f"undefined constant %{name}")
        return self.constants[name]

    def _lit(self, v) -> str:
        if isinstance(v, bool):
            return "TRUE" if v else "FALSE"
        if isinstance(v, (int, float)):
            return repr(v)
        return "'" + str(v).replace("'", "''") + "'"

    def _alias(self, prefix: str) -> str:
        self._n += 1
        return f"sof_{prefix}{self._n}"


def compile_view(view: dict, source_sql: str, typed: bool = False) -> CompiledView:
    return ViewCompiler(view, typed=typed).compile(source_sql)
