"""Real local persistence and validation with only HTTP replaced."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from wroclaw_transit_analytics.gtfs.exceptions import StorageError
from wroclaw_transit_analytics.gtfs.ingestion import ingest

from .conftest import URL
from .test_downloader import Chunks


def test_full_flow_and_independent_runs(tmp_path: Path, feed: bytes) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                stream=Chunks([feed]),
                headers={"Content-Type": "application/octet-stream", "ETag": '"test"'},
            )
        )
    ) as client:
        first = ingest(URL, tmp_path, client=client)
        second = ingest(URL, tmp_path, client=client)
    assert first.archive_path != second.archive_path
    for result in (first, second):
        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        assert manifest["manifest_version"] == 1
        assert manifest["validation"]["status"] == "passed"
        assert manifest["validation"]["profile"] == "wroclaw-static-mvp-v1"
        assert manifest["validation"]["issues"] == []
        assert manifest["sha256"] == hashlib.sha256(result.archive_path.read_bytes()).hexdigest()
        assert result.archive_path.read_bytes() == feed
        assert manifest["size_bytes"] == len(feed)
        assert manifest["requested_url"] == manifest["final_url"] == URL
        assert manifest["etag"] == '"test"'
        assert manifest["last_modified"] is None
        assert datetime.fromisoformat(manifest["downloaded_at"]).utcoffset().total_seconds() == 0
        assert result.manifest_path.parent / manifest["archive_path"] == result.archive_path
    assert not list(tmp_path.rglob("*.part"))


@pytest.mark.parametrize("body", [b"<html>portal error</html>", b"PKbroken"])
def test_failed_feed_is_preserved_with_manifest(tmp_path: Path, body: bytes) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Chunks([body])))
    ) as client:
        result = ingest(URL, tmp_path, client=client)
    assert result.archive_path.read_bytes() == body
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["validation"]["status"] == "failed"
    assert manifest["validation"]["issues"][0]["code"] == "invalid_zip"


def test_manifest_rename_failure(tmp_path: Path, feed: bytes, monkeypatch) -> None:
    original_rename = Path.rename

    def rename(path, target):
        if path.name == "manifest.json.part":
            raise OSError("manifest disk error")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", rename)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Chunks([feed])))
    ) as client:
        with pytest.raises(StorageError, match="manifest disk error"):
            ingest(URL, tmp_path, client=client)
    assert len(list(tmp_path.rglob("feed.zip"))) == 1
    assert not list(tmp_path.rglob("manifest.json"))
    assert not list(tmp_path.rglob("*.part"))
