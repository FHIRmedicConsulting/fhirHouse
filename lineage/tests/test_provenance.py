"""Provenance bridge: body shape + Bronze row emission mirror upstream's pattern."""
import json

from fhirhouse_contracts import PathCatalog
from fhirhouse_lineage import build_provenance, write_provenance


def test_build_provenance_shape():
    prov = build_provenance("MATCH", ["Patient/a", "Patient/b"], "fhirhouse-mdm", "why", recorded="2026-07-06T00:00:00+00:00")
    assert prov["resourceType"] == "Provenance"
    assert [t["reference"] for t in prov["target"]] == ["Patient/a", "Patient/b"]
    assert prov["activity"]["coding"][0]["code"] == "MATCH"
    assert prov["agent"][0]["who"]["display"] == "fhirhouse-mdm"


def test_write_provenance_lands_bronze_row_with_target_index():
    captured = {}

    class Stub:
        def write_bronze_resource(self, table_path, row):
            captured["path"], captured["row"] = table_path, row
            return {"written": 1}

    prov = build_provenance("UPDATE", ["Patient/x"], "fhirhouse-dq", "dq run", recorded="2026-07-06T00:00:00+00:00")
    write_provenance(prov, sidecar=Stub(), catalog=PathCatalog("/x"), ingest_source="dq")
    assert captured["path"] == "/x/bronze/provenance"
    row = captured["row"]
    assert row["is_current"] is True and row["_ingest_source"] == "dq"
    assert row["search_param_index"] == [{"code": "target", "system": "", "value": "Patient/x"}]
    assert json.loads(row["body_json"])["id"] == row["id"]
