"""Read-only acceptance evidence for the packaged portfolio sample.

Run inside the demo dashboard image. This checks real PostgreSQL state and
exports browser expectations; it never provisions data or prints credentials.
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
from datetime import timedelta
from importlib.resources import files
from pathlib import Path

import pandas  # noqa: F401
import pyarrow  # noqa: F401
from psycopg.conninfo import make_conninfo

from wroclaw_transit_analytics.dashboard import data
from wroclaw_transit_analytics.explorer import data as explorer


def course(dataset, day, route, variant, trip):
    visits = explorer.fetch("stops", dataset, day, route, variant, trip["trip_id"])
    geometry = explorer.fetch("geometry", dataset, day, route, variant, trip["trip_id"])
    assert visits and geometry, "The selected course needs visits and real shapes"
    assert [v["stop_sequence"] for v in visits] == sorted(v["stop_sequence"] for v in visits)
    return {
        **trip,
        "day": day,
        "visits": len(visits),
        "first_stop_name": visits[0]["stop_name"],
        "last_stop_name": visits[-1]["stop_name"],
        "stops": [
            {k: v[k] for k in ("stop_id", "stop_name", "stop_sequence", "departure_seconds")}
            for v in visits
        ],
        "shape_points": len(geometry),
        "visits_records": visits,
        "geometry_records": geometry,
    }


def first_course(dataset, day, route):
    variants = explorer.fetch("variants", dataset, day, route)
    assert variants, "The sample route must have service on its first calendar day"
    variant = variants[0]["variant_key"]
    trip = explorer.fetch("trips", dataset, day, route, variant)[0]
    return course(dataset, day, route, variant, trip)


def verify():
    catalog = data.catalog()
    assert len(catalog["datasets"]) == len(catalog["analyses"]) == 1, "Expected one isolated sample"
    dataset = catalog["datasets"][0]
    analysis = catalog["analyses"][0]
    dataset_id = dataset["dataset_id"]
    assert dataset["data_kind"] == "real_gtfs"
    assert analysis["dataset_id"] == dataset_id
    sample = dataset["provenance"].get("derivative_sample")
    assert sample, "A derivative sample must retain explicit provenance"
    metadata = explorer.metadata(dataset_id)
    day = metadata["start_date"]
    assert day is not None and day <= metadata["end_date"]
    context = data.Context(
        dataset_id, analysis["analysis_id"], analysis["start_date"], analysis["end_date"]
    )
    overview = data.fetch("overview", context)
    kpi = overview["kpi"]
    assert kpi["trips"] > 0 and kpi["departures"] > 0
    assert kpi["covered_days"] == kpi["requested_days"] == 7
    routes = explorer.fetch("routes", dataset_id)
    assert {r["route_short_name"] for r in routes} == {"1", "10", "100", "106"}
    assert kpi["active_routes"] == len(routes) == 4
    assert {r["route_type"] for r in routes} >= {0, 3}
    active = {r["route_id"] for r in explorer.fetch("active_routes", dataset_id, day)}
    default_route = next(r["route_id"] for r in routes if r["route_id"] in active)
    default = first_course(dataset_id, day, default_route)
    bus_route = next(r["route_id"] for r in routes if r["route_short_name"] == "100")
    bus = first_course(dataset_id, day, bus_route)
    late_route = next(r["route_id"] for r in routes if r["route_short_name"] == "10")
    late = None
    for offset in range(7):
        late_day = day + timedelta(days=offset)
        for variant in explorer.fetch("variants", dataset_id, late_day, late_route):
            trips = explorer.fetch(
                "trips", dataset_id, late_day, late_route, variant["variant_key"]
            )
            for trip in trips:
                if trip["end_seconds"] is not None and trip["end_seconds"] >= 86400:
                    late = course(dataset_id, late_day, late_route, variant["variant_key"], trip)
                    break
            if late:
                break
        if late:
            break
    assert late, "The original archive contains a late course; the sample must retain it"
    with data.reader() as conn:
        roles = conn.execute(
            "SELECT current_user AS role, rolsuper,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls "
            "FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        assert roles["role"] == "wta_reader" and not any(v for k, v in roles.items() if k != "role")
        permissions = conn.execute(
            "SELECT has_schema_privilege(current_user,'silver','USAGE') AS silver_usage, "
            "has_database_privilege(current_user,current_database(),'CREATE') AS database_create, "
            "has_schema_privilege(current_user,'public','CREATE') AS public_schema_create, "
            "has_table_privilege(current_user,'meta.datasets','INSERT,UPDATE,DELETE,TRUNCATE') AS meta_write, "
            "has_table_privilege(current_user,'gold.analysis_days','INSERT,UPDATE,DELETE,TRUNCATE') AS gold_write, "
            "has_table_privilege(current_user,'explorer.shape_points','INSERT,UPDATE,DELETE,TRUNCATE') AS explorer_write, "
            "EXISTS(SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles "
            "WHERE rolname=current_user)) AS role_memberships"
        ).fetchone()
        assert not any(permissions.values()), "Reader must not gain write or silver privileges"
        assert (
            conn.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"] == "on"
        )
        persisted = conn.execute(
            "SELECT (SELECT count(*) FROM meta.datasets) AS datasets, "
            "(SELECT count(*) FROM meta.analyses) AS analyses, "
            "(SELECT count(*) FROM gold.route_daily) AS route_daily, "
            "(SELECT count(*) FROM explorer.shape_points) AS shape_points"
        ).fetchone()
        geometry = conn.execute(
            "SELECT status,source_sha256,point_count FROM explorer.geometry_imports WHERE dataset_id=%s",
            (dataset_id,),
        ).fetchone()
        assert (
            geometry["status"] == "complete"
            and geometry["point_count"] == persisted["shape_points"] > 0
        )
        assert geometry["source_sha256"] == metadata["source_sha256"]
        sql_kpi = conn.execute(
            "SELECT sum(trip_instances) AS trips FROM gold.analysis_days WHERE dataset_id=%s AND analysis_id=%s",
            (dataset_id, analysis["analysis_id"]),
        ).fetchone()
        assert sql_kpi["trips"] == kpi["trips"]
    return {
        "status": "PASSED",
        "dataset_id": dataset_id,
        "analysis_id": analysis["analysis_id"],
        "start_date": context.start,
        "end_date": context.end,
        "calendar_start": day,
        "calendar_end": metadata["end_date"],
        "source_sha256": metadata["source_sha256"],
        "provenance": dataset["provenance"],
        "kpi": kpi,
        "persisted": persisted,
        "reader": {
            "role": roles["role"],
            "permissions": permissions,
            "read_only_transaction": True,
        },
        "default": default,
        "bus": bus,
        "late": late,
        "native_runtime": {
            "system": platform.system(),
            "machine": platform.machine(),
            "uid": os.getuid() if hasattr(os, "getuid") else None,
            "dependencies": {
                package: importlib.metadata.version(package)
                for package in ("pandas", "pyarrow", "psycopg-binary", "streamlit")
            },
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-file", type=Path)
    parser.add_argument("--database-host", default="postgres")
    parser.add_argument("--database-name", default="wta")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.credential_file:
        os.environ["READONLY_DATABASE_URL"] = make_conninfo(
            host=args.database_host,
            dbname=args.database_name,
            user="wta_reader",
            password=args.credential_file.read_text(encoding="utf-8").strip(),
        )
    report = verify()
    assets = files("wroclaw_transit_analytics.portfolio").joinpath("assets")
    archive = next(p for p in assets.iterdir() if p.name.endswith(".zip"))
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == report["source_sha256"]
    serialized = json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")


if __name__ == "__main__":
    main()
