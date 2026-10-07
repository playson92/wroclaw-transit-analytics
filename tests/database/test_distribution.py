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
            "from wroclaw_transit_analytics.database.migrations import migration_files; import wroclaw_transit_analytics.database as db; from wroclaw_transit_analytics.analytics.runner import sql_text, rules_digest; print(db.__file__); print([item[0] for item in migration_files()]); print(sql_text('departures.sql')); print(rules_digest())",
        ],
        cwd=tmp_path,
        env=environment,
    )
    assert str(target) in check.stdout
    assert "001_warehouse.sql" in check.stdout
    assert "002_gold.sql" in check.stdout
    assert "lag(departure_seconds)" in check.stdout
    dashboard_sql = run(
        [
            sys.executable,
            "-c",
            "from wroclaw_transit_analytics.dashboard.data import sql_text; "
            "from importlib.resources import files; print(sql_text('overview.sql')); "
            "print(files('wroclaw_transit_analytics.dashboard').joinpath('app.py').is_file())",
        ],
        cwd=tmp_path,
        env=environment,
    )
    assert "count(DISTINCT route_id)" in dashboard_sql.stdout
    assert "True" in dashboard_sql.stdout
    run(
        [sys.executable, "-m", "wroclaw_transit_analytics", "db-init", "--help"],
        cwd=tmp_path,
        env=environment,
    )
    run(
        [sys.executable, "-m", "wroclaw_transit_analytics", "analytics", "--help"],
        cwd=tmp_path,
        env=environment,
    )
