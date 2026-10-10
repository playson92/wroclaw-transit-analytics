import json
from datetime import UTC, date, datetime
from importlib.resources import files

import pytest
from streamlit.testing.v1 import AppTest
from tests.dashboard.test_offline import fake_data as fake_data

from wroclaw_transit_analytics.explorer import data, positions, ui
from wroclaw_transit_analytics.explorer.map import deck, stop_markers


@pytest.fixture
def explorer_data(fake_data, monkeypatch):
    ui.refresh()

    def metadata(dataset):
        return {
            "dataset_id": dataset,
            "data_kind": "synthetic_demo",
            "source_sha256": "a" * 64,
            "provenance": {},
            "start_date": date(2026, 10, 1),
            "end_date": date(2026, 10, 7),
            "capabilities": {"quantitative_gold_supported": True},
        }

    def fetch(kind, dataset, day=None, route=None, variant=None, trip=None, stop=None):
        if kind == "routes":
            return [
                {
                    "route_id": r,
                    "route_short_name": "1",
                    "route_long_name": "Demo",
                    "route_type": t,
                    "agency_id": r,
                    "agency_name": r,
                }
                for r, t in (("bus", 3), ("tram", 0))
            ]
        if day in (date(2026, 11, 1), date(2026, 10, 6)):
            return []
        if kind == "active_routes":
            return [{"route_id": "bus"}, {"route_id": "tram"}]
        if kind == "variants":
            return [
                {
                    "variant_key": "v1",
                    "trip_headsign": "Centrum",
                    "direction_id": 0,
                    "shape_id": None,
                    "source_variant_id": None,
                    "trip_count": 1,
                    "first_seconds": 0,
                },
                {
                    "variant_key": "v2",
                    "trip_headsign": "Zajezdnia",
                    "direction_id": None,
                    "shape_id": None,
                    "source_variant_id": None,
                    "trip_count": 1,
                    "first_seconds": 0,
                },
            ]
        if kind == "trips":
            return [
                {
                    "trip_id": variant,
                    "start_seconds": 90600,
                    "end_seconds": None,
                    "trip_headsign": "Centrum",
                    "direction_id": 0,
                    "service_id": "s",
                    "shape_id": None,
                    "source_variant_id": None,
                }
            ]
        if kind == "geometry":
            return []
        if kind == "stops":
            return [
                {
                    "stop_id": s,
                    "stop_name": s,
                    "stop_sequence": i,
                    "stop_lat": 51.1 + i / 100,
                    "stop_lon": 17.1,
                    "arrival_seconds": None,
                    "departure_seconds": 90600 + i,
                    "pickup_type": 0,
                    "timepoint": 1,
                }
                for i, s in enumerate(("001", "NA", "001"))
            ]
        if kind == "departures":
            return [
                {
                    "trip_id": trip,
                    "trip_headsign": "Centrum",
                    "direction_id": 0,
                    "stop_sequence": 0,
                    "arrival_seconds": None,
                    "departure_seconds": 90600,
                    "pickup_type": 0,
                    "timepoint": 1,
                }
            ]
        raise AssertionError(kind)

    monkeypatch.setattr(data, "metadata", metadata)
    monkeypatch.setattr(data, "fetch", fetch)
    yield
    ui.refresh()


def app():
    return AppTest.from_file(
        str(files("wroclaw_transit_analytics.dashboard").joinpath("app.py")), default_timeout=15
    ).run()


def test_map_is_first_view_filters_variants_trips_and_no_shapes(explorer_data):
    at = app()
    assert not at.exception and not at.error
    assert at.radio(key="view").value == "Mapa i linie"
    assert at.selectbox(key="explorer_route").value == "bus"
    assert "agency_id=bus" in at.selectbox(key="explorer_route").options[0]
    assert any("geometrii shapes" in i.value for i in at.info)
    assert at.dataframe[0].value["stop_id"].tolist() == ["001", "NA", "001"]
    assert at.dataframe[0].value["Odjazd"].iloc[0] == "25:10:00"
    assert at.dataframe[0].value["Przyjazd"].iloc[0] == "Brak czasu"
    at.selectbox(key="explorer_variant").set_value("v2").run()
    assert at.selectbox(key="explorer_trip").value == "v2"
    at.selectbox(key="explorer_mode").set_value("Tramwaj").run()
    assert at.selectbox(key="explorer_route").value == "tram"
    assert at.selectbox(key="explorer_variant").value == "v1"
    at.selectbox(key="explorer_stop").set_value("NA").run()
    at.radio(key="explorer_detail").set_value("Przystanek").run()
    assert at.dataframe[0].value["Odjazd"].iloc[0] == "25:10:00"
    at.date_input[0].set_value(date(2026, 11, 1)).run()
    assert any("poza zakresem snapshotu" in i.value for i in at.info)
    at.selectbox(key="dataset").set_value("d2").run()
    assert at.date_input[0].value == date(2026, 10, 1)
    assert not at.error and not at.exception


def test_snapshot_resets_search_mode_and_dependents_but_view_navigation_preserves(explorer_data):
    at = app()
    at.date_input[0].set_value(date(2026, 10, 2)).run()
    at.selectbox(key="explorer_mode").set_value("Tramwaj").run()
    at.selectbox(key="explorer_variant").set_value("v2").run()
    at.selectbox(key="explorer_stop").set_value("NA").run()
    at.radio(key="explorer_detail").set_value("Przystanek").run()
    for view in ("Analityka", "Dane i jakość", "Mapa i linie"):
        at.radio(key="view").set_value(view).run()
        assert not at.error and not at.exception
    assert at.date_input[0].value == date(2026, 10, 2)
    assert at.selectbox(key="explorer_mode").value == "Tramwaj"
    assert at.selectbox(key="explorer_variant").value == "v2"
    assert at.selectbox(key="explorer_stop").value == "NA"
    assert at.radio(key="explorer_detail").value == "Przystanek"
    at.text_input(key="explorer_search").set_value("not in the next snapshot").run()
    assert any("Wyczyść wyszukiwanie" in i.value for i in at.info)
    at.selectbox(key="dataset").set_value("d2").run()
    assert at.date_input[0].value == date(2026, 10, 1)
    assert at.selectbox(key="explorer_mode").value == "Wszystkie"
    assert at.text_input(key="explorer_search").value == ""
    assert at.selectbox(key="explorer_route").value == "bus"
    assert at.selectbox(key="explorer_variant").value == "v1"
    assert at.selectbox(key="explorer_stop").value == "001"
    assert at.radio(key="explorer_detail").value == "Kurs"
    assert not at.toggle(key="explorer_vehicles").value
    at.selectbox(key="explorer_route").set_value("tram").run()
    assert at.date_input[0].value == date(2026, 10, 1)
    assert not at.error and not at.exception


def test_cleared_day_does_not_query_and_valid_day_without_services_stays_selected(
    explorer_data, monkeypatch
):
    original_fetch = data.fetch
    calls = []

    def fetch(kind, *args, **kwargs):
        calls.append(kind)
        return original_fetch(kind, *args, **kwargs)

    monkeypatch.setattr(data, "fetch", fetch)
    at = app()
    ui.refresh()
    calls.clear()
    at.date_input[0].set_value(None).run()
    assert any("Wybierz dzień usługi" in i.value for i in at.info)
    assert calls == ["routes"]
    assert not at.error and not at.exception
    at.date_input[0].set_value(date(2026, 10, 6)).run()
    assert any("Brak kursów" in i.value for i in at.info)
    assert at.date_input[0].value == date(2026, 10, 6)
    assert not at.error and not at.exception


@pytest.mark.parametrize(
    "key", ["explorer_route", "explorer_variant", "explorer_trip", "explorer_stop"]
)
def test_cleared_selection_has_instruction_instead_of_exception(explorer_data, key):
    at = app()
    at.selectbox(key=key).set_value(None).run()
    assert any("Wybierz" in i.value for i in at.info)
    assert not at.error and not at.exception


def test_cleared_snapshot_and_analysis_have_instructions(explorer_data):
    at = app()
    at.selectbox(key="dataset").set_value(None).run()
    assert any("Wybierz snapshot danych" in i.value for i in at.info)
    assert not at.error and not at.exception
    at.selectbox(key="dataset").set_value("d1").run()
    at.radio(key="view").set_value("Analityka").run()
    at.selectbox(key="analysis").set_value(None).run()
    assert any("Wybierz analizę" in i.value for i in at.info)
    assert not at.error and not at.exception


def test_snapshot_changes_in_analytics_reset_map_even_after_return_to_original(explorer_data):
    at = app()
    at.date_input[0].set_value(date(2026, 10, 2)).run()
    at.selectbox(key="explorer_mode").set_value("Tramwaj").run()
    at.radio(key="view").set_value("Analityka").run()
    at.selectbox(key="dataset").set_value("d2").run()
    at.selectbox(key="dataset").set_value("d1").run()
    at.radio(key="view").set_value("Mapa i linie").run()
    assert at.date_input[0].value == date(2026, 10, 1)
    assert at.selectbox(key="explorer_mode").value == "Wszystkie"
    assert at.selectbox(key="explorer_route").value == "bus"
    assert not at.error and not at.exception


@pytest.mark.parametrize(
    ("timepoint", "departure", "precision", "displayed_time"),
    [
        (0, 90600, "Przybliżony", "25:10:00"),
        (1, 90600, "Dokładny", "25:10:00"),
        (0, None, "Przybliżony", "Brak czasu"),
    ],
)
def test_stop_departure_table_displays_precision_and_missing_time(
    explorer_data, monkeypatch, timepoint, departure, precision, displayed_time
):
    original_fetch = data.fetch

    def fetch(kind, *args, **kwargs):
        records = original_fetch(kind, *args, **kwargs)
        if kind == "departures":
            return [dict(r, timepoint=timepoint, departure_seconds=departure) for r in records]
        return records

    monkeypatch.setattr(data, "fetch", fetch)
    at = app()
    at.radio(key="explorer_detail").set_value("Przystanek").run()
    assert not at.exception and not at.error
    assert any(h.value == "Odjazdy z wybranego przystanku" for h in at.subheader)
    assert len(at.dataframe) == 1
    displayed = at.dataframe[0].value
    assert displayed["Czas"].tolist() == [precision]
    assert displayed["Odjazd"].tolist() == [displayed_time]
    assert displayed["Przyjazd"].tolist() == ["Brak czasu"]
    assert "00:00:00" not in displayed["Odjazd"].tolist()


def test_position_failure_does_not_remove_trip_tables(explorer_data, monkeypatch):
    monkeypatch.setattr(
        positions,
        "snapshot",
        lambda: {
            "status": "unavailable",
            "fetched_at": datetime(2026, 10, 9, tzinfo=UTC),
            "next_fetch_at": datetime(2026, 10, 9, 1, tzinfo=UTC),
            "records": [],
            "terms_confirmed": False,
        },
    )
    at = app()
    at.toggle(key="explorer_vehicles").set_value(True).run()
    assert not at.error and not at.exception
    assert len(at.dataframe) == 1
    at.radio(key="explorer_detail").set_value("Pojazdy").run()
    assert any("niedostępne" in w.value for w in at.warning)
    at.radio(key="explorer_detail").set_value("Kurs").run()
    assert len(at.dataframe) == 1


def test_map_layer_keeps_timetable_visits_and_attribution():
    visits = [
        {"stop_id": "001", "stop_name": "A <script>", "stop_lat": 51.1, "stop_lon": 17.1},
        {"stop_id": "001", "stop_name": "A <script>", "stop_lat": 51.1, "stop_lon": 17.1},
        {"stop_id": "NA", "stop_name": "B", "stop_lat": None, "stop_lon": None},
    ]
    markers = stop_markers(visits, "001")
    assert len(markers) == 1 and len(visits) == 3
    assert markers[0]["color"] == [245, 158, 11]
    chart = deck(visits, [], "001")
    assert isinstance(chart.map_style, str) and chart.map_style.startswith("data:application/json,")
    assert "OpenStreetMap" in chart.to_json()
    assert chart._tooltip == {"text": "{label}"}  # GTFS is never rendered as tooltip HTML.
    assert deck(visits, [], "001", basemap=False).map_provider is None


def test_basemap_provider_change_recreates_chart_and_keeps_selected_stop(explorer_data):
    at = app()
    at.selectbox(key="explorer_stop").set_value("NA").run()
    with_basemap = at.get("deck_gl_json_chart")[0].proto
    assert json.loads(with_basemap.json)["mapStyle"].startswith("data:application/json,")
    at.toggle(key="explorer_basemap").set_value(False).run()
    without_basemap = at.get("deck_gl_json_chart")[0].proto
    assert without_basemap.id != with_basemap.id
    assert json.loads(without_basemap.json).get("mapStyle") is None
    assert json.loads(without_basemap.json).get("mapProvider") is None
    assert at.selectbox(key="explorer_stop").value == "NA"
    assert not at.error and not at.exception
