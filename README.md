# Wroclaw Transit Analytics

Local-first platform for processing and analysing public transport data from Wroclaw.

## MVP

The first version will:

1. download a public GTFS dataset,
2. preserve the original ZIP file in the raw data layer,
3. validate required GTFS files and columns,
4. extract stops, routes, trips and stop times,
5. prepare cleaned analytical datasets,
6. calculate basic route and stop statistics,
7. run locally with automated tests and CI.

## Technology stack

- Python 3.12
- Pandas
- HTTPX
- SQL
- PostgreSQL
- Docker
- pytest
- Ruff
- GitHub Actions

## Local setup

```powershell
py -V:3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Checks

```powershell
ruff check .
ruff format --check .
python -m pytest
```

## GTFS ingestion (implemented)

The first working feature downloads an explicitly selected official GTFS archive,
preserves its bytes in raw, validates the `wroclaw-static-mvp-v1` profile and writes
a JSON completion manifest. Later analytical processing remains planned.

Start in the repository directory. Copy the address of a specific **Pobierz** link
from the [official file catalogue](https://open-data.cui.wroclaw.pl/hdb/ft/6/), then run:

```powershell
Set-Location C:\projekty\wroclaw-transit-analytics
.\.venv\Scripts\python.exe -m wroclaw_transit_analytics.gtfs --help
.\.venv\Scripts\python.exe -m wroclaw_transit_analytics.gtfs --url "<OFFICIAL_ZIP_URL>"
```

Alternatively, set the environment variable in PowerShell:

```powershell
$env:GTFS_URL = "<OFFICIAL_ZIP_URL>"
.\.venv\Scripts\python.exe -m wroclaw_transit_analytics.gtfs
```

`--url` takes precedence over `GTFS_URL`. A `.env` file is not loaded automatically.
There is no automatic selection of the latest resource. See
[GTFS ingestion](docs/gtfs-ingestion.md) for raw layout, failure handling and validation limits.

## Author

Jonatan Tomaszewicz
