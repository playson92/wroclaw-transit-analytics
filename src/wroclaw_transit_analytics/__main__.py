"""Public root CLI; the existing GTFS download CLI remains independent."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .analytics import analyze
from .database import DatabaseError, initialize, load_silver
from .preparation import PrepareError, prepare
from .sample_data import write_sample_data


def main(argv: list[str] | None = None) -> int:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Wrocław Transit Analytics — przygotowanie GTFS.")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare", help="Raw → bronze → silver i raport jakości.")
    prepare_parser.add_argument("--raw-manifest", type=Path, required=True)
    prepare_parser.add_argument("--output-root", type=Path, default=Path("data"))
    prepare_parser.add_argument("--batch-size", type=int, default=50_000)
    prepare_parser.add_argument("--json", dest="as_json", action="store_true")
    sample_parser = commands.add_parser(
        "sample-data", help="Wygeneruj jawnie syntetyczny raw GTFS."
    )
    sample_parser.add_argument("--output-root", type=Path, default=Path("data"))
    sample_parser.add_argument("--json", dest="as_json", action="store_true")
    init_parser = commands.add_parser("db-init", help="Transakcyjne migracje PostgreSQL 17.")
    init_parser.add_argument("--loader-role", help="Przyznaj istniejącej roli prawa append/read.")
    init_parser.add_argument("--reader-role", choices=["wta_reader"], help="Utwórz/grantuj reader.")
    init_parser.add_argument("--json", dest="as_json", action="store_true")
    load_parser = commands.add_parser("db-load", help="Zweryfikowane silver → PostgreSQL 17.")
    load_parser.add_argument("--silver-manifest", type=Path, required=True)
    load_parser.add_argument("--batch-size", type=int, default=50_000)
    load_parser.add_argument("--json", dest="as_json", action="store_true")
    analytics_parser = commands.add_parser("analytics", help="SQL gold dla jawnych dni usługi.")
    analytics_parser.add_argument("--dataset-id", required=True)
    analytics_parser.add_argument("--start-date", required=True)
    analytics_parser.add_argument("--end-date", required=True)
    analytics_parser.add_argument("--max-days", type=int, default=31)
    analytics_parser.add_argument("--max-events", type=int, default=5_000_000)
    analytics_parser.add_argument("--max-grid-rows", type=int, default=5_000_000)
    analytics_parser.add_argument("--timeout-seconds", type=int, default=120)
    analytics_parser.add_argument("--json", dest="as_json", action="store_true")
    for name in ("run", "demo"):
        flow = commands.add_parser(name, help="Istniejący pipeline raw → silver → SQL gold.")
        flow.add_argument("--output-root", type=Path, default=Path("data"))
        flow.add_argument("--json", dest="as_json", action="store_true")
        if name == "run":
            flow.add_argument("--raw-manifest", type=Path, required=True)
            flow.add_argument("--start-date", required=True)
            flow.add_argument("--end-date", required=True)
    dashboard_parser = commands.add_parser("dashboard", help="Dashboard z opcjonalnego extra.")
    dashboard_parser.add_argument("--port", type=int, default=8501)
    dashboard_parser.add_argument("--address", default="127.0.0.1")
    args = parser.parse_args(argv)
    try:
        if args.command == "dashboard":
            from .dashboard.launcher import launch

            return launch(args.port, args.address)
        elif args.command in ("run", "demo"):
            from . import pipeline

            result = (
                pipeline.demo(args.output_root)
                if args.command == "demo"
                else pipeline.run(
                    args.raw_manifest, args.start_date, args.end_date, args.output_root
                )
            )
            print(json.dumps(result, default=str, ensure_ascii=True))
            return 0 if result["status"] == "PASSED" else 1
        elif args.command == "analytics":
            analyzed = analyze(
                args.dataset_id,
                args.start_date,
                args.end_date,
                max_days=args.max_days,
                max_events=args.max_events,
                max_grid_rows=args.max_grid_rows,
                timeout_seconds=args.timeout_seconds,
            )
            print(
                json.dumps(asdict(analyzed))
                if args.as_json
                else f"{analyzed.status}: {analyzed.analysis_id}\nDataset: {analyzed.dataset_id}\n"
                f"Gold rows: {json.dumps(analyzed.row_counts)}\nCoverage: {json.dumps(analyzed.coverage)}"
            )
            return 0
        elif args.command == "db-init":
            applied = initialize(loader_role=args.loader_role, reader_role=args.reader_role)
            result = {"status": "INITIALIZED" if applied else "UP_TO_DATE", "applied": applied}
            print(
                json.dumps(result) if args.as_json else f"{result['status']}: {', '.join(applied)}"
            )
            return 0
        elif args.command == "db-load":
            loaded = load_silver(args.silver_manifest, batch_size=args.batch_size)
            print(
                json.dumps(asdict(loaded))
                if args.as_json
                else f"{loaded.status}: {loaded.dataset_id}"
            )
            return 0
        elif args.command == "sample-data":
            result = write_sample_data(args.output_root)
            if args.as_json:
                print(
                    json.dumps(
                        {
                            "status": "passed",
                            "data_kind": "synthetic_demo",
                            "notice": "DANE SYNTETYCZNE — nie rozkład MPK",
                            "raw_manifest": str(result.manifest_path),
                            "archive_path": str(result.archive_path),
                            "source_sha256": result.sha256,
                        }
                    )
                )
                return 0
            print(
                f"DANE SYNTETYCZNE — przykładowy GTFS, nie rozkład MPK.\n"
                f"Raw manifest: {result.manifest_path}\nZIP: {result.archive_path}\n"
                f"SHA-256: {result.sha256}"
            )
        else:
            result = prepare(args.raw_manifest, args.output_root, batch_size=args.batch_size)
            if args.as_json:
                print(
                    json.dumps(
                        {
                            "status": "passed",
                            "data_kind": result.data_kind,
                            "dataset_id": result.dataset_id,
                            "processing_run_id": result.processing_run_id,
                            "bronze_manifest": str(result.bronze_manifest),
                            "silver_manifest": str(result.silver_manifest),
                            "quality_report": str(result.quality_report),
                        }
                    )
                )
                return 0
            print(
                f"Prepare passed\nDane: {result.data_kind}\n"
                f"Dataset: {result.dataset_id}\nRun: {result.processing_run_id}\n"
                f"Bronze manifest: {result.bronze_manifest}\n"
                f"Silver manifest: {result.silver_manifest}\nDQ: {result.quality_report}"
            )
    except (DatabaseError, PrepareError, OSError) as exc:
        print(f"Błąd: {exc}", file=sys.stderr)
        if isinstance(exc, PrepareError):
            for manifest in exc.manifests:
                print(f"Manifest diagnostyczny: {manifest}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
