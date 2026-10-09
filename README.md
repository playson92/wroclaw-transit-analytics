# Wroclaw Transit Analytics

Odtwarzalna analiza rozkładu GTFS: raw → bronze/silver Parquet i jakość → PostgreSQL
→ SQL gold → dashboard Streamlit po polsku.

## Mapa i linie

Pierwszy ekran przegląda rzeczywisty snapshot GTFS: dzień, autobus/tramwaj, linia,
kierunek/wariant, konkretny kurs i przystanek. Interaktywna mapa pokazuje shapes
wybranego kursu; kliknięcie punktu otwiera jego rozkładowe odjazdy. Lista i tabela
działają także bez podkładu. Analityka KPI i widok danych/jakości pozostają dostępne.

[Dokładne uruchomienie i zakres przeglądarki](docs/transit-explorer.md). Nowa wersja
jest testowana osobno na **8502**, z własną bazą i wolumenami; demo na 8501 pozostaje
niezależne. Lokalny GTFS pobrany 2026-10-04 ma kalendarz 2026-10-03–2026-10-18 i
jest oznaczony jako historyczny snapshot, bez obietnicy aktualnego rozkładu.

Osobne obserwacje pojazdów CUI mają status źródła, walidację współrzędnych,
czas pobrania/pomiaru i ograniczenie żądań. **Integracja live pozostaje zablokowana**:
eksport nie potwierdza strefy czasu, a jego metadane licencji są niespójne z metadanymi
pozycji. Punkty obserwacji nie są przypisywane do kursu ani przedstawiane jako aktualny GPS.

## Jeden start demo

Wymagany działający Docker/daemon i Compose v2. PowerShell:

```powershell
Set-Location 'C:\projekty\wroclaw-transit-analytics'
& .\scripts\start-demo.ps1 -DashboardPort 8501 -PostgresPort 5433
```

Skrypt buduje obraz non-root, inicjalizuje bazę i role, wykonuje ten sam pipeline demo
i uruchamia dashboard. Wypisuje rzeczywisty URL; adres oczekiwany przy domyślnym porcie
to http://127.0.0.1:8501. Inny port: `-DashboardPort 8502`. Powtórzenie zachowuje hasła
i named volumes własnego projektu wta-demo. Nie nadpisuje `.env` ani nie instaluje Dockera.
**DANE SYNTETYCZNE — nie rozkład Wrocławia**. Linux/macOS: `sh scripts/start-demo.sh`.

[Dashboard, reader i dokładne uruchomienie](docs/dashboard.md),
[studium portfolio](docs/portfolio-case-study.md),
[release notes/checklista v0.2.0](docs/release-notes-v0.2.0.md).
Kod: MIT. Dane: CC0 1.0 według [oficjalnych metadanych](https://open-data.cui.wroclaw.pl/hdb/metadane/13/),
odczyt 2026-10-07. Dane rozkładowe nie oznaczają punktualności, pasażerów ani realtime.

## MVP

Zaimplementowany przepływ obejmuje:

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
- Streamlit (opcjonalny dashboard)

## Local setup

```powershell
py -V:3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -c constraints.txt -e ".[dev,dashboard,ui-test]"
```

## Checks

```powershell
ruff check .
ruff format --check .
python -m pytest -m "not integration and not browser"
```

## GTFS ingestion (implemented)

The first working feature downloads an explicitly selected official GTFS archive,
preserves its bytes in raw, validates the `wroclaw-static-mvp-v1` profile and writes
a JSON completion manifest. File preparation, SQL analytics and the optional UI are implemented.

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
Gold SQL is implemented below; the dashboard reads its results using a separate reader role.

## PostgreSQL runtime (Sprint 02)

The root CLI adds `db-init` and `db-load --silver-manifest PATH`.
The [PostgreSQL and Compose guide](docs/postgres-runtime.md) gives exact PowerShell commands,
roles, model grains, idempotence rules and read-only silver mounts.
The application image runs as a non-root user. CI runs offline checks,
real PostgreSQL 17 integration cases and a separate image build/Compose smoke.
Local Windows Compose and the real-feed load require a working local Docker daemon;
Linux CI does not establish Windows runtime compatibility.

## Scheduled-service analytics (Sprint 03)

`analytics --dataset-id ID --start-date YYYY-MM-DD --end-date YYYY-MM-DD --json`
expands actual service calendars and computes daily trips, regular known departures,
hourly counts, headways, service spans and per-day coverage in PostgreSQL SQL.
The returned analysis_id identifies append-only results; repeat calls are idempotent.
Unsupported frequencies and excessive expansion are rejected before publication.
See [metrics and runnable examples](docs/metrics.md) for definitions, upgrade/grants,
null/zero semantics, execution limits and service-day/DST restrictions.

See [data contract](docs/data-contract.md), [scope](docs/project-scope.md)
and [implementation plan](docs/project-plan.md).

## Author

Jonatan Tomaszewicz
