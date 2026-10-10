import os
import subprocess
import sys
from datetime import date
from importlib.resources import files
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from wroclaw_transit_analytics import pipeline
from wroclaw_transit_analytics.dashboard import cache, data
from wroclaw_transit_analytics.dashboard.formatting import notice, number, percent, service_time
from wroclaw_transit_analytics.database import DatabaseError


def test_core_help_without_optional_streamlit_or_database(tmp_path):
    # Block the actual import, rather than merely asserting it isn't installed in this environment.
    script = """
import sys, importlib.abc
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('streamlit'):
            raise ImportError('blocked optional dependency')
sys.meta_path.insert(0, Block())
import wroclaw_transit_analytics
from wroclaw_transit_analytics.__main__ import main
main(['--help'])
"""
    environment = {k: v for k, v in os.environ.items() if "DATABASE_URL" not in k}
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert all(word in result.stdout for word in ("run", "demo", "dashboard", "analytics"))


@pytest.mark.parametrize(
    "seconds,expected",
    [(None, "Brak czasu"), (0, "00:00:00"), (90600, "25:10:00"), (3600000000, "1000000:00:00")],
)
def test_service_time(seconds, expected):
    assert service_time(seconds) == expected


def test_null_zero_kind_and_ratio():
    assert number(None) != number(0)
    assert percent(0, 0) == percent(None, 3) == "Nieokreślone"
    assert percent(3, 4) == "75.0%"
    assert "SYNTETYCZNE" in notice("synthetic_benchmark")
    assert notice(None) == "Niepotwierdzony rodzaj danych"


@pytest.mark.parametrize("failing", ["prepare", "load", "analyze"])
def test_pipeline_stops_and_preserves_completed_stages(monkeypatch, tmp_path, failing):
    from dataclasses import dataclass

    @dataclass
    class Prepared:
        dataset_id: str = "dataset"
        silver_manifest: str = "silver.json"

    @dataclass
    class Loaded:
        dataset_id: str = "dataset"
        status: str = "LOADED"

    @dataclass
    class Analyzed:
        analysis_id: str = "analysis"
        status: str = "ANALYZED"

    calls = []
    for name, response in (("prepare", Prepared()), ("load", Loaded()), ("analyze", Analyzed())):

        def action(*args, _name=name, _response=response):
            calls.append(_name)
            if _name == failing:
                raise DatabaseError("Bezpieczny błąd")
            return _response

        monkeypatch.setattr(pipeline, {"load": "load_silver"}.get(name, name), action)
    result = pipeline.run(tmp_path / "raw.json", "2026-10-01", "2026-10-07", tmp_path)
    names = ["prepare", "load", "analyze"]
    assert calls == names[: names.index(failing) + 1]
    assert result["status"] == "FAILED"
    assert result["stages"][failing]["status"] == "FAILED"
    assert all(
        result["stages"][n]["status"] == "NOT_RUN" for n in names[names.index(failing) + 1 :]
    )


@pytest.fixture
def fake_data(monkeypatch):
    cache.refresh()
    monkeypatch.setenv("READONLY_DATABASE_URL", "fake-reader-secret")
    start, end = date(2026, 10, 1), date(2026, 10, 7)
    catalog = {
        "datasets": [
            {"dataset_id": "d1", "data_kind": "synthetic_demo"},
            {"dataset_id": "d2", "data_kind": "synthetic_benchmark"},
            {"dataset_id": "no-gold", "data_kind": None},
        ],
        "analyses": [
            {"dataset_id": "d1", "analysis_id": "a1", "start_date": start, "end_date": end},
            {"dataset_id": "d1", "analysis_id": "a2", "start_date": end, "end_date": end},
            {"dataset_id": "d2", "analysis_id": "a3", "start_date": end, "end_date": end},
        ],
    }
    calls = []

    def fetch(view, context):
        calls.append((view, context))
        if view == "overview":
            return {
                "kpi": {
                    "trips": 0 if context.analysis == "a2" else 17,
                    "departures": None,
                    "active_routes": 2,
                    "served_stops": 3,
                    "catalog_stops": 7,
                    "covered_days": 6,
                    "requested_days": 7,
                    "regular_events": None,
                },
                "routes": [],
                "stops": [],
                "coverage": [],
                "hourly": [{"service_hour": 1000000, "departures": 1}],
            }
        if view == "filters":
            return {
                "routes": [
                    {"route_id": "001", "route_short_name": "Demo", "route_long_name": ""},
                    {"route_id": "002", "route_short_name": "Demo", "route_long_name": ""},
                ],
                "stops": [
                    {"stop_id": "0001", "stop_name": "Ta sama nazwa"},
                    {"stop_id": "0002", "stop_name": "Ta sama nazwa"},
                ],
                "directions": [{"direction_id": None}, {"direction_id": 0}, {"direction_id": 1}],
            }
        if view == "group":
            return {
                "daily": [
                    {
                        "service_date": start,
                        "calendar_covered": True,
                        "departures": 1,
                        "regular_events": 2,
                        "missing": 1,
                        "approximate": 0,
                        "first_seconds": 90600,
                        "last_seconds": 3600000000,
                    }
                ],
                "hourly": [],
                "headways": [
                    {
                        "service_date": start,
                        "direction_id": None,
                        "departure_count": 1,
                        "interval_count": 0,
                        "avg_seconds": None,
                        "median_seconds": None,
                        "p90_seconds": None,
                    }
                ],
            }
        return {
            "dataset": {
                "dataset_id": context.dataset,
                "data_kind": "synthetic_demo",
                "provenance": {},
                "loaded_at": start,
                "model_version": "wta-silver-v1",
                "source_sha256": "hash",
                "logical_fingerprint": "fp",
                "quality_report": {},
                "capabilities": {},
            },
            "analysis": {
                "analysis_id": context.analysis,
                "created_at": end,
                "metrics_version": "wta-gold-v1",
                "start_date": start,
                "end_date": end,
            },
            "coverage": [],
        }

    monkeypatch.setattr(data, "catalog", lambda: catalog)
    monkeypatch.setattr(data, "fetch", fetch)
    yield catalog, calls
    cache.refresh()


def app():
    at = AppTest.from_file(
        str(files("wroclaw_transit_analytics.dashboard").joinpath("app.py")), default_timeout=15
    )
    at.session_state["view"] = "Analityka"
    return at.run()


def test_app_favicon_is_marshaled_as_local_svg_without_external_resources(fake_data, monkeypatch):
    import base64
    from types import SimpleNamespace
    from xml.etree import ElementTree

    from streamlit.commands import page_config

    messages = []
    get_context = page_config.get_script_run_ctx

    def capture_context():
        context = get_context()

        def enqueue(message):
            messages.append(message)
            context.enqueue(message)

        return SimpleNamespace(enqueue=enqueue)

    monkeypatch.setattr(page_config, "get_script_run_ctx", capture_context)
    at = app()
    assert not at.exception and not at.error
    icons = [
        message.page_config_changed.favicon
        for message in messages
        if message.WhichOneof("type") == "page_config_changed"
    ]
    assert len(icons) == 1 and icons[0].startswith("data:image/svg+xml;base64,")
    svg = ElementTree.fromstring(base64.b64decode(icons[0].split(",", 1)[1]))
    assert svg.tag == "{http://www.w3.org/2000/svg}svg"
    assert not any(
        attribute.endswith(("href", "src"))
        for element in svg.iter()
        for attribute in element.attrib
    )


def test_three_views_dependent_filters_and_null_direction(fake_data):
    _, calls = fake_data
    at = app()
    assert not at.exception and not at.error
    assert any("SYNTETYCZNE" in w.value for w in at.caption)
    assert at.metric[0].value == "17"
    assert at.metric[1].value == "Brak danych"
    at.segmented_control(key="analytics_view").set_value("Linia / punkt zatrzymania").run()
    assert at.selectbox(key="filter_stop").value == "0001"
    assert at.selectbox(key="filter_direction").options == [
        "Wszystkie kierunki",
        "Niepodany",
        "0",
        "1",
    ]
    at.selectbox(key="filter_direction").set_value("NULL").run()
    assert calls[-1][1].direction == "NULL"
    assert not at.metric  # No false trip_count with stop/direction filter.
    assert at.dataframe[0].value["Pierwszy znany czas"].iloc[0] == "25:10:00"
    assert at.dataframe[0].value["Ostatni znany czas"].iloc[0] == "1000000:00:00"
    at.selectbox(key="filter_stop").set_value("0002").run()
    assert at.selectbox(key="filter_direction").value == "ALL"
    at.selectbox(key="filter_route").set_value("002").run()
    assert at.selectbox(key="filter_stop").value == "0001"
    at.segmented_control(key="view").set_value("Dane").run()
    assert not at.exception and not at.error
    assert any("Lokalny generator" in t.value for t in at.text)


def test_snapshot_analysis_reset_and_missing_gold(fake_data):
    at = app()
    at.selectbox(key="analysis").set_value("a2").run()
    assert at.date_input(key="dates").value == (date(2026, 10, 7), date(2026, 10, 7))
    assert at.metric[0].value == "0"
    at.selectbox(key="dataset").set_value("d2").run()
    assert at.selectbox(key="analysis").value == "a3"
    at.selectbox(key="dataset").set_value("no-gold").run()
    assert any("Brak kompletnej analizy" in i.value for i in at.info)
    assert not at.metric


def test_empty_catalog_and_database_failure(fake_data, monkeypatch):
    cache.refresh()
    monkeypatch.setattr(data, "catalog", lambda: {"datasets": [], "analyses": []})
    assert "Brak zaimportowanych" in app().info[0].value
    cache.refresh()

    def fail():
        raise data.DashboardError("Baza niedostępna")

    monkeypatch.setattr(data, "catalog", fail)
    at = app()
    assert at.error[0].value == "Baza niedostępna" and not at.exception
    monkeypatch.delenv("READONLY_DATABASE_URL")
    assert "READONLY_DATABASE_URL" in app().error[0].value


def test_cache_refresh_and_source_isolation(fake_data):
    _, calls = fake_data
    at = app()
    initial = len(calls)
    at.run()
    assert len(calls) == initial
    at.button[0].click().run()
    assert len(calls) > initial
    assert data.source_key() != "fake-reader-secret"


def test_invalid_dsn_redacted(monkeypatch):
    monkeypatch.setenv("READONLY_DATABASE_URL", "secret_invalid_password_123")
    with pytest.raises(data.DashboardError) as error, data.reader():
        pass
    assert "secret_invalid_password_123" not in str(error.value)


def test_cache_error_is_not_empty_success_and_database_source_changes(fake_data, monkeypatch):
    catalog, _ = fake_data
    calls = []

    def failing_catalog():
        calls.append(True)
        raise data.DashboardError("Baza niedostępna")

    cache.refresh()
    monkeypatch.setattr(data, "catalog", failing_catalog)
    assert app().error
    assert app().error
    assert len(calls) == 2
    monkeypatch.setattr(data, "catalog", lambda: catalog)
    at = app()
    assert at.metric[0].value == "17"
    monkeypatch.setenv("READONLY_DATABASE_URL", "another-source")
    monkeypatch.setattr(data, "catalog", lambda: {"datasets": [], "analyses": []})
    assert app().info[0].value.startswith("Brak zaimportowanych")


def test_server_limit_is_an_error_not_a_truncated_result():
    class Cursor:
        def fetchmany(self, size):
            assert size == 3
            return [{"row": 1}, {"row": 2}, {"row": 3}]

    class Connection:
        def execute(self, statement, parameters):
            assert "LIMIT %(fetch_limit)s" in statement
            assert parameters["fetch_limit"] == 3
            return Cursor()

    with pytest.raises(data.DashboardError, match="limit"):
        data.rows(Connection(), "SELECT 1", limit=2)


def test_installed_launcher_uses_packaged_theme_from_any_working_directory(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from wroclaw_transit_analytics.dashboard import launcher

    calls = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs)) or SimpleNamespace(returncode=0),
    )
    assert launcher.launch(port=8504) == 0
    command, options = calls[0]
    assert "--server.port=8504" in command
    theme = options["cwd"] / ".streamlit" / "config.toml"
    assert theme.is_file()
    assert "primaryColor" in theme.read_text(encoding="utf-8")
    assert Path.cwd() == tmp_path
