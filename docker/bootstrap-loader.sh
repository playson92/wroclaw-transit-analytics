#!/bin/sh
set -eu
# Only the official entrypoint's first initialization of this project's empty volume.
# Feed the password via a psql variable, never concatenate it into SQL.
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 --set=loader_password="$WTA_LOADER_PASSWORD" <<'SQL'
CREATE ROLE wta_loader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
  PASSWORD :'loader_password';
SQL
