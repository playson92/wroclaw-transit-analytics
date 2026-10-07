"""Wheel installation in another directory must retain runnable SQL resources."""

import os
import subprocess
import sys
from pathlib import Path


def run(arguments, **kwargs):
    result = subprocess.run(arguments, capture_output=True, text=True, **kwargs)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_installed_wheel_contains_migrations(tmp_path):
    project = Path(__file__).resolve().parents[2]
    wheels = tmp_path / "wheels"
    run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            str(project),
            "--no-deps",
            "--no-build-isolation",
            "--no-index",
            "--no-cache-dir",
            "--wheel-dir",
            str(wheels),
        ],
    )
    wheel = next(wheels.glob("*.whl"))
    target = tmp_path / "installed"
    run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            str(wheel),
            "--no-deps",
            "--no-index",
            "--no-cache-dir",
            "--no-compile",
            "--target",
            str(target),
        ],
    )
    environment = {**os.environ, "PYTHONPATH": str(target)}
    environment.pop("DATABASE_URL", None)
    check = run(
        [
            sys.executable,
            "-c",
            "from wroclaw_transit_analytics.database.migrations import migration_files; import wroclaw_transit_analytics.database as db; print(db.__file__); print(migration_files()[0][0])",
        ],
        cwd=tmp_path,
        env=environment,
    )
    assert str(target) in check.stdout
    assert "001_warehouse.sql" in check.stdout
    run(
        [sys.executable, "-m", "wroclaw_transit_analytics", "db-init", "--help"],
        cwd=tmp_path,
        env=environment,
    )
