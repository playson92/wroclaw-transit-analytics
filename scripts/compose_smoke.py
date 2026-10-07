"""Run inside the built non-root pipeline image; use the public CLI end to end."""

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql

from wroclaw_transit_analytics.database.verification import verified_silver
from wroclaw_transit_analytics.preparation.contract import TABLES


def cli(*arguments):
    result = subprocess.run(
        [sys.executable, "-m", "wroclaw_transit_analytics", *map(str, arguments), "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def main():
    if os.geteuid() == 0:
        raise RuntimeError("Smoke must exercise the non-root image user")
    root = Path("/work") / ("smoke-" + uuid4().hex)
    sample = cli("sample-data", "--output-root", root)
    prepared = cli(
        "prepare",
        "--raw-manifest",
        sample["raw_manifest"],
        "--output-root",
        root,
        "--batch-size",
        2,
    )
    manifest = Path(prepared["silver_manifest"])
    first = cli("db-load", "--silver-manifest", manifest, "--batch-size", 2)
    second = cli("db-load", "--silver-manifest", manifest, "--batch-size", 3)
    assert first["status"] in ("LOADED", "ALREADY_LOADED")
    if os.environ.get("WTA_SMOKE_REQUIRE_NEW") == "1":
        assert first["status"] == "LOADED"
    assert second["status"] == "ALREADY_LOADED"
    with verified_silver(manifest) as verified, psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        assert conn.info.server_version // 10000 == 17
        server_version = conn.info.server_version
        role = conn.execute(
            "SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        assert role == (False, False, False)
        assert not conn.execute(
            "SELECT has_schema_privilege(current_user, 'silver', 'CREATE')"
        ).fetchone()[0]
        assert not conn.execute(
            "SELECT has_table_privilege(current_user, 'meta.datasets', 'UPDATE,DELETE,TRUNCATE')"
        ).fetchone()[0]
        counts = {}
        for name in TABLES:
            counts[name] = conn.execute(
                sql.SQL("SELECT count(*) FROM {} WHERE dataset_id=%s").format(
                    sql.Identifier("silver", name)
                ),
                (first["dataset_id"],),
            ).fetchone()[0]
        assert counts == {
            name: entry["row_count"] for name, entry in verified.manifest["tables"].items()
        }
        saved = conn.execute(
            "SELECT status, data_kind, capabilities FROM meta.datasets WHERE dataset_id=%s",
            (first["dataset_id"],),
        ).fetchone()
        assert saved == ("complete", "synthetic_demo", verified.manifest["capabilities"])
    evidence = {
        "status": "PASS",
        "dataset_id": first["dataset_id"],
        "row_counts": counts,
        "second_load": second["status"],
        "uid": os.geteuid(),
        "server_version": server_version,
    }
    Path("/work/compose-smoke.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()
