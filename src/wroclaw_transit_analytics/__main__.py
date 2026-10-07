"""Public root CLI; the existing GTFS download CLI remains independent."""

import argparse
import json
import sys
from pathlib import Path

from .preparation import PrepareError, prepare
from .sample_data import write_sample_data


def main(argv: list[str] | None = None) -> int:
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
    args = parser.parse_args(argv)
    try:
        if args.command == "sample-data":
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
    except (PrepareError, OSError) as exc:
        print(f"Błąd: {exc}", file=sys.stderr)
        if isinstance(exc, PrepareError):
            for manifest in exc.manifests:
                print(f"Manifest diagnostyczny: {manifest}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
