"""Explicit configuration and errors that never include a connection string."""

import os
from contextlib import contextmanager

import psycopg


class DatabaseError(Exception):
    """An actionable, safe message for the public CLI."""


@contextmanager
def connect(database_url: str | None = None):
    value = database_url if database_url is not None else os.environ.get("DATABASE_URL")
    if not value or not value.strip():
        raise DatabaseError("DATABASE_URL jest wymagane; Python nie wczytuje pliku .env.")
    try:
        with psycopg.connect(value, connect_timeout=10) as connection:
            if connection.info.server_version // 10000 != 17:
                raise DatabaseError("Wymagany jest PostgreSQL 17.")
            yield connection
    except psycopg.Error as exc:
        # Server DETAIL, libpq text and malformed DSNs may all contain secrets or input values.
        code = exc.sqlstate or "connection/configuration"
        raise DatabaseError(
            f"PostgreSQL: {type(exc).__name__} ({code}). Sprawdź konfigurację, "
            "uprawnienia, db-init oraz zgodność danych. Szczegóły połączenia ukryto."
        ) from None
    except (ValueError, UnicodeError):
        raise DatabaseError("Niepoprawne DATABASE_URL; szczegóły połączenia ukryto.") from None
