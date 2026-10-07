"""An existing login receives only append/read permissions, during db-init."""

import os

from psycopg import sql

from .connection import DatabaseError


def grant_loader(connection, role: str) -> None:
    identifier = sql.Identifier(role)
    connection.execute(sql.SQL("GRANT USAGE ON SCHEMA meta, silver, gold TO {}").format(identifier))
    connection.execute(sql.SQL("GRANT SELECT ON meta.migrations TO {}").format(identifier))
    connection.execute(
        sql.SQL("GRANT SELECT, INSERT ON meta.datasets, meta.analyses TO {}").format(identifier)
    )
    connection.execute(
        sql.SQL("GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA silver TO {}").format(identifier)
    )
    connection.execute(
        sql.SQL("GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA gold TO {}").format(identifier)
    )


def grant_reader(connection, role: str = "wta_reader") -> None:
    """No password rotation or remediation of a foreign privileged role."""
    if role != "wta_reader":
        raise DatabaseError("Reader musi używać własnej roli wta_reader.")
    connection.execute("SELECT pg_advisory_xact_lock(%s)", (0x5754410002,))
    existing = connection.execute(
        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, rolcanlogin "
        "FROM pg_roles WHERE rolname=%s",
        (role,),
    ).fetchone()
    identifier = sql.Identifier(role)
    if existing is None:
        password = os.environ.get("WTA_READER_PASSWORD")
        if not password:
            raise DatabaseError(
                "Nowy reader wymaga WTA_READER_PASSWORD; hasło nie jest wypisywane."
            )
        connection.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION "
                "NOBYPASSRLS PASSWORD {}"
            ).format(identifier, sql.Literal(password))
        )
    elif existing != (False, False, False, False, False, True):
        raise DatabaseError("Istniejący reader ma niezgodne atrybuty; nie zmieniono cudzej roli.")
    memberships = connection.execute(
        "SELECT count(*) FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles "
        "WHERE rolname=%s)",
        (role,),
    ).fetchone()[0]
    unsafe = connection.execute(
        "SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname IN ('meta','silver','gold') AND c.relkind IN ('r','v','m','p') "
        "AND has_table_privilege(%s,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')) "
        "OR EXISTS(SELECT 1 FROM pg_namespace WHERE nspname IN ('meta','silver','gold','public') "
        "AND has_schema_privilege(%s,oid,'CREATE'))",
        (role, role),
    ).fetchone()[0]
    if memberships or unsafe:
        raise DatabaseError("Istniejący reader ma prawa zapisu/członkostwa; nie zmieniono roli.")
    connection.execute(sql.SQL("GRANT USAGE ON SCHEMA meta, gold TO {}").format(identifier))
    connection.execute(
        sql.SQL("GRANT SELECT ON meta.datasets, meta.analyses TO {}").format(identifier)
    )
    connection.execute(
        sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA gold TO {}").format(identifier)
    )
