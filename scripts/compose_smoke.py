"""Run inside the built non-root pipeline image; use the public CLI end to end."""

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql

from wroclaw_transit_analytics.database.verification import verified_silver
from wroclaw_transit_analytics.preparation.contract import TABLES


def cli(*arguments):
    result = subprocess.run(
        [sys.executable, "-m", "wroclaw_transit_analytics", *map(str, arguments), "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def main():
    if os.geteuid() == 0:
        raise RuntimeError("Smoke must exercise the non-root image user")
    root = Path("/work") / ("smoke-" + uuid4().hex)
    sample = cli("sample-data", "--output-root", root)
    prepared = cli(
        "prepare",
        "--raw-manifest",
        sample["raw_manifest"],
        "--output-root",
        root,
        "--batch-size",
        2,
    )
    manifest = Path(prepared["silver_manifest"])
    first = cli("db-load", "--silver-manifest", manifest, "--batch-size", 2)
    second = cli("db-load", "--silver-manifest", manifest, "--batch-size", 3)
    assert first["status"] in ("LOADED", "ALREADY_LOADED")
    if os.environ.get("WTA_SMOKE_REQUIRE_NEW") == "1":
        assert first["status"] == "LOADED"
    assert second["status"] == "ALREADY_LOADED"
    arguments = [
        "analytics",
        "--dataset-id",
        first["dataset_id"],
        "--start-date",
        "2026-10-01",
        "--end-date",
        "2026-10-07",
    ]
    analyzed = cli(*arguments)
    repeated = cli(*arguments)
    assert analyzed["status"] in ("ANALYZED", "ALREADY_ANALYZED")
    if os.environ.get("WTA_SMOKE_REQUIRE_NEW") == "1":
        assert analyzed["status"] == "ANALYZED"
    assert repeated["status"] == "ALREADY_ANALYZED"
    assert analyzed["coverage"]["total_events"] == 48
    assert analyzed["coverage"]["known_departures"] == 44
    assert analyzed["coverage"]["regular_known_departures"] == 25
    assert analyzed["row_counts"]["route_daily"] == 14
    full_first = cli("demo", "--output-root", root / "full-first")
    full_repeat = cli("demo", "--output-root", root / "full-repeat")
    assert full_first["status"] == full_repeat["status"] == "PASSED"
    assert full_repeat["dataset_id"] == first["dataset_id"]
    assert full_repeat["analysis_id"] == analyzed["analysis_id"]
    assert full_repeat["stages"]["load"]["status"] == "ALREADY_LOADED"
    assert full_repeat["stages"]["analyze"]["status"] == "ALREADY_ANALYZED"
    with verified_silver(manifest) as verified, psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        assert conn.info.server_version // 10000 == 17
        server_version = conn.info.server_version
        role = conn.execute(
            "SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        assert role == (False, False, False)
        assert not conn.execute(
            "SELECT has_schema_privilege(current_user, 'silver', 'CREATE')"
        ).fetchone()[0]
        assert not conn.execute(
            "SELECT has_table_privilege(current_user, 'meta.datasets', 'UPDATE,DELETE,TRUNCATE')"
        ).fetchone()[0]
        counts = {}
        for name in TABLES:
            counts[name] = conn.execute(
                sql.SQL("SELECT count(*) FROM {} WHERE dataset_id=%s").format(
                    sql.Identifier("silver", name)
                ),
                (first["dataset_id"],),
            ).fetchone()[0]
        assert counts == {
            name: entry["row_count"] for name, entry in verified.manifest["tables"].items()
        }
        saved = conn.execute(
            "SELECT status, data_kind, capabilities FROM meta.datasets WHERE dataset_id=%s",
            (first["dataset_id"],),
        ).fetchone()
        assert saved == ("complete", "synthetic_demo", verified.manifest["capabilities"])
        analysis_id = analyzed["analysis_id"]
        route_select = conn.execute(
            "SELECT route_id, trip_count FROM gold.route_daily "
            "WHERE analysis_id=%s AND service_date='2026-10-07' ORDER BY route_id",
            (analysis_id,),
        ).fetchall()
        assert route_select == [("D1", 0), ("D2", 1)]
        headway_select = conn.execute(
            "SELECT departure_count, interval_count, avg_seconds, median_seconds, p90_seconds "
            "FROM gold.route_stop_headways WHERE analysis_id=%s AND service_date='2026-10-01' "
            "AND route_id='D1' AND stop_id='0001' AND direction_id=0",
            (analysis_id,),
        ).fetchone()
        assert headway_select == (2, 1, 1800, 1800.0, 1800.0)
        assert not conn.execute(
            "SELECT has_schema_privilege(current_user, 'gold', 'CREATE')"
        ).fetchone()[0]
        assert not conn.execute(
            "SELECT has_table_privilege(current_user, 'gold.route_daily', 'UPDATE,DELETE,TRUNCATE')"
        ).fetchone()[0]
    evidence = {
        "status": "PASS",
        "full_demo": full_first,
        "demo_repeat": full_repeat,
        "expected_ui_kpi": {"trips": 16, "departures": 25, "active_routes": 2, "served_stops": 3},
        "dataset_id": first["dataset_id"],
        "row_counts": counts,
        "second_load": second["status"],
        "uid": os.geteuid(),
        "server_version": server_version,
        "analysis_id": analyzed["analysis_id"],
        "analytics_second_call": repeated["status"],
        "gold_row_counts": analyzed["row_counts"],
        "selected_day_coverage": analyzed["coverage"],
        "route_daily_oct07": route_select,
        "headways_d1_0001_oct01": [
            str(value) if hasattr(value, "as_tuple") else value for value in headway_select
        ],
    }
    Path("/work/compose-smoke.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()
