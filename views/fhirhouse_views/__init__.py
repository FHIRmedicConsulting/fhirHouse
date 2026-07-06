"""fhirhouse_views — SQL-on-FHIR v2 ViewDefinition → DuckDB compiler (FH-0005).

Execution model: compile each ViewDefinition to ONE native DuckDB SELECT over Delta
(set-based; the engine's optimizer, parallelism, and pushdown do the work) instead of
interpreting FHIRPath per resource. Expressions the compiler cannot lower raise
CompileError — fail loud or fall back, never guess (research note §6).

Correctness bar: the official SQL-on-FHIR shared JSON test suite, vendored under
views/conformance/suite/ and run by conformance.py (report in views/conformance/).
"""
from .compiler import CompileError, CompiledView, ViewCompiler
from .runner import connect, run_view

__all__ = ["CompileError", "CompiledView", "ViewCompiler", "connect", "run_view"]
