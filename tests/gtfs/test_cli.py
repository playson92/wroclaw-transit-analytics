"""CLI results, error channels and help without HTTP."""

import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from wroclaw_transit_analytics.gtfs import cli, ingestion

from .conftest import URL
from .test_downloader import Chunks


def wire_client(monkeypatch, client):
    original_ingest = ingestion.ingest
    monkeypatch.setattr(
        cli, "ingest", lambda url, output_dir: original_ingest(url, output_dir, client=client)
    )


def test_cli_success(tmp_path: Path, feed: bytes, monkeypatch, capsys) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Chunks([feed])))
    ) as client:
        wire_client(monkeypatch, client)
        assert cli.main(["--url", URL, "--output-dir", str(tmp_path)]) == 0
    output = capsys.readouterr()
    assert "SHA-256:" in output.out and "manifest.json" in output.out and "feed.zip" in output.out
    assert output.err == ""


@pytest.mark.parametrize("body", [b"HTML", b""])
def test_cli_download_and_validation_failure(
    tmp_path: Path, body: bytes, monkeypatch, capsys
) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Chunks([body])))
    ) as client:
        wire_client(monkeypatch, client)
        assert cli.main(["--url", URL, "--output-dir", str(tmp_path)]) == 1
    output = capsys.readouterr()
    assert "Błąd:" in output.err and "Traceback" not in output.err
    assert output.out == ""
    manifests = list(tmp_path.rglob("manifest.json"))
    if body:
        assert (
            json.loads(manifests[0].read_text(encoding="utf-8"))["validation"]["status"] == "failed"
        )
    else:
        assert not manifests


def test_cli_missing_config(monkeypatch, capsys) -> None:
    monkeypatch.delenv("GTFS_URL", raising=False)
    assert cli.main([]) == 1
    assert "GTFS_URL" in capsys.readouterr().err


def test_cli_manifest_failure(tmp_path: Path, feed: bytes, monkeypatch, capsys) -> None:
    original_open = Path.open

    def fail_manifest(path, *args, **kwargs):
        if path.name == "manifest.json.part":
            raise OSError("cannot write manifest")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_manifest)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Chunks([feed])))
    ) as client:
        wire_client(monkeypatch, client)
        assert cli.main(["--url", URL, "--output-dir", str(tmp_path)]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "manifest" in output.err


def test_help_does_not_download(monkeypatch, capsys) -> None:
    monkeypatch.setattr(httpx.Client, "send", lambda *_args, **_kwargs: pytest.fail("network call"))
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    assert "--url" in capsys.readouterr().out


def test_module_help_and_import_without_network() -> None:
    code = (
        "import httpx,runpy,sys; "
        "httpx.Client.send=lambda *a,**k: (_ for _ in ()).throw(AssertionError('network')); "
        "import wroclaw_transit_analytics.gtfs; "
        "sys.argv=['gtfs','--help']; "
        "runpy.run_module('wroclaw_transit_analytics.gtfs',run_name='__main__')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    assert "--output-dir" in result.stdout
