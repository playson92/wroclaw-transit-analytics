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
- PyArrow (Parquet)
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
a JSON completion manifest. File preparation is implemented below; SQL analytics and UI remain planned.

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

## GTFS preparation (implemented)

Completed raw runs now produce streamed textual bronze, typed silver Parquet,
and a global quality report. Required values, keys, cross-table references and known
service-time ordering must pass before silver is published. Source bytes remain unchanged.

Start a small **synthetic** example after dependency installation:

```powershell
Set-Location C:\projekty\wroclaw-transit-analytics
$demo = (& .\.venv\Scripts\python.exe -m wroclaw_transit_analytics sample-data --output-root data --json) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "Generator demo failed." }
$result = (& .\.venv\Scripts\python.exe -m wroclaw_transit_analytics prepare --raw-manifest $demo.raw_manifest --output-root data --json) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "Prepare failed." }
$result | Format-List
```

The returned paths identify this exact run; no latest-file guessing is required.
After packages are installed, sample generation and prepare are offline.
For official data, use the existing ingestion command, then pass its actual raw manifest
to prepare. See the [Polish prepare guide](docs/prepare.md).

Times above 24:00 retain their GTFS service-day meaning. Missing allowed times stay null.
Each run preserves source/model identity and inventories files excluded from the MVP.
Nonempty frequencies is preserved in bronze and marks quantitative gold unsupported.
Verified silver can now be loaded into PostgreSQL 17 using transactional COPY.
Gold SQL and the dashboard remain planned.

## PostgreSQL runtime (Sprint 02)

The root CLI adds `db-init` and `db-load --silver-manifest PATH`.
The [PostgreSQL and Compose guide](docs/postgres-runtime.md) gives exact PowerShell commands,
roles, model grains, idempotence rules and read-only silver mounts.
The application image runs as a non-root user. CI runs offline checks,
real PostgreSQL 17 integration cases and a separate image build/Compose smoke.
Local Windows Compose and the real-feed load require a working local Docker daemon;
Linux CI does not establish Windows runtime compatibility.

See [data contract](docs/data-contract.md), [scope](docs/project-scope.md)
and [implementation plan](docs/project-plan.md).

## Author

Jonatan Tomaszewicz
