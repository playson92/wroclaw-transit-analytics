"""Thin orchestration: files and two independent database transactions."""

from dataclasses import asdict
from pathlib import Path

from .analytics import analyze
from .database import DatabaseError, load_silver
from .preparation import PrepareError, prepare
from .sample_data import write_sample_data

DEMO_START = "2026-10-01"
DEMO_END = "2026-10-07"


def run(raw_manifest, start_date, end_date, output_root=Path("data"), database_url=None):
    report = {
        "status": "RUNNING",
        "raw_manifest": str(Path(raw_manifest).resolve()),
        "dataset_id": None,
        "analysis_id": None,
        "stages": {name: {"status": "NOT_RUN"} for name in ("prepare", "load", "analyze")},
    }
    stage = "prepare"
    try:
        prepared = prepare(Path(raw_manifest), Path(output_root))
        report["stages"][stage] = {"status": "PASSED", **asdict(prepared)}
        report["dataset_id"] = prepared.dataset_id
        stage = "load"
        loaded = load_silver(prepared.silver_manifest, database_url)
        report["stages"][stage] = asdict(loaded)
        stage = "analyze"
        analyzed = analyze(loaded.dataset_id, start_date, end_date, database_url)
        report["stages"][stage] = asdict(analyzed)
        report["analysis_id"] = analyzed.analysis_id
        report["status"] = "PASSED"
    except (DatabaseError, PrepareError, OSError) as exc:
        report["status"] = "FAILED"
        report["stages"][stage] = {
            "status": "FAILED",
            "error": str(exc) if isinstance(exc, (DatabaseError, PrepareError)) else "Błąd plików.",
        }
        if isinstance(exc, PrepareError):
            report["stages"][stage]["diagnostic_manifests"] = list(map(str, exc.manifests))
    return report


def demo(output_root=Path("data"), database_url=None):
    sample = write_sample_data(Path(output_root))
    return run(sample.manifest_path, DEMO_START, DEMO_END, output_root, database_url)
