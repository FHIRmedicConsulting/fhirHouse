"""L5 IG/profile conformance via the external HL7 Java validator (validator_cli.jar).

fhirEngine's own chain covers L1–L4; the validator closes the L5 gap it names
(closed/max slices, discriminators, must-support — fhirEngine ADR-0015). The jar is
operator-supplied (JVM dependency): set FHIRHOUSE_VALIDATOR_JAR, or pass `jar=`.
Download: https://github.com/hapifhir/org.hl7.fhir.core/releases (validator_cli.jar).

Emits standard MetricResults so L5 rides the same gold/dq_score table as the Kahn
dimensions (dimension="conformance", metric="l5_ig_conformance").
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile

from .kahn import MetricResult


class ValidatorUnavailable(RuntimeError):
    pass


def _jar_path(jar: str | None) -> str:
    jar = jar or os.environ.get("FHIRHOUSE_VALIDATOR_JAR", "")
    if not jar or not pathlib.Path(jar).exists():
        raise ValidatorUnavailable(
            "HL7 validator_cli.jar not found — set FHIRHOUSE_VALIDATOR_JAR "
            "(https://github.com/hapifhir/org.hl7.fhir.core/releases)")
    return jar


def validate_resources(
    resources: list[dict],
    jar: str | None = None,
    igs: list[str] | None = None,
    profiles: list[str] | None = None,
    fhir_version: str = "4.0.1",
    java: str = "java",
    timeout: int = 900,
) -> list[dict]:
    """Run validator_cli over the resources; return one OperationOutcome dict per input
    (order preserved). `igs` are `-ig` package ids (e.g. hl7.fhir.us.core#6.1.0)."""
    jar = _jar_path(jar)
    with tempfile.TemporaryDirectory(prefix="fhirhouse-l5-") as td:
        paths = []
        for i, r in enumerate(resources):
            p = pathlib.Path(td) / f"r{i:06d}.json"
            p.write_text(json.dumps(r))
            paths.append(str(p))
        out_bundle = pathlib.Path(td) / "outcome.json"
        cmd = [java, "-jar", jar, *paths, "-version", fhir_version, "-output", str(out_bundle)]
        for ig in igs or []:
            cmd += ["-ig", ig]
        for prof in profiles or []:
            cmd += ["-profile", prof]
        # validator exits non-zero when resources are invalid — that's a result, not a failure.
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if not out_bundle.exists():
            raise ValidatorUnavailable(
                f"validator produced no output (exit {proc.returncode}): {proc.stderr[-500:]}")
        doc = json.loads(out_bundle.read_text())
    # Single input → bare OperationOutcome; multiple → Bundle of them.
    if doc.get("resourceType") == "OperationOutcome":
        return [doc]
    return [e["resource"] for e in doc.get("entry", []) if e.get("resource", {}).get("resourceType") == "OperationOutcome"]


def issue_counts(outcome: dict) -> dict[str, int]:
    counts = {"fatal": 0, "error": 0, "warning": 0, "information": 0}
    for issue in outcome.get("issue", []):
        sev = issue.get("severity", "information")
        counts[sev] = counts.get(sev, 0) + 1
    return counts


def l5_conformance_metric(resource_type: str, outcomes: list[dict], igs: list[str] | None = None) -> MetricResult:
    """Population L5 score: resources with zero error/fatal issues over resources validated."""
    clean = sum(1 for o in outcomes if issue_counts(o)["error"] == 0 and issue_counts(o)["fatal"] == 0)
    totals = {"error": 0, "fatal": 0, "warning": 0, "information": 0}
    for o in outcomes:
        for k, v in issue_counts(o).items():
            totals[k] = totals.get(k, 0) + v
    return MetricResult(
        "conformance", "l5_ig_conformance", clean, len(outcomes),
        {"igs": igs or [], "issue_totals": totals, "resource_type": resource_type},
    )
