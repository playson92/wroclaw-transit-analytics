"""Credential reuse and lost-configuration refusal protect retained demo databases."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from wroclaw_transit_analytics.database import DatabaseError
from wroclaw_transit_analytics.portfolio.runtime import configure, reader_dsn


def snapshot(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and path.name != ".lock"
    }


def test_first_config_generates_distinct_credentials_and_restart_preserves_them(tmp_path):
    secrets = tmp_path / "secrets"
    database = tmp_path / "database"
    database.mkdir()
    first = configure(secrets, database, set_owner=False)
    before = snapshot(secrets)
    passwords = [before[f"{role}/password"] for role in ("admin", "loader", "reader")]
    assert len(set(passwords)) == 3 and all(len(value.strip()) == 64 for value in passwords)
    assert all(value.decode().strip() not in json.dumps(first) for value in passwords)
    (database / "PG_VERSION").write_text("17")
    assert configure(secrets, database, set_owner=False)["status"] == "CONFIG_REUSED"
    assert snapshot(secrets) == before


def test_database_without_configuration_refuses_to_generate_credentials(tmp_path):
    database = tmp_path / "database"
    database.mkdir()
    (database / "PG_VERSION").write_text("17")
    secrets = tmp_path / "secrets"
    with pytest.raises(DatabaseError, match="DEMO_CONFIG_LOST"):
        configure(secrets, database, set_owner=False)
    assert not snapshot(secrets)
    assert (database / "PG_VERSION").read_text() == "17"


def test_partial_or_mismatched_configuration_is_not_overwritten(tmp_path):
    secrets = tmp_path / "secrets"
    database = tmp_path / "database"
    configure(secrets, database, set_owner=False)
    missing = secrets / "reader" / "password"
    missing.chmod(0o600)
    missing.unlink()
    before = snapshot(secrets)
    with pytest.raises(DatabaseError, match="DEMO_CONFIG_LOST"):
        configure(secrets, database, set_owner=False)
    assert snapshot(secrets) == before


def test_mismatched_cluster_ids_are_rejected(tmp_path):
    secrets = tmp_path / "secrets"
    database = tmp_path / "database"
    configure(secrets, database, set_owner=False)
    wrong = secrets / "reader" / "cluster-id"
    wrong.chmod(0o600)
    wrong.write_text("f" * 64)
    before = snapshot(secrets)
    with pytest.raises(DatabaseError, match="DEMO_CONFIG_MISMATCH"):
        configure(secrets, database, set_owner=False)
    assert snapshot(secrets) == before


def test_reader_configuration_is_scoped_and_malformed_secret_is_not_logged(tmp_path):
    password = tmp_path / "password"
    password.write_text("a" * 64)
    value = reader_dsn(password)
    assert "user=wta_reader" in value and "host=postgres" in value
    password.write_text("private-invalid-password")
    with pytest.raises(DatabaseError) as caught:
        reader_dsn(password)
    assert "private-invalid-password" not in str(caught.value)


def test_concurrent_configuration_creates_one_consistent_credential_set(tmp_path):
    secrets = tmp_path / "secrets"
    database = tmp_path / "database"
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(
                lambda _: configure(secrets, database, set_owner=False),
                range(4),
            )
        )
    assert [result["status"] for result in results].count("CONFIG_CREATED") == 1
    assert [result["status"] for result in results].count("CONFIG_REUSED") == 3
    before = snapshot(secrets)
    ids = {before[f"{role}/cluster-id"] for role in ("admin", "loader", "reader")}
    assert len(ids) == 1
    assert configure(secrets, database, set_owner=False)["status"] == "CONFIG_REUSED"
    assert snapshot(secrets) == before


def test_invalid_retained_credential_is_not_regenerated_or_disclosed(tmp_path):
    secrets = tmp_path / "secrets"
    database = tmp_path / "database"
    configure(secrets, database, set_owner=False)
    password = secrets / "loader" / "password"
    password.chmod(0o600)
    password.write_text("private-invalid-password")
    before = snapshot(secrets)
    with pytest.raises(DatabaseError, match="DEMO_CONFIG_INVALID") as caught:
        configure(secrets, database, set_owner=False)
    assert "private-invalid-password" not in str(caught.value)
    assert snapshot(secrets) == before
