"""Packaged SQL, transaction-scoped serialization and immutable migration history."""

import hashlib
from importlib.resources import files

from .connection import DatabaseError, connect
from .roles import grant_loader, grant_reader

MIGRATION_LOCK = 0x5754410001


def migration_files() -> list[tuple[str, str, str]]:
    root = files("wroclaw_transit_analytics.database").joinpath("sql")
    result = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.name.endswith(".sql"):
            content = path.read_bytes()
            result.append((path.name, hashlib.sha256(content).hexdigest(), content.decode("utf-8")))
    if not result:
        raise DatabaseError("Brak SQL migracji w zainstalowanym pakiecie.")
    return result


def apply_migrations(connection, migrations: list[tuple[str, str, str]] | None = None) -> list[str]:
    entries = migration_files() if migrations is None else migrations
    if len({entry[0] for entry in entries}) != len(entries):
        raise DatabaseError("Powtórzona wersja migracji.")
    applied = []
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK,))
        connection.execute("CREATE SCHEMA IF NOT EXISTS meta")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS meta.migrations ("
            "version TEXT PRIMARY KEY, checksum TEXT NOT NULL, "
            "applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp())"
        )
        history = dict(connection.execute("SELECT version, checksum FROM meta.migrations"))
        known = {entry[0] for entry in entries}
        if history.keys() - known:
            raise DatabaseError("Baza zawiera migracje nieznane tej wersji aplikacji.")
        for version, checksum, query in entries:
            if version in history:
                if history[version] != checksum:
                    raise DatabaseError(f"Konflikt checksum migracji {version}.")
                continue
            connection.execute(query)
            connection.execute(
                "INSERT INTO meta.migrations (version, checksum) VALUES (%s, %s)",
                (version, checksum),
            )
            applied.append(version)
    return applied


def initialize(
    database_url: str | None = None,
    *,
    loader_role: str | None = None,
    reader_role: str | None = None,
) -> list[str]:
    with connect(database_url) as connection, connection.transaction():
        applied = apply_migrations(connection)
        if loader_role is not None:
            grant_loader(connection, loader_role)
        if reader_role is not None:
            grant_reader(connection, reader_role)
        return applied
