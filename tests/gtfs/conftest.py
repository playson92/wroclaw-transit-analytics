"""Tiny synthetic feeds; no network or municipal data in tests."""

import io
from zipfile import ZIP_STORED, ZipFile

import pytest

URL = "https://open-data.cui.wroclaw.pl/hdb/download/test/"


def zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_STORED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


@pytest.fixture
def feed_files() -> dict[str, bytes]:
    return {
        "agency.txt": b"agency_name,agency_url,agency_timezone\nMPK,https://example.org,Europe/Warsaw\n",
        "stops.txt": b"stop_id,stop_name,stop_lat,stop_lon\ns,Stop,51,17\n",
        "routes.txt": b"route_id,route_type,route_short_name\nr,3,1\n",
        "trips.txt": b"route_id,service_id,trip_id\nr,c,t\n",
        "stop_times.txt": b"trip_id,arrival_time,departure_time,stop_id,stop_sequence\nt,25:10:00,25:10:00,s,1\n",
        "calendar.txt": b"service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nc,1,1,1,1,1,0,0,20260101,20261231\n",
    }


@pytest.fixture
def feed(feed_files: dict[str, bytes]) -> bytes:
    return zip_bytes(feed_files)
