"""An existing login receives only append/read permissions, during db-init."""

from psycopg import sql


def grant_loader(connection, role: str) -> None:
    identifier = sql.Identifier(role)
    connection.execute(sql.SQL("GRANT USAGE ON SCHEMA meta, silver TO {}").format(identifier))
    connection.execute(sql.SQL("GRANT SELECT, INSERT ON meta.datasets TO {}").format(identifier))
    connection.execute(
        sql.SQL("GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA silver TO {}").format(identifier)
    )
