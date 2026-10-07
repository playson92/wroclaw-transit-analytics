"""No production fallback: each integration case owns a fresh test database."""

import os
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from tests.preparation.conftest import make_raw as make_raw

from wroclaw_transit_analytics.preparation import prepare
from wroclaw_transit_analytics.sample_data import write_sample_data


@pytest.fixture
def silver(tmp_path):
    sample = write_sample_data(tmp_path / "sample")
    return prepare(sample.manifest_path, tmp_path / "prepared", batch_size=2).silver_manifest


@pytest.fixture
def db_url():
    base = os.environ.get("TEST_DATABASE_URL")
    if not base:
        if os.environ.get("WTA_REQUIRE_INTEGRATION") == "1":
            pytest.fail("Integration job requires TEST_DATABASE_URL; skips are forbidden")
        pytest.skip("Local integration NOT_RUN: TEST_DATABASE_URL is unset")
    settings = conninfo_to_dict(base)
    if not settings.get("dbname", "").startswith("wta_test"):
        pytest.fail("TEST_DATABASE_URL must name a dedicated wta_test* database")
    name = "wta_test_" + uuid4().hex
    with psycopg.connect(base, autocommit=True, connect_timeout=10) as admin:
        assert admin.info.server_version // 10000 == 17
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            yield make_conninfo(base, dbname=name)
        finally:
            # Only the unique database this fixture created, never schemas in an existing DB.
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
