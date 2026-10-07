"""Exercise HTTP streaming and real files through MockTransport."""

import hashlib
from pathlib import Path

import httpx
import pytest

from wroclaw_transit_analytics.gtfs.config import Limits
from wroclaw_transit_analytics.gtfs.downloader import download
from wroclaw_transit_analytics.gtfs.exceptions import DownloadError, StorageError

from .conftest import URL


class Chunks(httpx.SyncByteStream):
    def __init__(self, chunks: list[bytes], error: Exception | None = None):
        self.chunks = chunks
        self.error = error
        self.closed = False

    def __iter__(self):
        yield from self.chunks
        if self.error:
            raise self.error

    def close(self) -> None:
        self.closed = True


def test_stream_size_hash_and_resource_ownership(tmp_path: Path, feed: bytes) -> None:
    stream = Chunks([feed[:31], feed[31:]])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Accept-Encoding"] == "identity"
        assert request.extensions["timeout"]["connect"] == 10
        assert request.extensions["timeout"]["read"] == 60
        return httpx.Response(
            200, stream=stream, headers={"Content-Type": "application/octet-stream"}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = download(URL, tmp_path / "feed.zip", Limits(), client=client)
        assert not client.is_closed
        assert stream.closed
    assert result.size_bytes == len(feed)
    assert result.sha256 == hashlib.sha256(feed).hexdigest()
    assert (tmp_path / "feed.zip").read_bytes() == feed
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("status", [404, 500, 206])
def test_http_status(tmp_path: Path, status: int) -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status))) as client:
        with pytest.raises(DownloadError, match=str(status)):
            download(URL, tmp_path / "feed.zip", Limits(), client=client)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("error", [httpx.ReadTimeout("timeout"), httpx.ReadError("broken")])
def test_interrupted_stream_cleanup(tmp_path: Path, error: Exception) -> None:
    stream = Chunks([b"start"], error)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))
    ) as client:
        with pytest.raises(DownloadError):
            download(URL, tmp_path / "feed.zip", Limits(), client=client)
    assert stream.closed
    assert list(tmp_path.iterdir()) == []


def test_connect_timeout(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DownloadError):
            download(URL, tmp_path / "feed.zip", Limits(), client=client)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("chunks", "headers", "limit"),
    [
        ([], {}, 10),
        ([b"123", b"456"], {}, 5),
        ([b"abc"], {"Content-Length": "9"}, 10),
        ([b"abc"], {"Content-Length": "wrong"}, 10),
        ([b"abc"], {"Content-Encoding": "gzip", "Content-Length": "3"}, 10),
    ],
)
def test_rejected_response_cleanup(tmp_path: Path, chunks, headers, limit) -> None:
    stream = Chunks(chunks)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream, headers=headers))
    ) as client:
        with pytest.raises(DownloadError):
            download(URL, tmp_path / "feed.zip", Limits(max_download_bytes=limit), client=client)
    assert stream.closed
    assert list(tmp_path.iterdir()) == []


def test_allowed_redirect(tmp_path: Path, feed: bytes) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if len(requests) == 1:
            return httpx.Response(302, headers={"Location": "/archive"})
        return httpx.Response(200, stream=Chunks([feed]))

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        result = download(URL, tmp_path / "feed.zip", Limits(), client=client)
    assert result.final_url == "https://open-data.cui.wroclaw.pl/archive"
    assert len(requests) == 2


@pytest.mark.parametrize(
    "location", ["https://evil.example/feed", "http://open-data.cui.wroclaw.pl/feed"]
)
def test_forbidden_redirect_never_requested(tmp_path: Path, location: str) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(302, headers={"Location": location})

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        with pytest.raises(DownloadError, match="przekierowanie"):
            download(URL, tmp_path / "feed.zip", Limits(), client=client)
    assert requests == [URL]


def test_redirect_limit(tmp_path: Path) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"Location": URL})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DownloadError):
            download(URL, tmp_path / "feed.zip", Limits(), client=client)
    assert len(requests) == 4


@pytest.mark.parametrize("location", [None, "https://[invalid/"])
def test_missing_or_malformed_redirect(tmp_path: Path, location: str | None) -> None:
    headers = {} if location is None else {"Location": location}
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(302, headers=headers))
    ) as client:
        with pytest.raises(DownloadError):
            download(URL, tmp_path / "feed.zip", Limits(), client=client)
    assert list(tmp_path.iterdir()) == []


def test_archive_rename_failure_cleans_part(tmp_path: Path, monkeypatch) -> None:
    def fail_rename(*_args):
        raise OSError("rename denied")

    monkeypatch.setattr(Path, "rename", fail_rename)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Chunks([b"abc"])))
    ) as client:
        with pytest.raises(StorageError, match="rename denied"):
            download(URL, tmp_path / "feed.zip", Limits(), client=client)
    assert list(tmp_path.iterdir()) == []


def test_disk_write_failure(tmp_path: Path, monkeypatch) -> None:
    original_open = Path.open

    class BrokenFile:
        def __enter__(self):
            self.file = original_open(tmp_path / "feed.zip.part", "xb")
            return self

        def write(self, chunk):
            raise OSError("disk full")

        def __exit__(self, *args):
            self.file.close()

    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: BrokenFile())
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Chunks([b"abc"])))
    ) as client:
        with pytest.raises(StorageError, match="disk full"):
            download(URL, tmp_path / "feed.zip", Limits(), client=client)
    assert list(tmp_path.iterdir()) == []


def test_do_not_delete_foreign_part(tmp_path: Path) -> None:
    part = tmp_path / "feed.zip.part"
    part.write_bytes(b"belongs to another run")
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Chunks([b"abc"])))
    ) as client:
        with pytest.raises(StorageError):
            download(URL, tmp_path / "feed.zip", Limits(), client=client)
    assert part.read_bytes() == b"belongs to another run"
