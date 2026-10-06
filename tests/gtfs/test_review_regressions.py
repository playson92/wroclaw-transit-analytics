"""Regression evidence for CSV emptiness, original ZIP names and BZIP2 errors."""

import errno
import hashlib
import io
import json
import struct
from pathlib import Path
from zipfile import ZIP_BZIP2, ZIP_DEFLATED, ZIP_STORED, ZipFile

import httpx
import pytest

from wroclaw_transit_analytics.gtfs.config import Limits
from wroclaw_transit_analytics.gtfs.exceptions import StorageError
from wroclaw_transit_analytics.gtfs.ingestion import ingest
from wroclaw_transit_analytics.gtfs.validation import validate_archive

from .conftest import URL, zip_bytes
from .test_cli import wire_client
from .test_downloader import Chunks

CORE = ["agency.txt", "stops.txt", "routes.txt", "trips.txt", "stop_times.txt"]


def empty_row(field_count: int, style: str) -> bytes:
    field = {"commas": "", "quoted": '""', "spaces": '" "'}[style]
    return (",".join([field] * field_count) + "\n").encode()


def replace_data_with_empty(files: dict[str, bytes], name: str, style: str) -> None:
    header = files[name].splitlines()[0]
    files[name] = header + b"\n" + empty_row(header.count(b",") + 1, style)


def compressed_feed(files: dict[str, bytes], compression: int) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=compression) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def damaged_bzip2(files: dict[str, bytes]) -> bytes:
    data = bytearray(compressed_feed(files, ZIP_BZIP2))
    assert data[:4] == b"PK\x03\x04"
    name_length, extra_length = struct.unpack_from("<HH", data, 26)
    payload = 30 + name_length + extra_length
    assert data[payload : payload + 3] == b"BZh"
    data[payload] ^= 1
    return bytes(data)


@pytest.mark.parametrize("name", CORE)
@pytest.mark.parametrize("style", ["commas", "quoted", "spaces"])
def test_r1_empty_csv_fields_are_not_data(tmp_path: Path, feed_files, name, style) -> None:
    replace_data_with_empty(feed_files, name, style)
    path = tmp_path / "feed.zip"
    path.write_bytes(zip_bytes(feed_files))
    result = validate_archive(path)
    assert result.status == "failed"
    assert any(issue.code == "empty_table" and issue.file == name for issue in result.issues)


@pytest.mark.parametrize("calendar", ["calendar.txt", "calendar_dates.txt"])
@pytest.mark.parametrize("style", ["commas", "quoted", "spaces"])
def test_r1_only_calendar_with_empty_fields(tmp_path: Path, feed_files, calendar, style) -> None:
    if calendar == "calendar_dates.txt":
        del feed_files["calendar.txt"]
        feed_files[calendar] = b"service_id,date,exception_type\nc,20260101,1\n"
    replace_data_with_empty(feed_files, calendar, style)
    path = tmp_path / "feed.zip"
    path.write_bytes(zip_bytes(feed_files))
    result = validate_archive(path)
    assert result.status == "failed"
    assert any(issue.code == "empty_calendar" for issue in result.issues)


@pytest.mark.parametrize("style", ["commas", "quoted", "spaces"])
@pytest.mark.parametrize("bom_crlf", [False, True])
def test_r1_empty_rows_before_quoted_data_are_allowed(
    tmp_path: Path, feed_files, style, bom_crlf
) -> None:
    header = feed_files["stops.txt"].splitlines()[0]
    content = header + b"\n" + empty_row(4, style) + b's,"Stop, with\nnewline",51,17\n'
    if bom_crlf:
        content = b"\xef\xbb\xbf" + content.replace(b"\n", b"\r\n")
    feed_files["stops.txt"] = content
    path = tmp_path / "feed.zip"
    path.write_bytes(zip_bytes(feed_files))
    assert validate_archive(path).status == "passed"


@pytest.mark.parametrize("style", ["commas", "quoted", "spaces"])
def test_r1_empty_dates_with_populated_calendar_allowed(tmp_path: Path, feed_files, style) -> None:
    feed_files["calendar_dates.txt"] = b"service_id,date,exception_type\n" + empty_row(3, style)
    path = tmp_path / "feed.zip"
    path.write_bytes(zip_bytes(feed_files))
    assert validate_archive(path).status == "passed"


def test_r1_ingestion_manifest_failed_for_empty_fields(tmp_path: Path, feed_files) -> None:
    replace_data_with_empty(feed_files, "stops.txt", "commas")
    body = zip_bytes(feed_files)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Chunks([body])))
    ) as client:
        result = ingest(URL, tmp_path, client=client)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["validation"]["status"] == "failed"
    assert any(
        issue["code"] == "empty_table" and issue["file"] == "stops.txt"
        for issue in manifest["validation"]["issues"]
    )
    assert result.archive_path.read_bytes() == body


def test_r2_nul_in_original_zip_name_rejected_before_content(
    tmp_path: Path, feed_files, monkeypatch
) -> None:
    feed_files["stops.txtXsuffix"] = feed_files.pop("stops.txt")
    body = zip_bytes(feed_files)
    assert body.count(b"stops.txtXsuffix") == 2
    body = body.replace(b"stops.txtXsuffix", b"stops.txt\x00suffix")
    path = tmp_path / "feed.zip"
    path.write_bytes(body)
    with ZipFile(path) as archive:
        member = next(info for info in archive.infolist() if info.filename == "stops.txt")
        assert member.orig_filename == "stops.txt\x00suffix"

    def forbidden_open(*_args, **_kwargs):
        pytest.fail("No member may be opened before rejecting the original unsafe name")

    monkeypatch.setattr(ZipFile, "open", forbidden_open)
    result = validate_archive(path)
    assert result.status == "failed"
    assert any(issue.code == "unsafe_path" for issue in result.issues)
    assert path.read_bytes() == body


def test_r3_bzip2_corruption_preserved_with_failed_manifest(tmp_path: Path, feed_files) -> None:
    body = damaged_bzip2(feed_files)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Chunks([body])))
    ) as client:
        result = ingest(URL, tmp_path, client=client)
    assert result.archive_path.read_bytes() == body
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["validation"]["status"] == "failed"
    assert any(
        issue["code"] == "corrupt_member" and issue["file"] == "agency.txt"
        for issue in manifest["validation"]["issues"]
    )
    assert manifest["sha256"] == hashlib.sha256(body).hexdigest()


@pytest.mark.parametrize("compression", [ZIP_STORED, ZIP_DEFLATED, ZIP_BZIP2])
def test_correct_feed_all_supported_compressions(tmp_path: Path, feed_files, compression) -> None:
    path = tmp_path / "feed.zip"
    path.write_bytes(compressed_feed(feed_files, compression))
    assert validate_archive(path).status == "passed"


@pytest.mark.parametrize(
    "error",
    [
        OSError(errno.EIO, "read failed"),
        PermissionError(errno.EACCES, "denied"),
        PermissionError("denied"),
        OSError("another read failure"),
    ],
)
def test_r3_real_read_failure_is_storage_error(
    tmp_path: Path, feed_files, monkeypatch, error
) -> None:
    path = tmp_path / "feed.zip"
    path.write_bytes(compressed_feed(feed_files, ZIP_BZIP2))
    original_open = ZipFile.open

    class BrokenRead:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.stream.close()

        def readline(self, _size):
            raise error

    monkeypatch.setattr(
        ZipFile,
        "open",
        lambda archive, *args, **kwargs: BrokenRead(original_open(archive, *args, **kwargs)),
    )
    with pytest.raises(StorageError) as caught:
        validate_archive(path)
    assert caught.value.__cause__ is error


@pytest.mark.parametrize("problem", ["empty_csv_fields", "damaged_bzip2"])
def test_cli_failed_validation_has_manifest_and_no_traceback(
    tmp_path: Path, feed_files, monkeypatch, capsys, problem
) -> None:
    from wroclaw_transit_analytics.gtfs import cli

    if problem == "empty_csv_fields":
        replace_data_with_empty(feed_files, "stops.txt", "commas")
        body = zip_bytes(feed_files)
    else:
        body = damaged_bzip2(feed_files)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Chunks([body])))
    ) as client:
        wire_client(monkeypatch, client)
        assert cli.main(["--url", URL, "--output-dir", str(tmp_path)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "Traceback" not in output.err
    manifests = list(tmp_path.rglob("manifest.json"))
    assert len(manifests) == 1
    assert json.loads(manifests[0].read_text(encoding="utf-8"))["validation"]["status"] == "failed"


@pytest.mark.parametrize("multiline", [False, True])
def test_r1_inspected_record_has_bounded_size(tmp_path: Path, feed_files, multiline) -> None:
    header = feed_files["stops.txt"].splitlines()[0] + b"\n"
    record = b's,"' + (b" \n" * 40 if multiline else b"x" * 80) + b'",51,17\n'
    feed_files["stops.txt"] = header + record
    path = tmp_path / "feed.zip"
    path.write_bytes(zip_bytes(feed_files))
    result = validate_archive(path, Limits(max_record_bytes=64))
    assert result.status == "failed"
    assert any(
        issue.code == "record_limit" and issue.file == "stops.txt" for issue in result.issues
    )


@pytest.mark.parametrize("record_bytes", [64, 65])
def test_r1_record_limit_boundary(tmp_path: Path, feed_files, record_bytes) -> None:
    prefix, suffix = b"s,", b",51,17\n"
    record = prefix + b"x" * (record_bytes - len(prefix) - len(suffix)) + suffix
    assert len(record) == record_bytes
    feed_files["stops.txt"] = feed_files["stops.txt"].splitlines()[0] + b"\n" + record
    path = tmp_path / "feed.zip"
    path.write_bytes(zip_bytes(feed_files))
    result = validate_archive(path, Limits(max_record_bytes=64))
    assert result.status == ("passed" if record_bytes == 64 else "failed")


def test_r1_record_budget_resets_and_reads_are_bounded(
    tmp_path: Path, feed_files, monkeypatch
) -> None:
    header, data = feed_files["stops.txt"].split(b"\n", 1)
    feed_files["stops.txt"] = header + b"\n" + b",,,\n" * 100 + data
    path = tmp_path / "feed.zip"
    path.write_bytes(zip_bytes(feed_files))
    original_open = ZipFile.open
    reads = []

    class BoundedStream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.stream.close()

        def readline(self, size):
            assert 0 < size <= 65537
            reads.append(size)
            return self.stream.readline(size)

        def read(self, size):
            assert 0 < size <= 65536
            return self.stream.read(size)

    monkeypatch.setattr(
        ZipFile,
        "open",
        lambda archive, *args, **kwargs: BoundedStream(original_open(archive, *args, **kwargs)),
    )
    assert validate_archive(path, Limits(max_record_bytes=64)).status == "passed"
    assert len(reads) > 100


@pytest.mark.parametrize("compression", [ZIP_STORED, ZIP_DEFLATED, ZIP_BZIP2])
def test_r1_crc_of_tail_checked_after_finding_data(tmp_path: Path, feed_files, compression) -> None:
    # First data is near the start; CRC can only be verified after the later chunks.
    feed_files["stops.txt"] += b"s,Stop,51,17\n" * 6000 + b"s,unique_tail,51,17\n"
    body = bytearray(compressed_feed(feed_files, compression))
    path = tmp_path / "feed.zip"
    path.write_bytes(body)
    central_start = body.index(b"PK\x01\x02")
    central = body.index(b"stops.txt", central_start) - 46
    assert body[central : central + 4] == b"PK\x01\x02"
    # Alter expected CRC in the central directory, retaining valid decompression.
    body[central + 16] ^= 1
    path.write_bytes(body)
    result = validate_archive(path)
    assert any(
        issue.code == "corrupt_member" and issue.file == "stops.txt" for issue in result.issues
    )


@pytest.mark.parametrize(
    "error", [OSError(errno.EIO, "tail read failed"), PermissionError(errno.EACCES, "tail denied")]
)
def test_r3_io_failure_during_tail_read_is_storage_error(
    tmp_path: Path, feed_files, monkeypatch, error
) -> None:
    path = tmp_path / "feed.zip"
    path.write_bytes(compressed_feed(feed_files, ZIP_BZIP2))
    original_open = ZipFile.open

    class BrokenTail:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.stream.close()

        def readline(self, size):
            return self.stream.readline(size)

        def read(self, _size):
            raise error

    monkeypatch.setattr(
        ZipFile,
        "open",
        lambda archive, *args, **kwargs: BrokenTail(original_open(archive, *args, **kwargs)),
    )
    with pytest.raises(StorageError) as caught:
        validate_archive(path)
    assert caught.value.__cause__ is error


def test_r3_errno_less_oserror_for_stored_zip_is_storage(
    tmp_path: Path, feed_files, monkeypatch
) -> None:
    path = tmp_path / "feed.zip"
    path.write_bytes(zip_bytes(feed_files))
    error = OSError("Invalid data stream")

    def broken_open(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(ZipFile, "open", broken_open)
    with pytest.raises(StorageError) as caught:
        validate_archive(path)
    assert caught.value.__cause__ is error


@pytest.mark.parametrize("calendar", ["calendar.txt", "calendar_dates.txt"])
@pytest.mark.parametrize("style", ["commas", "quoted", "spaces"])
def test_r1_calendar_empty_records_before_data_allowed(
    tmp_path: Path, feed_files, calendar, style
) -> None:
    if calendar == "calendar_dates.txt":
        del feed_files["calendar.txt"]
        feed_files[calendar] = b"service_id,date,exception_type\nc,20260101,1\n"
    header, data = feed_files[calendar].split(b"\n", 1)
    content = header + b"\n" + empty_row(header.count(b",") + 1, style) + data
    feed_files[calendar] = b"\xef\xbb\xbf" + content.replace(b"\n", b"\r\n")
    path = tmp_path / "feed.zip"
    path.write_bytes(zip_bytes(feed_files))
    result = validate_archive(path)
    assert result.status == "passed"
    assert result.issues == ()


@pytest.mark.parametrize("compression", [ZIP_STORED, ZIP_DEFLATED, ZIP_BZIP2])
def test_valid_feed_ingestion_for_supported_compressions(
    tmp_path: Path, feed_files, compression
) -> None:
    body = compressed_feed(feed_files, compression)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Chunks([body])))
    ) as client:
        result = ingest(URL, tmp_path, client=client)
    assert result.validation.status == "passed"
    assert result.validation.issues == ()
    assert result.archive_path.read_bytes() == body
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 1
    assert manifest["validation"]["status"] == "passed"
    assert manifest["validation"]["issues"] == []
    assert manifest["sha256"] == hashlib.sha256(body).hexdigest()
    assert manifest["size_bytes"] == len(body)


def test_r2_cli_rejects_original_nul_name_with_failed_manifest(
    tmp_path: Path, feed_files, monkeypatch, capsys
) -> None:
    from wroclaw_transit_analytics.gtfs import cli

    feed_files["stops.txtXsuffix"] = feed_files.pop("stops.txt")
    body = zip_bytes(feed_files)
    assert body.count(b"stops.txtXsuffix") == 2
    body = body.replace(b"stops.txtXsuffix", b"stops.txt\x00suffix")
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Chunks([body])))
    ) as client:
        wire_client(monkeypatch, client)
        assert cli.main(["--url", URL, "--output-dir", str(tmp_path)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "unsafe_path" in output.err
    assert "Traceback" not in output.err
    manifests = list(tmp_path.rglob("manifest.json"))
    assert len(manifests) == 1
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["validation"]["status"] == "failed"
    assert any(
        issue["code"] == "unsafe_path" and issue["file"] == "stops.txt\x00suffix"
        for issue in manifest["validation"]["issues"]
    )
    assert manifests[0].with_name("feed.zip").read_bytes() == body
