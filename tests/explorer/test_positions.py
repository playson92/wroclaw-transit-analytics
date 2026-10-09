from datetime import UTC, datetime, timedelta

import httpx
import pytest

from wroclaw_transit_analytics.explorer import positions

NOW = datetime(2026, 10, 9, 12, tzinfo=UTC)


def row(time="2026-10-09T14:00:00", lat=51.1, lon=17.1, vehicle="0001"):
    return {
        "Data_Aktualizacji": time,
        "Ostatnia_Pozycja_Szerokosc": lat,
        "Ostatnia_Pozycja_Dlugosc": lon,
        "Nr_Boczny": vehicle,
        "Nazwa_Linii": "A",
    }


def test_unknown_timezone_stale_future_duplicates_and_bad_coordinates():
    source = {
        "records": [
            row(),
            row(vehicle="0001"),
            row(time=(NOW - timedelta(hours=1)).isoformat()),
            row(time=(NOW + timedelta(hours=1)).isoformat()),
            row(lat=900),
            row(lon="NaN"),
            row(lat=0, lon=0),
            row(lat="51,1", lon="17,1"),
        ],
        "terms_confirmed": True,
    }
    result = positions.normalize(source, NOW)
    assert result["skipped"] == 3
    assert result["duplicate_ids"]["0001"] == 8
    assert result["positions"][0]["age_seconds"] is None
    assert "strefa" in result["positions"][0]["state"]
    assert result["positions"][2]["state"] == "Stara obserwacja"
    assert result["positions"][3]["state"] == "Czas w przyszłości"
    assert all("trip_id" not in r for r in result["positions"])


def test_only_explicit_offsets_get_age_and_terms_must_match():
    record = row(time="2026-10-09T14:00:00+02:00")
    result = positions.normalize({"records": [record], "terms_confirmed": True}, NOW)
    assert result["positions"][0]["age_seconds"] == 0
    assert result["positions"][0]["state"] == "Niedawna obserwacja"
    unknown = positions.normalize({"records": [record], "terms_confirmed": False}, NOW)
    assert unknown["positions"][0]["state"] == "Warunki źródła niepotwierdzone"
    with pytest.raises(ValueError):
        positions.normalize({"records": []}, datetime(2026, 10, 9))


def test_source_failure_is_cached_and_manual_refresh_cannot_bypass_limit(monkeypatch):
    attempts = []
    monkeypatch.setattr(positions, "_cached", None)
    monkeypatch.setattr(positions, "_last_attempt", None)
    clock = [0]
    monkeypatch.setattr(positions.time, "monotonic", lambda: clock[0])

    def download():
        attempts.append(True)
        return {"status": "unavailable", "fetched_at": NOW, "records": []}

    monkeypatch.setattr(positions, "download", download)
    assert positions.snapshot()["status"] == "unavailable"
    positions.snapshot()
    assert len(attempts) == 1
    clock[0] = positions.MIN_INTERVAL
    positions.snapshot()
    assert len(attempts) == 2


@pytest.mark.parametrize("mode", ["good", "wrong_metadata", "error", "oversize"])
def test_export_contract_and_bounded_download(monkeypatch, mode):
    def respond(request):
        if mode == "error":
            return httpx.Response(503)
        if mode == "oversize":
            return httpx.Response(200, content=b"x" * (positions.MAX_BYTES + 1))
        if str(request.url) == positions.METADATA_URL:
            return httpx.Response(200, json={"tytul": "positions", "licencja": "CC0 1.0"})
        return httpx.Response(
            200,
            json={
                "meta": {"tytul": "other" if mode == "wrong_metadata" else "positions"},
                "dane": [row()],
            },
        )

    original = httpx.Client
    monkeypatch.setattr(
        positions.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    result = positions.download()
    assert result["status"] == ("unavailable" if mode in ("error", "oversize") else "available")
    assert result["terms_confirmed"] == (mode == "good")
