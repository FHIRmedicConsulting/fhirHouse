"""DEMO: materialize the view pack into a real DuckDB file you can open in a client.

    python -m fhirhouse_views  # (this module: fhirhouse_views/demo_materialize.py)
    python demo_materialize.py --examples <r4examples dir> --out fhirhouse_demo.duckdb

This bypasses Delta entirely (loads example FHIR JSON into one table) so it needs no
delta extension — it exists only to SHOW the compiled views producing populated flat
tables. In production the same compiled SQL runs over fhirEngine's Silver Delta tables
(FH-0003/FH-0005); nothing here is the real data path.
"""
from __future__ import annotations

import argparse
import glob
import json
import pathlib

import duckdb

from fhirhouse_views.compiler import MACROS, ViewCompiler

REPO = pathlib.Path(__file__).resolve().parent
DEFS = REPO / "definitions"


def load_examples(examples_dir: str) -> list[tuple[str, str, str]]:
    rows = []
    for f in glob.glob(str(pathlib.Path(examples_dir) / "*.json")):
        try:
            r = json.load(open(f))
        except Exception:
            continue
        rt = r.get("resourceType")
        rid = r.get("id")
        if rt and rid:
            rows.append((rt, rid, json.dumps(r)))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--examples", required=True)
    ap.add_argument("--out", default=str(REPO.parent / "fhirhouse_demo.duckdb"))
    args = ap.parse_args()

    con = duckdb.connect(args.out)
    for m in MACROS:
        con.execute(m)
    con.execute("CREATE OR REPLACE TABLE _resources(rtype VARCHAR, id VARCHAR, body JSON)")
    rows = load_examples(args.examples)
    con.executemany("INSERT INTO _resources VALUES (?,?,?)", rows)
    counts = dict(con.execute(
        "SELECT rtype, count(*) FROM _resources GROUP BY 1").fetchall())
    print(f"[demo] loaded {len(rows)} example resources across {len(counts)} types")

    built = skipped = 0
    for f in sorted(DEFS.glob("*.ViewDefinition.json")) + sorted(DEFS.glob("base/*.ViewDefinition.json")):
        view = json.loads(f.read_text())
        rtype, name = view["resource"], view["name"]
        if counts.get(rtype, 0) == 0:
            skipped += 1
            continue
        src = (f"SELECT body AS resource, id AS resource_key "
               f"FROM _resources WHERE rtype = '{rtype}'")
        for typed in (True, False):  # prefer native types; fall back to text
            try:
                sql = ViewCompiler(view, typed=typed).compile(src).sql
                con.execute(f'CREATE OR REPLACE TABLE "{name}" AS {sql}')
                built += 1
                break
            except Exception as e:
                if not typed:
                    print(f"[demo] skip {name}: {str(e)[:80]}")
                    skipped += 1
    print(f"[demo] built {built} view tables, skipped {skipped} (no examples / error)")
    print(f"[demo] wrote {args.out}")
    # show a sample
    n = con.execute("SELECT count(*) FROM information_schema.tables "
                    "WHERE table_name NOT LIKE '\\_%' ESCAPE '\\'").fetchone()[0]
    print(f"[demo] {n} objects now queryable in {pathlib.Path(args.out).name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
