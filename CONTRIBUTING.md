# Contributing

Use a separate `feat/`, `fix/`, `docs/`, `test/` or `refactor/` branch. Keep commits focused, update affected documentation, and open a pull request with the behavior change and relevant verification. Do not commit secrets, local configuration, private data, full GTFS archives, generated Parquet or review-run outputs.

## Development environment

Use Python **3.12** and a virtual environment. On Linux/macOS:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -c constraints.txt -e ".[dev,dashboard,ui-test]"
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m pytest -m "not integration and not browser"
```

On Windows, create the environment with `py -V:3.12 -m venv .venv` and use `.venv\Scripts\python.exe` for those commands. Activating the environment is optional. The Docker demo itself needs no host Python: [quick start](README.md#quick-start-from-a-fresh-download).

Use the pinned [constraints](constraints.txt). Add dependencies only when needed; verify Linux AMD64 and ARM64 native imports when changing packages with binary extensions.

## Tests with a database or browser

- PostgreSQL tests require a **dedicated PostgreSQL 17 test database**, an administrator scoped to that test environment, and `TEST_DATABASE_URL`. The database name must begin with `wta_test`. Tests create and remove their own randomly named databases; never point them at a demo, production or shared application database. Run `python -m pytest -m integration`; set `WTA_REQUIRE_INTEGRATION=1` to fail rather than skip when required infrastructure is missing.
- Browser tests use Playwright and a running Streamlit/Compose fixture. Install the local Chromium runner with `python -m playwright install chromium`; Linux runners may need `--with-deps`. Each browser test module documents the URL and fixture environment it requires. Follow the checked-in [CI workflow](.github/workflows/ci.yml) for complete setup and mandatory checks.
- Keep the two-snapshot/disjoint-calendar [browser regression](tests/ui/test_snapshot_browser.py). Its required fixture must fail when unavailable. Navigation changes must preserve dataset, day and dependent-filter behavior after a second interaction, page changes and reload.
- Use local fixtures or blocked public tile requests for ordinary map tests. The [raster test](tests/ui/test_raster_browser.py) explicitly labels its synthetic image. Do not bulk-download, scan or package OpenStreetMap tiles.

CI runs quality/offline, real PostgreSQL, Compose/browser regression and portable-demo architecture checks. Report the tested SHA, failures and explicit skips; a health endpoint or image build alone does not prove the UI works.

## Data and presentation contracts

Preserve textual IDs, repeated stop visits, service-day times over 24:00 and the distinction between missing values and zero. Keep SQL/data access separate from presentation. Existing applied migrations are checksum-protected: add a new migration instead of modifying one already published. [Data contract](docs/data-contract.md) · [Metrics](docs/metrics.md) · [Reader permissions](docs/dashboard.md).

The D1/D2 fixture and its 16 / 25 / 2 / 3 seven-day expectation are regression inputs, not a Wrocław timetable. The separately packaged portfolio sample is a derivative archive with explicit source, hashes, closed references, selection rules and license. Rebuild it only from the exact original specified in its provenance; do not overwrite historical source manifests or represent a filtered ZIP as an original download.

Use the official Streamlit API and installed-version theme options. Keep CSS in shared presentation modules, escape source text inserted into HTML, and test first-screen desktop plus narrow/mobile layouts. Screenshots and recordings must come from the running application.

Keep demo passwords in their persistent credential volumes. Repeated start and restart must retain existing data. Do not use `down -v`, `prune`, broad cleanup commands, or stop another project's containers while validating your change.

## Pull requests

Include the concrete before/after behavior, affected contracts, how it was tested, and material limitations. For UI work, include actual desktop and narrow-screen captures. For startup work, verify a fresh exported source directory without `.git`, `.env`, host Python or prepared data, then repeat startup and restart. Keep test evidence scoped to your own Compose project and the reviewed commit.

Code is licensed under [MIT](LICENSE); the bundled GTFS sample and optional map have their own documented licenses. Please preserve those notices and attribution.
