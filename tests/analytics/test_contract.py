"""CLI admission and versioned identity are offline; numerical KPI tests use PostgreSQL."""

from datetime import date

import pytest

from wroclaw_transit_analytics.__main__ import main
from wroclaw_transit_analytics.analytics import AnalyticsError, analysis_id, analyze
from wroclaw_transit_analytics.analytics.runner import rules_digest, sql_text

DATASET = "gtfs_" + "a" * 64


def test_identity_versions_dates_and_packaged_rules():
    start, end = date(2026, 10, 1), date(2026, 10, 2)
    identity = analysis_id(DATASET, start, end)
    assert identity == analysis_id(DATASET, start, end)
    assert identity != analysis_id(DATASET, start, end, "next-version")
    assert identity != analysis_id(DATASET, start, start)
    assert len(rules_digest()) == 64
    assert "lag(departure_seconds)" in sql_text("departures.sql")


@pytest.mark.parametrize(
    "start,end",
    [("20261001", "2026-10-02"), ("2026-02-30", "2026-10-02"), ("2026-10-03", "2026-10-02")],
)
def test_date_rejections_before_database(start, end):
    with pytest.raises(AnalyticsError, match="INVALID_DATES"):
        analyze(DATASET, start, end, "invalid DSN")


def test_limits_and_cli_errors_without_database(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit) as caught:
        main(["analytics", "--help"])
    assert caught.value.code == 0
    arguments = [
        "analytics",
        "--dataset-id",
        DATASET,
        "--start-date",
        "2026-10-01",
        "--end-date",
        "2026-10-02",
    ]
    assert main(arguments) == 1 and "DATABASE_URL" in capsys.readouterr().err
    assert (
        main([*arguments, "--max-events", "0"]) == 1 and "INVALID_LIMITS" in capsys.readouterr().err
    )
    with pytest.raises(AnalyticsError, match="LIMIT_EXCEEDED"):
        analyze(DATASET, "2026-10-01", "2026-11-01")
    with pytest.raises(AnalyticsError, match="INVALID_DATASET_ID"):
        analyze("bad", "2026-10-01", "2026-10-02")
    monkeypatch.setenv("DATABASE_URL", "invalid=ANALYTICS_SECRET")
    assert main(arguments) == 1
    assert "ANALYTICS_SECRET" not in capsys.readouterr().err
