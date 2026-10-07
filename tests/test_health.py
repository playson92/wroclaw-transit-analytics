"""Tests for the application health check."""

from wroclaw_transit_analytics.health import health_check


def test_health_check_returns_ok_status() -> None:
    """Health check should return an OK status."""
    assert health_check() == {"status": "ok"}
