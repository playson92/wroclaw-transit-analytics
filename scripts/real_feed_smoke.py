"""Explicit opt-in download of one verified official resource, never part of normal pytest."""

import json
import os
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from wroclaw_transit_analytics import pipeline
from wroclaw_transit_analytics.gtfs.ingestion import ingest


def main():
    if os.environ.get("WTA_REAL_E2E") != "1":
        raise RuntimeError("Real download requires explicit WTA_REAL_E2E=1")
    root = Path("/work") / ("real-" + uuid4().hex)
    url = "https://open-data.cui.wroclaw.pl/hdb/download/141/"
    downloaded = ingest(url, root / "raw" / "gtfs")
    if downloaded.validation.status != "passed":
        raise RuntimeError("Official archive did not pass the existing validator")
    result = pipeline.run(downloaded.manifest_path, "2026-10-07", "2026-10-08", root)
    output = Path("/work/real-evidence")
    output.mkdir(exist_ok=True)
    (output / "pipeline.json").write_text(
        json.dumps(result, default=str, indent=2), encoding="utf-8"
    )
    if result["status"] != "PASSED":
        raise RuntimeError("Real pipeline failed; see per-stage report")
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        parameters = (result["dataset_id"], result["analysis_id"])
        days = conn.execute(
            "SELECT service_date,calendar_covered,active_services,trip_instances "
            "FROM gold.analysis_days WHERE dataset_id=%s AND analysis_id=%s ORDER BY service_date",
            parameters,
        ).fetchall()
        assert len(days) == 2 and all(
            r["calendar_covered"] and r["trip_instances"] > 0 for r in days
        )
        kpi = conn.execute(
            "SELECT (SELECT sum(trip_instances) FROM gold.analysis_days "
            "WHERE dataset_id=%s AND analysis_id=%s) AS trips, "
            "(SELECT sum(regular_known_departures) FROM gold.coverage_daily WHERE dataset_id=%s AND analysis_id=%s) AS departures, "
            "(SELECT count(DISTINCT route_id) FROM gold.route_daily WHERE dataset_id=%s AND analysis_id=%s AND trip_count>0) AS active_routes, "
            "(SELECT count(DISTINCT stop_id) FROM gold.service_span WHERE dataset_id=%s AND analysis_id=%s) AS served_stops",
            parameters * 4,
        ).fetchone()
        routes = conn.execute(
            "SELECT route_id,sum(trip_count) AS trips FROM gold.route_daily "
            "WHERE dataset_id=%s AND analysis_id=%s GROUP BY route_id ORDER BY trips DESC,route_id LIMIT 5",
            parameters,
        ).fetchall()
        coverage = conn.execute(
            "SELECT * FROM gold.coverage_daily WHERE dataset_id=%s AND analysis_id=%s ORDER BY service_date",
            parameters,
        ).fetchall()
    prepared = result["stages"]["prepare"]
    for name, path in (
        ("raw-manifest.json", downloaded.manifest_path),
        ("silver-manifest.json", Path(prepared["silver_manifest"])),
        ("quality.json", Path(prepared["quality_report"])),
    ):
        (output / name).write_bytes(path.read_bytes())
    evidence = {
        "status": "PASS",
        "url": url,
        "download": asdict(downloaded.download),
        "dataset_id": result["dataset_id"],
        "analysis_id": result["analysis_id"],
        "start_date": "2026-10-07",
        "end_date": "2026-10-08",
        "days": days,
        "expected_ui_kpi": kpi,
        "top_routes": routes,
        "coverage": coverage,
    }
    (output / "real-smoke.json").write_text(
        json.dumps(evidence, default=str, indent=2), encoding="utf-8"
    )
    print(json.dumps(evidence, default=str))


if __name__ == "__main__":
    main()
