"""CUI JSON observations, never GTFS-RT or inferred trip assignments."""

import json
import math
import threading
import time
from collections import Counter
from datetime import UTC, datetime, timedelta

import httpx

SOURCE_URL = "https://open-data.cui.wroclaw.pl/hdb/db/14?download=json"
METADATA_URL = "https://open-data.cui.wroclaw.pl/hdb/metadane/json/51/"
MIN_INTERVAL = 3600  # Export says hourly, catalogue says ten minutes: choose the slower rate.
MAX_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 10000
MAX_AGE_SECONDS = 600
_lock = threading.Lock()
_cached = None
_last_attempt = None


def _json_response(client, url):
    # Fixed official HTTPS URLs, no redirect to a different provider, bounded decoded bytes.
    with client.stream("GET", url) as response:
        response.raise_for_status()
        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > MAX_BYTES:
                raise ValueError("Przekroczono limit eksportu.")
        return json.loads(body)


def download():
    fetched = datetime.now(UTC)
    try:
        with httpx.Client(
            timeout=10,
            follow_redirects=False,
            headers={
                "User-Agent": "WroclawTransitAnalytics/0.1 (+https://github.com/playson92/wroclaw-transit-analytics)"
            },
        ) as client:
            payload = _json_response(client, SOURCE_URL)
            metadata = _json_response(client, METADATA_URL)
        if not isinstance(payload, dict) or not isinstance(payload.get("dane"), list):
            raise ValueError("Nieobsługiwany format eksportu.")
        if len(payload["dane"]) > MAX_RECORDS or not isinstance(metadata, dict):
            raise ValueError("Niepoprawne metadane lub liczba rekordów.")
        consistent = payload.get("meta", {}).get("tytul") == metadata.get("tytul")
        return {
            "status": "available",
            "fetched_at": fetched,
            "records": payload["dane"],
            "metadata": metadata,
            "metadata_consistent": consistent,
            "terms_confirmed": consistent and metadata.get("licencja") == "CC0 1.0",
        }
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return {
            "status": "unavailable",
            "fetched_at": fetched,
            "records": [],
            "metadata": {},
            "metadata_consistent": False,
            "terms_confirmed": False,
        }


def snapshot():
    """A manual refresh may reuse cache; no session can bypass the shared request cooldown."""
    global _cached, _last_attempt
    with _lock:
        now = time.monotonic()
        if _last_attempt is None or now - _last_attempt >= MIN_INTERVAL:
            _cached = download()
            _last_attempt = time.monotonic()
        return {**_cached, "next_fetch_at": _cached["fetched_at"] + timedelta(seconds=MIN_INTERVAL)}


def normalize(source, now=None):
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("Czas weryfikacji wymaga strefy.")
    records = source["records"]
    identifiers = Counter(str(r.get("Nr_Boczny")) for r in records if isinstance(r, dict))
    output = []
    skipped = 0
    for index, row in enumerate(records):
        if not isinstance(row, dict):
            skipped += 1
            continue
        try:
            lat = float(str(row.get("Ostatnia_Pozycja_Szerokosc")).replace(",", "."))
            lon = float(str(row.get("Ostatnia_Pozycja_Dlugosc")).replace(",", "."))
            if (
                not math.isfinite(lat)
                or not math.isfinite(lon)
                or not -90 <= lat <= 90
                or not -180 <= lon <= 180
                or (lat == 0 and lon == 0)
            ):
                raise ValueError("Niepoprawne współrzędne.")
        except (ValueError, TypeError):
            skipped += 1
            continue
        raw_time = row.get("Data_Aktualizacji")
        age = None
        state = "Niepotwierdzony czas / strefa"
        try:
            measured = datetime.fromisoformat(raw_time)
            if measured.tzinfo is not None:
                age = (now - measured.astimezone(UTC)).total_seconds()
                if age < -60:
                    state = "Czas w przyszłości"
                elif age > MAX_AGE_SECONDS:
                    state = "Stara obserwacja"
                elif source.get("terms_confirmed"):
                    state = "Niedawna obserwacja"
                else:
                    state = "Warunki źródła niepotwierdzone"
        except (ValueError, TypeError):
            pass
        vehicle = str(row.get("Nr_Boczny")) if row.get("Nr_Boczny") is not None else "Niepodany"
        line = str(row.get("Nazwa_Linii") or "Niepodana")
        output.append(
            {
                "observation_id": str(index),
                "line": line,
                "vehicle_id": vehicle,
                "duplicate_id": identifiers.get(vehicle, 0) > 1,
                "latitude": lat,
                "longitude": lon,
                "measured_at": raw_time or "Niepodany",
                "age_seconds": age,
                "state": state,
                "label": f"Linia {line} · pojazd {vehicle}\n{raw_time or 'Brak czasu'}\n{state}",
            }
        )
    return {
        **source,
        "positions": output,
        "skipped": skipped,
        "received": len(records),
        "unconfirmed_time": sum(p["age_seconds"] is None for p in output),
        "duplicate_ids": {k: v for k, v in identifiers.items() if v > 1},
    }
