# Project Scope

## Goal

Build a reproducible local GTFS pipeline and dashboard for scheduled public transport in Wroclaw.

## Implemented

- static GTFS ingestion,
- raw file archive,
- source validation,
- cleaned analytical datasets,
- streamed textual bronze and typed silver Parquet,
- global quality, provenance and nullable service-time coverage,
- prepare CLI and deterministic, explicitly synthetic sample feed,
- automated tests,
- local execution.

## Remaining local MVP

- PostgreSQL storage,
- Docker Compose,
- dashboard,
- gold SQL over explicit service dates.

## Beyond MVP

- GTFS Realtime and actual vehicle positions,
- punctuality, passengers and occupancy require separate measured sources,
- frequency-based service expansion, shapes and snapshot comparison,
- optional cloud deployment.

See [the plan](project-plan.md), [prepare guide](prepare.md) and [data contract](data-contract.md).
