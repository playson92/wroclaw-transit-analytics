"""Archive safety, bounded integrity reads and analytical profile headers."""

import io
import stat
import struct
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from wroclaw_transit_analytics.gtfs.config import DEFAULT_LIMITS, Limits
from wroclaw_transit_analytics.gtfs.validation import validate_archive

from .conftest import zip_bytes

DATES = b"service_id,date,exception_type\nc,20260101,1\n"


def check(tmp_path: Path, files: dict[str, bytes], limits: Limits = DEFAULT_LIMITS):
    path = tmp_path / "feed.zip"
    path.write_bytes(zip_bytes(files))
    return validate_archive(path, limits)


@pytest.mark.parametrize("calendar", ["regular", "dates", "both", "empty_dates"])
def test_valid_calendars(tmp_path: Path, feed_files, calendar) -> None:
    if calendar == "dates":
        del feed_files["calendar.txt"]
    if calendar in ("dates", "both", "empty_dates"):
        feed_files["calendar_dates.txt"] = (
            DATES if calendar != "empty_dates" else DATES.splitlines()[0] + b"\n"
        )
    assert check(tmp_path, feed_files).status == "passed"


def test_missing_calendars(tmp_path: Path, feed_files) -> None:
    del feed_files["calendar.txt"]
    assert "missing_calendar" in {i.code for i in check(tmp_path, feed_files).issues}


def test_missing_file_and_column(tmp_path: Path, feed_files) -> None:
    del feed_files["trips.txt"]
    feed_files["stops.txt"] = b"stop_id,stop_name,stop_lat\ns,Stop,51\n"
    issues = check(tmp_path, feed_files).issues
    assert any(i.code == "missing_file" and i.file == "trips.txt" for i in issues)
    assert any(i.code == "missing_columns" and "stop_lon" in i.description for i in issues)


def test_bom_crlf_and_quoted_csv(tmp_path: Path, feed_files) -> None:
    feed_files = {
        name: b"\xef\xbb\xbf" + content.replace(b"\n", b"\r\n")
        for name, content in feed_files.items()
    }
    feed_files["stops.txt"] = (
        b'\xef\xbb\xbf"stop_id",stop_name,stop_lat,stop_lon,"extra,quoted"\r\ns,Stop,51,17,x\r\n'
    )
    assert check(tmp_path, feed_files).status == "passed"


@pytest.mark.parametrize(
    "name", ["agency.txt", "stops.txt", "routes.txt", "trips.txt", "stop_times.txt"]
)
def test_empty_core(tmp_path: Path, feed_files, name) -> None:
    feed_files[name] = feed_files[name].splitlines()[0] + b"\n\r\n  \n"
    assert any(
        i.code == "empty_table" and i.file == name for i in check(tmp_path, feed_files).issues
    )


def test_empty_calendar(tmp_path: Path, feed_files) -> None:
    feed_files["calendar.txt"] = feed_files["calendar.txt"].splitlines()[0] + b"\n"
    assert "empty_calendar" in {i.code for i in check(tmp_path, feed_files).issues}


@pytest.mark.parametrize(
    ("header", "code"),
    [
        (b"stop_id,stop_name,stop_lat,stop_lon,stop_id", "duplicate_column"),
        (b"stop_id,stop_name,stop_lat,stop_lon,", "empty_column"),
        (b"stop_id,stop_name,stop_lat,stop_lon,\xff", "invalid_header"),
        (b'"unterminated', "invalid_header"),
    ],
)
def test_bad_headers(tmp_path: Path, feed_files, header, code) -> None:
    feed_files["stops.txt"] = header + b"\ns,Stop,51,17\n"
    assert code in {i.code for i in check(tmp_path, feed_files).issues}


def test_routes_alternative_name(tmp_path: Path, feed_files) -> None:
    feed_files["routes.txt"] = b"route_id,route_type,route_long_name\nr,3,Long\n"
    assert check(tmp_path, feed_files).status == "passed"
    feed_files["routes.txt"] = b"route_id,route_type\nr,3\n"
    assert "missing_route_name" in {i.code for i in check(tmp_path, feed_files).issues}


@pytest.mark.parametrize(
    "name", ["../x", "/x", "folder/../../x", "..\\x", "C:\\x", "C:x", "\\server\\share\\x"]
)
def test_unsafe_paths_before_content_reads(tmp_path: Path, feed_files, name, monkeypatch) -> None:
    feed_files[name] = b"unsafe"
    path = tmp_path / "feed.zip"
    path.write_bytes(zip_bytes(feed_files))
    monkeypatch.setattr(ZipFile, "open", lambda *_args: pytest.fail("member must not be opened"))
    assert "unsafe_path" in {i.code for i in validate_archive(path).issues}


def test_nested_files_are_not_root_files(tmp_path: Path, feed_files) -> None:
    files = {"folder/" + name: content for name, content in feed_files.items()}
    assert {i.file for i in check(tmp_path, files).issues if i.code == "missing_file"} == {
        "agency.txt",
        "stops.txt",
        "routes.txt",
        "trips.txt",
        "stop_times.txt",
    }


def test_optional_files(tmp_path: Path, feed_files) -> None:
    feed_files.update(
        {"shapes.txt": b"anything", "transfers.txt": b"anything", "notes/info.txt": b"safe"}
    )
    assert check(tmp_path, feed_files).status == "passed"


@pytest.mark.parametrize("limit", [Limits(max_entries=1), Limits(max_uncompressed_bytes=10)])
def test_metadata_limits_before_reads(tmp_path: Path, feed_files, limit, monkeypatch) -> None:
    path = tmp_path / "feed.zip"
    path.write_bytes(zip_bytes(feed_files))
    monkeypatch.setattr(ZipFile, "open", lambda *_args: pytest.fail("member must not be opened"))
    assert validate_archive(path, limit).status == "failed"


def test_header_limit(tmp_path: Path, feed_files) -> None:
    assert "header_limit" in {
        i.code for i in check(tmp_path, feed_files, Limits(max_header_bytes=10)).issues
    }


def test_multiline_header_limit(tmp_path: Path, feed_files) -> None:
    feed_files["stops.txt"] = (
        b'"stop_id\n' + b"x\n" * 60 + b'",stop_name,stop_lat,stop_lon\nx,y,1,2\n'
    )
    assert "header_limit" in {
        i.code for i in check(tmp_path, feed_files, Limits(max_header_bytes=100)).issues
    }


@pytest.mark.parametrize("content", [None, b"", b"<html>not a zip</html>", b"PK\x03\x04broken"])
def test_invalid_archive(tmp_path: Path, content) -> None:
    path = tmp_path / "feed.zip"
    if content is not None:
        path.write_bytes(content)
    assert validate_archive(path).status == "failed"


def test_duplicate_entries(tmp_path: Path) -> None:
    path = tmp_path / "feed.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("agency.txt", "one")
        with pytest.warns(UserWarning):
            archive.writestr("agency.txt", "two")
    assert "duplicate_entry" in {i.code for i in validate_archive(path).issues}


def test_symlink(tmp_path: Path) -> None:
    path = tmp_path / "feed.zip"
    with ZipFile(path, "w") as archive:
        info = ZipInfo("link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "target")
    assert "symlink_entry" in {i.code for i in validate_archive(path).issues}


def test_encrypted_metadata(tmp_path: Path, feed: bytes, monkeypatch) -> None:
    path = tmp_path / "feed.zip"
    path.write_bytes(feed)
    data = bytearray(feed)
    central = data.index(b"PK\x01\x02")
    flags = struct.unpack_from("<H", data, central + 8)[0]
    struct.pack_into("<H", data, central + 8, flags | 1)
    path.write_bytes(data)
    monkeypatch.setattr(ZipFile, "open", lambda *_args: pytest.fail("member must not be opened"))
    assert "encrypted_entry" in {i.code for i in validate_archive(path).issues}


def test_crc_corruption(tmp_path: Path, feed: bytes) -> None:
    path = tmp_path / "feed.zip"
    data = bytearray(feed)
    index = data.index(b"MPK,https")
    data[index] ^= 1
    path.write_bytes(data)
    assert "corrupt_member" in {i.code for i in validate_archive(path).issues}


def test_optional_member_crc_checked(tmp_path: Path, feed_files) -> None:
    feed_files["optional.bin"] = b"unique optional payload"
    data = bytearray(zip_bytes(feed_files))
    data[data.index(b"unique optional payload")] ^= 1
    path = tmp_path / "feed.zip"
    path.write_bytes(data)
    assert any(
        i.code == "corrupt_member" and i.file == "optional.bin"
        for i in validate_archive(path).issues
    )


def test_actual_decompression_budget(tmp_path: Path, monkeypatch) -> None:
    # Simulate a stream exceeding the central directory declaration, without a huge archive.
    path = tmp_path / "feed.zip"
    path.write_bytes(zip_bytes({"optional.bin": b"x"}))
    monkeypatch.setattr(ZipFile, "open", lambda *_args: io.BytesIO(b"x" * 21))
    assert "uncompressed_limit" in {
        i.code for i in validate_archive(path, Limits(max_uncompressed_bytes=20)).issues
    }


def test_deflated_feed(tmp_path: Path, feed_files) -> None:
    path = tmp_path / "feed.zip"
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in feed_files.items():
            archive.writestr(name, content)
    assert validate_archive(path).status == "passed"


def test_corrupt_utf8_member_name(tmp_path: Path, feed: bytes) -> None:
    data = bytearray(feed)
    central = data.index(b"PK\x01\x02")
    flags = struct.unpack_from("<H", data, central + 8)[0]
    struct.pack_into("<H", data, central + 8, flags | 0x800)
    data[central + 46] = 0xFF
    path = tmp_path / "feed.zip"
    path.write_bytes(data)
    assert "invalid_zip" in {i.code for i in validate_archive(path).issues}
