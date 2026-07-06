"""HTTP client for fhirEngine's delta-rs sidecar (packages/server/sidecar/delta_sidecar.py).

The sidecar is the single writer per Delta table (fhirEngine ADR-0026 §5; FH-0003):
all fhirHouse persistence goes through it. Reads may also use it (`query` runs
DataFusion), but bulk analytical reads should prefer read-side delta-rs/DuckDB
(`deltalake.DeltaTable` / dbt-duckdb) to keep load off the writer.

Stdlib-only (urllib), mirroring the sidecar's own no-framework stance.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


class SidecarError(RuntimeError):
    pass


class SidecarClient:
    def __init__(self, url: str | None = None, token: str | None = None, timeout: float = 300.0):
        self.url = (url or os.environ.get("FHIRENGINE_DELTA_SIDECAR_URL", "http://127.0.0.1:8077")).rstrip("/")
        self.token = token if token is not None else os.environ.get("FHIRENGINE_SIDECAR_TOKEN", "")
        self.timeout = timeout

    def _post(self, route: str, payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{self.url}{route}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", **({"X-Sidecar-Token": self.token} if self.token else {})},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            raise SidecarError(f"sidecar {route} -> HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise SidecarError(f"sidecar unreachable at {self.url}: {e.reason}") from e
        if isinstance(body, dict) and body.get("error"):
            raise SidecarError(f"sidecar {route} -> {body['error']}: {body.get('detail', '')}")
        return body

    def health(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.url}/health", timeout=5) as resp:
                return bool(json.loads(resp.read()).get("ok"))
        except OSError:
            return False

    def write(self, table_path: str, rows: list[dict], mode: str = "append", schema: str = "infer") -> dict:
        """Append/overwrite rows. `schema="bronze"` for Bronze-shaped rows, else "infer"."""
        return self._post("/write", {"table_path": table_path, "rows": rows, "mode": mode, "schema": schema})

    def merge(self, table_path: str, rows: list[dict], key: str = "id", schema: str = "infer") -> dict:
        return self._post("/merge", {"table_path": table_path, "rows": rows, "key": key, "schema": schema})

    def query(self, sql: str, tables: dict[str, str]) -> list[dict]:
        return self._post("/query", {"sql": sql, "tables": tables})["rows"]

    def delete(self, table_path: str, predicate: str | None = None) -> dict:
        payload: dict[str, Any] = {"table_path": table_path}
        if predicate:
            payload["predicate"] = predicate
        return self._post("/delete", payload)

    def write_bronze_resource(self, table_path: str, resource_row: dict) -> dict:
        """Land a Bronze-shaped resource row (e.g. a Provenance emitted by governance)."""
        return self.write(table_path, [resource_row], mode="append", schema="bronze")
