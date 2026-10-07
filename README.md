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

## Author

Jonatan Tomaszewicz
