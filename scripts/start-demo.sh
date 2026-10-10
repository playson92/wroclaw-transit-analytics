#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
command -v docker >/dev/null 2>&1 || {
  echo 'Brak Docker CLI lub daemona. Uruchom istniejący Docker i ponów start demo.' >&2
  exit 1
}
if [ -n "${DOCKER_HOST:-}" ] && [ -z "${DOCKER_CONTEXT:-}" ]; then
  endpoint=$DOCKER_HOST
else
  active_context=${DOCKER_CONTEXT:-$(docker context show)}
  endpoint=$(docker context inspect "$active_context" --format '{{.Endpoints.docker.Host}}')
fi
case "$endpoint" in unix:///*|npipe:////./pipe/*) ;; *)
  echo 'Aktywna konfiguracja Dockera jest zdalna; nie użyto jej.' >&2; exit 1;;
esac
[ "$(docker info --format '{{.OSType}}')" = linux ] || {
  echo 'Demo wymaga dostępnego lokalnego silnika Linux Dockera.' >&2; exit 1;
}
if [ ! -f .env.demo ]; then
  volumes=$(docker volume ls --filter label=com.docker.compose.project=wta-demo --format '{{.Name}}')
  [ -z "$volumes" ] || { echo 'Istnieje wolumen demo; przywróć .env.demo.' >&2; exit 1; }
  umask 077
  for key in POSTGRES_PASSWORD WTA_LOADER_PASSWORD WTA_READER_PASSWORD; do
    printf '%s=%s\n' "$key" "$(openssl rand -hex 32)" >> .env.demo
  done
fi
unset POSTGRES_PASSWORD WTA_LOADER_PASSWORD WTA_READER_PASSWORD COMPOSE_PROFILES
export DASHBOARD_PORT="${DASHBOARD_PORT:-8501}" POSTGRES_PORT="${POSTGRES_PORT:-5433}"
mkdir -p data/silver
export SILVER_DIR="$(pwd)/data/silver"
compose() { docker compose --project-name wta-demo --env-file .env.demo "$@"; }
compose --profile tools build
compose up -d --wait postgres
compose run --rm initializer
compose run --rm pipeline demo --json
compose up -d --wait dashboard
printf 'Demo gotowe: http://127.0.0.1:%s\n' "$DASHBOARD_PORT"
