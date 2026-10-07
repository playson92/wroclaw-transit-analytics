"""Actual Parquet/JSON corruption and portable identity, with no database."""

import json
import shutil
from pathlib import Path

import pytest

from wroclaw_transit_analytics.__main__ import main
from wroclaw_transit_analytics.database import DatabaseError
from wroclaw_transit_analytics.database import connection as configuration
from wroclaw_transit_analytics.database.verification import verified_silver
from wroclaw_transit_analytics.preparation import prepare
from wroclaw_transit_analytics.preparation.source import file_sha256
from wroclaw_transit_analytics.sample_data import write_sample_data


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_relocated_silver_and_batch_independent_fingerprint(tmp_path):
    raw = write_sample_data(tmp_path / "source").manifest_path
    first = prepare(raw, tmp_path / "one", batch_size=1).silver_manifest
    second = prepare(raw, tmp_path / "two", batch_size=100).silver_manifest
    with verified_silver(first, batch_size=3) as a, verified_silver(second, batch_size=7) as b:
        fingerprint = a.fingerprint
        assert fingerprint == b.fingerprint
        assert a.manifest["tables"]["stops"]["sha256"] != b.manifest["tables"]["stops"]["sha256"]
    moved = tmp_path / "portable"
    shutil.copytree(first.parent, moved)
    # No access to raw or bronze; historical absolute paths remain verbatim in the copy.
    shutil.rmtree(tmp_path / "source")
    shutil.rmtree(tmp_path / "one")
    with verified_silver(moved / "manifest.json") as verified:
        assert verified.fingerprint == fingerprint
        assert verified.manifest["tables"]["stop_times"]["row_count"] == 15


@pytest.mark.parametrize(
    "change",
    [
        "parquet",
        "quality",
        "logical",
        "count",
        "schema",
        "identity",
        "incomplete",
        "quality_dataset",
        "capabilities",
        "traversal",
    ],
)
def test_tampered_input_is_rejected(silver, change):
    manifest = read(silver)
    if change == "parquet":
        path = silver.parent / "stops.parquet"
        with path.open("r+b") as stream:
            stream.seek(20)
            stream.write(b"broken")
    elif change == "quality":
        with (silver.parent / "quality.json").open("ab") as stream:
            stream.write(b" ")
    elif change == "logical":
        manifest["tables"]["stop_times"]["content_sha256"] = "0" * 64
    elif change == "count":
        manifest["tables"]["stops"]["row_count"] += 1
    elif change == "schema":
        manifest["tables"]["routes"]["columns"][0]["type"] = "int64"
    elif change == "identity":
        manifest["dataset_id"] = "gtfs_" + "0" * 64
    elif change == "incomplete":
        del manifest["tables"]["calendar"]
    elif change == "quality_dataset":
        path = silver.parent / "quality.json"
        quality = read(path)
        quality["dataset_id"] = "different"
        write(path, quality)
        manifest["data_quality"]["sha256"] = file_sha256(path)
    elif change == "capabilities":
        manifest["capabilities"]["quantitative_gold_supported"] = False
    else:
        manifest["tables"]["stops"]["path"] = "../stops.parquet"
    write(silver, manifest)
    with pytest.raises(DatabaseError), verified_silver(silver):
        pass


def test_symlink_traversal_rejected(silver, tmp_path):
    link = tmp_path / "linked"
    try:
        link.symlink_to(silver.parent, target_is_directory=True)
    except OSError:
        pytest.skip("Windows account cannot create symlinks")
    with pytest.raises(DatabaseError, match="dowiązań"), verified_silver(link / "manifest.json"):
        pass


def test_changed_open_file_rejected_before_commit(silver):
    with verified_silver(silver) as verified:
        with (silver.parent / "quality.json").open("ab") as stream:
            stream.write(b" ")
        with pytest.raises(DatabaseError, match="zmieniły"):
            verified.assert_unchanged()


def test_cli_help_and_safe_errors(monkeypatch, capsys, silver):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for arguments in (["--help"], ["db-init", "--help"], ["db-load", "--help"]):
        with pytest.raises(SystemExit) as caught:
            main(arguments)
        assert caught.value.code == 0
    assert main(["db-init"]) == 1
    assert "DATABASE_URL" in capsys.readouterr().err
    secret = "TEST_SECRET_do_not_print"
    monkeypatch.setenv("DATABASE_URL", "postgresql://bad:" + secret + "@127.0.0.1:1/wta")
    assert main(["db-init"]) == 1
    assert secret not in capsys.readouterr().err
    monkeypatch.setenv("DATABASE_URL", "invalid=" + secret)
    assert main(["db-init"]) == 1
    assert secret not in capsys.readouterr().err
    assert main(["db-load", "--silver-manifest", str(silver), "--batch-size", "0"]) == 1
    assert "batch_size" in capsys.readouterr().err

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid silver must be rejected before connecting")

    monkeypatch.setattr(configuration.psycopg, "connect", forbidden)
    assert main(["db-load", "--silver-manifest", str(Path("missing-manifest.json"))]) == 1
