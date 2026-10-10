"""One-off demo setup; all data transformations remain in the existing pipeline.

Credential volumes are deliberately separated. Only configuration generation and
directory ownership run as root; initializer, sample and dashboard use UID 10001.
No credentials or connection strings are printed, including in failures.
"""

import argparse
import json
import os
import secrets
import sys
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from ..dashboard.launcher import launch
from ..database import DatabaseError, initialize
from ..database.connection import connect
from ..explorer.geometry import import_geometry
from ..pipeline import run
from ..preparation.source import PrepareError, file_sha256, read_source, write_json

SECRET_ROOT = Path("/run/secrets")
WORK_ROOT = Path("/work")
DATABASE_ROOT = Path("/database")
ROLES = {"admin": "wta_admin", "loader": "wta_loader", "reader": "wta_reader"}


@contextmanager
def _config_lock(path: Path):
    with path.open("a+", encoding="ascii") as lock:
        if os.name == "nt":
            import msvcrt

            lock.write("0")
            lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def _credential(path: Path) -> str:
    try:
        value = path.read_text(encoding="ascii").strip()
    except OSError:
        raise DatabaseError(
            "DEMO_CONFIG_MISSING: przywróć odpowiadający wolumen konfiguracji."
        ) from None
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise DatabaseError(
            "DEMO_CONFIG_INVALID: niepoprawny plik poświadczeń; niczego nie zmieniono."
        )
    return value


def _dsn(role: str, secret_root: Path = SECRET_ROOT) -> str:
    return make_conninfo(
        host="postgres",
        port=5432,
        dbname="wta",
        user=ROLES[role],
        password=_credential(secret_root / role / "password"),
    )


def reader_dsn(credential_file: Path = SECRET_ROOT / "reader" / "password") -> str:
    """Return the scoped reader conninfo; callers must never log it."""
    return make_conninfo(
        host="postgres",
        port=5432,
        dbname="wta",
        user="wta_reader",
        password=_credential(credential_file),
    )


def configure(
    secret_root: Path = SECRET_ROOT,
    database_root: Path = DATABASE_ROOT,
    *,
    set_owner: bool = True,
) -> dict:
    roots = [secret_root / role for role in ROLES]
    for directory in roots:
        directory.mkdir(parents=True, exist_ok=True)
    # A process crash must never make an existing database look like a fresh one.
    # The database mount is read-only; only this volume's credential lock is written.
    with _config_lock(roots[0] / ".lock"):
        paths = [directory / name for directory in roots for name in ("password", "cluster-id")]
        present = [path.is_file() for path in paths]
        database_exists = (database_root / "PG_VERSION").is_file()
        if (any(present) or database_exists) and not all(present):
            raise DatabaseError(
                "DEMO_CONFIG_LOST: baza lub część konfiguracji istnieje, ale brak odpowiadających "
                "poświadczeń. Przywróć komplet trzech wolumenów konfiguracji tego projektu; "
                "hasła i dane nie zostały zmienione."
            )
        if all(present):
            cluster_ids = [(directory / "cluster-id").read_text().strip() for directory in roots]
            if len(set(cluster_ids)) != 1 or len(cluster_ids[0]) != 64:
                raise DatabaseError(
                    "DEMO_CONFIG_MISMATCH: wolumeny konfiguracji pochodzą z różnych instancji."
                )
            for directory in roots:
                _credential(directory / "password")
            return {"status": "CONFIG_REUSED", "credentials": "preserved"}
        cluster_id = secrets.token_hex(32)
        for role, directory in zip(ROLES, roots, strict=True):
            for name, value in (("password", secrets.token_hex(32)), ("cluster-id", cluster_id)):
                path = directory / name
                with path.open("x", encoding="ascii") as stream:
                    stream.write(value + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                if set_owner:
                    os.chown(path, 10001, 10001)
                # PG's entrypoint needs its administrator password as postgres UID.
                # That file is scoped to PG and initializer, mounted read-only.
                path.chmod(0o444 if role == "admin" or name == "cluster-id" else 0o400)
            if set_owner:
                os.chown(directory, 10001, 10001)
            directory.chmod(0o755)
        return {"status": "CONFIG_CREATED", "credentials": "random persistent files"}


def initialize_demo(secret_root: Path = SECRET_ROOT) -> dict:
    admin_dsn = _dsn("admin", secret_root)
    loader_password = _credential(secret_root / "loader" / "password")
    with connect(admin_dsn) as connection, connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (0x5754410003,))
        existing = connection.execute(
            "SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolcanlogin "
            "FROM pg_roles WHERE rolname='wta_loader'"
        ).fetchone()
        if existing is None:
            connection.execute(
                sql.SQL(
                    "CREATE ROLE wta_loader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Literal(loader_password))
            )
        elif existing != (False, False, False, False, False, True):
            raise DatabaseError("DEMO_LOADER_UNSAFE: niezgodne atrybuty istniejącego loadera.")
    # Reader creation and grant verification use exactly the existing migration API.
    os.environ["WTA_READER_PASSWORD"] = _credential(secret_root / "reader" / "password")
    try:
        applied = initialize(admin_dsn, loader_role="wta_loader", reader_role="wta_reader")
    finally:
        os.environ.pop("WTA_READER_PASSWORD", None)
    # A mismatched configuration is detected without rotating any existing password.
    for role in ("loader", "reader"):
        with connect(_dsn(role, secret_root)) as connection:
            connection.execute("SELECT 1")
    return {"status": "INITIALIZED" if applied else "UP_TO_DATE", "applied": applied}


def prepare_sample(work_root: Path = WORK_ROOT, secret_root: Path = SECRET_ROOT) -> dict:
    manifest = Path(__file__).with_name("assets") / "manifest.json"
    source = read_source(manifest)
    dsn = _dsn("loader", secret_root)
    # The original service calendar establishes both dates, not the host's clock.
    start_date, end_date = "2026-10-03", "2026-10-09"
    ready = work_root / "portfolio-ready.json"
    if ready.is_file():
        saved = json.loads(ready.read_text(encoding="utf-8"))
        if saved.get("source_sha256") != source.sha256:
            raise DatabaseError("DEMO_SAMPLE_CONFLICT: istniejący stan dotyczy innej próbki.")
    result = run(manifest, start_date, end_date, work_root / "data", dsn)
    if result["status"] != "PASSED":
        failed = next(value for value in result["stages"].values() if value["status"] == "FAILED")
        raise DatabaseError("DEMO_PIPELINE_FAILED: " + failed["error"])
    geometry = import_geometry(manifest, dsn)
    if geometry["dataset_id"] != result["dataset_id"] or geometry["geometry_status"] != "complete":
        raise DatabaseError("DEMO_GEOMETRY_FAILED: nie potwierdzono geometrii tej samej próbki.")
    proof = {
        "status": "READY",
        "dataset_id": result["dataset_id"],
        "analysis_id": result["analysis_id"],
        "source_sha256": source.sha256,
        "sample_manifest_sha256": file_sha256(manifest),
        "start_date": start_date,
        "end_date": end_date,
        "load_status": result["stages"]["load"]["status"],
        "analysis_status": result["stages"]["analyze"]["status"],
        "geometry": geometry,
    }
    if not ready.exists():
        write_json(ready, proof)
    return proof


def dashboard() -> int:
    os.environ["READONLY_DATABASE_URL"] = reader_dsn()
    return launch(8501, "0.0.0.0")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Portable local portfolio demo stages.")
    parser.add_argument("stage", choices=("config", "initialize", "sample", "dashboard"))
    args = parser.parse_args(argv)
    try:
        if args.stage == "dashboard":
            return dashboard()
        operation = {"config": configure, "initialize": initialize_demo, "sample": prepare_sample}
        print(json.dumps(operation[args.stage](), ensure_ascii=False))
        return 0
    except (DatabaseError, PrepareError) as exc:
        print(f"Demo: {exc}", file=sys.stderr)
    except (OSError, ValueError, psycopg.Error):
        print(
            "DEMO_STAGE_FAILED: błąd plików/konfiguracji; poświadczenia nie zostały ujawnione.",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
