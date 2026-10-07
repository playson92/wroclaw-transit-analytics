# PostgreSQL 17 — Sprint 02

Sprinty 01–03 są scalone do main. Sprint 04 ma osobny draft PR #6.
Sprint 02 dodaje bazę silver, migracje i runtime Compose. Sprint 03 rozszerza runtime
o [wersjonowane SQL gold](metrics.md); 001 pozostaje bez zmian, upgrade dodaje 002.
Wymagany major to 17; `postgres:17` nie jest deklaracją najnowszej wersji PostgreSQL.
Obraz aplikacji używa `python:3.12-slim`. CI zapisuje odczytane RepoDigests obrazów
w artefaktach `postgres-evidence-*` i `compose-evidence-*` razem z testowanym SHA.
Status konkretnego runu i platform znajduje się w jego review bundle.

## Model i relacje

Każda tabela silver ma `dataset_id` w PK i FK. Nie miesza rekordów dwóch feedów.
Wiersze są dopisywane przez loader, a istniejący dataset nigdy nie jest zastępowany.

| Tabela | Grain wewnątrz datasetu | Relacje |
| --- | --- | --- |
| agency | `_agency_key` | meta.datasets |
| stops | `stop_id` | parent_station → stops, FK odroczony do commit |
| routes | `route_id` | `_agency_key` → agency, agency_id może być null |
| services | `service_id` | unia calendar i calendar_dates |
| calendar | `service_id` | services |
| calendar_dates | `service_id, date` | services |
| trips | `trip_id` | routes i services |
| stop_times | `trip_id, stop_sequence` | trips i stops |

ID to TEXT, daty to DATE, współrzędne to double precision. Sekwencja, provenance
`_wta_source_record`, route_type i sekundy to BIGINT. Godziny oryginalne są tekstem;
25:10:00 pozostaje 90600 sekundami bez modulo 24. Null i pusty tekst są różne.
Znane małe enumy mają SMALLINT i CHECK. Dodatkowe pola mają oryginalne nazwy i wartości
w `extra_fields JSONB`. Nie ma ALTER TABLE według nagłówków źródła.

`meta.datasets` przechowuje źródło, model, fingerprint, data_kind, capabilities,
pełny manifest silver i quality.json, status complete i loaded_at UTC.
W manifestach zachowane są source_present/normalized_empty, input oraz inventory.
Ostrzeżenia i quantitative_gold_supported=false dla frequencies nie blokują load.
Raw/bronze nie są ładowane do SQL. Liczba trips to statyczne szablony, nie dzienne kursy.

## Uruchomienie Compose w PowerShell

Zainstalowany Docker/daemon jest warunkiem tych komend. Aplikacja nie instaluje Dockera.
Z katalogu projektu utwórz lokalną konfigurację, zachowując istniejący `.env`:

```powershell
Set-Location C:\projekty\wroclaw-transit-analytics
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

Wpisz własne trzy różne hasła w POSTGRES_PASSWORD, WTA_LOADER_PASSWORD i WTA_READER_PASSWORD.
Pozostaw nazwę bazy `wta`, port 5433 lub wybierz wolny POSTGRES_PORT.
SILVER_DIR wskazuje cały `C:/projekty/wroclaw-transit-analytics/data/silver`.
Compose czyta `.env` do interpolacji; Python sam nie czyta tego pliku.
Nie wypisuj rozwiniętego `docker compose config`, bo zawiera hasła.

```powershell
docker compose --profile tools build
if ($LASTEXITCODE -ne 0) { throw "Build failed" }
docker compose up -d --wait postgres
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL startup failed" }
docker compose run --rm initializer db-init --loader-role wta_loader --json
if ($LASTEXITCODE -ne 0) { throw "db-init failed" }
docker compose run --rm pipeline db-load --silver-manifest /input/silver/gtfs/20261007T124031398819Z_07856434a78f4eaa8bf92916d05cea09/manifest.json --json
if ($LASTEXITCODE -ne 0) { throw "db-load failed" }
```

Podana ścieżka dotyczy istniejącego realnego silver z tego projektu. Gdy montujesz inny
kompletny run, podstaw jego katalog; nie edytuj manifestu. Silver jest montowane read-only.
Historyczne input.raw_manifest/archive_path to provenance: nie muszą istnieć w kontenerze.
Kontener używa hosta `postgres`; host Windows używa `127.0.0.1:5433`.

Jawnie syntetyczny smoke generuje demo w named volume `/work` należącym do UID 10001:

```powershell
docker compose run --rm --entrypoint python pipeline /app/scripts/compose_smoke.py
if ($LASTEXITCODE -ne 0) { throw "Compose demo smoke failed" }
```

Skrypt używa rzeczywistych poleceń sample-data, prepare i dwukrotnego db-load oraz analytics,
weryfikuje zapytaniami counts, ręczne KPI, capabilities i uprawnienia wta_loader. Nie pobiera GTFS.
Zapisuje wynik `/work/compose-smoke.json`; nie zawiera haseł.
Każdy smoke tworzy świeże pliki. Powtórzony smoke na tej samej bazie może otrzymać
ALREADY_LOADED w pierwszym load; CI wymaga LOADED i używa nowego, unikalnego projektu/bazy.

```powershell
docker compose restart postgres
docker compose up -d --wait postgres
docker compose run --rm initializer db-init --loader-role wta_loader --json
docker compose stop
```

Restart i stop zachowują `postgres_data` oraz `pipeline_work`. Nie używaj `down -v` ani prune.
Bootstrap tworzy wta_loader tylko przy pierwszym uruchomieniu pustego własnego wolumenu.
Zmiana haseł w `.env` nie rotuje haseł istniejącej bazy; wymaga jawnej administracji.
Nie ma chmod 777; bind z silver musi być czytelny dla UID 10001, wyjście jest w `/work`.

## Lokalny Python i role

Do db-init użyj administratora tej dedykowanej bazy. Codzienny load używa wta_loader,
który ma USAGE schematów oraz SELECT/INSERT tabel danych, bez UPDATE/DELETE/TRUNCATE,
CREATE w schematach, superuser, createdb czy createrole. Rola jest utworzona przez
bootstrap Compose; poza Compose administrator tworzy ją w swojej dedykowanej bazie.
`db-init --loader-role` przyznaje prawa istniejącej roli, nie tworzy kont.

Hasło wprowadź lokalnie bez zapisu do historii powłoki:

```powershell
Set-Location C:\projekty\wroclaw-transit-analytics
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$passwordInput = Read-Host "Hasło wta_admin" -AsSecureString
$env:PGPASSWORD = [System.Net.NetworkCredential]::new('', $passwordInput).Password
$env:DATABASE_URL = "host=127.0.0.1 port=5433 dbname=wta user=wta_admin"
.\.venv\Scripts\python.exe -m wroclaw_transit_analytics db-init --loader-role wta_loader
if ($LASTEXITCODE -ne 0) { throw "db-init failed" }
$passwordInput = Read-Host "Hasło wta_loader" -AsSecureString
$env:PGPASSWORD = [System.Net.NetworkCredential]::new('', $passwordInput).Password
$env:DATABASE_URL = "host=127.0.0.1 port=5433 dbname=wta user=wta_loader"
.\.venv\Scripts\python.exe -m wroclaw_transit_analytics db-load --silver-manifest "C:\projekty\wroclaw-transit-analytics\data\silver\gtfs\20261007T124031398819Z_07856434a78f4eaa8bf92916d05cea09\manifest.json" --json
if ($LASTEXITCODE -ne 0) { throw "db-load failed" }
Remove-Item Env:PGPASSWORD
```

DATABASE_URL akceptuje URI Psycopg lub conninfo. Conninfo z PGPASSWORD pomaga uniknąć
kodowania znaków specjalnych hasła w URI. Oczekiwane błędy zwracają stderr i exit 1;
komunikaty PostgreSQL są redagowane i nie wypisują DSN, haseł ani server DETAIL.
Help i wcześniejsze CLI nie wymagają bazy ani sieci.

## Integralność, transakcje i fingerprint

Loader dopuszcza tylko passed silver manifest v1 / wta-silver-v1, wszystkie siedem tabel
oraz zgodny quality.json bez błędów. Sprawdza realne rozmiary/hashy plików, schematy
według schema_for, liczby odczytanych wierszy i logiczne content_sha256. Odrzuca traversal,
symlinki i junction. Otwiera pliki na czas operacji i powtarza kontrolę fizycznych hashów
przed zakończeniem transakcji. Dotyczy to też ALREADY_LOADED.

Content hash jest dokładnie algorytmem przygotowania: ordered schema name/type,
wiersze compact JSON UTF-8 z ISO dates, null i newline, w tym _wta_source_record.
Nullable int64 odczytywany jest przez ArrowDtype bez przejścia przez float.

Fingerprint v1 to SHA-256 canonical JSON (sort_keys, compact separators, UTF-8) z:
dataset/source/model, data_kind/source_kind, capabilities, a dla każdej tabeli
content_sha256, ordered columns/types/nullability, row_count, source_columns,
added_columns, source_present/normalized_empty oraz cały zweryfikowany raport jakości
z pominięciem processing_run_id. Nie obejmuje czasu, ścieżek, run_id, batch_size,
durations ani fizycznego Parquet SHA. Provenance czasu/URL/input jest zachowane w metadanych,
ale nie powoduje konfliktu nowego prepare tego samego źródła.

Przed insert loader bierze transakcyjny advisory lock z pierwszych ośmiu bajtów
SHA-256 dataset_id (signed BIGINT). Unique PK jest dodatkową ochroną. Dwa load tego
samego datasetu kończą się LOADED i ALREADY_LOADED. Inny fingerprint daje CONFLICT.
Jeden dataset, wszystkie COPY, pomocnicze services i status complete są w jednej
transakcji; błąd dowolnego kroku lub odroczonego FK cofa wszystko. Starsze datasety pozostają.
Parquet jest czytany batchami; stop_times nie jest łączone w jeden DataFrame.

Migracje są zasobami wheel i obrazu, nie zależą od cwd. `meta.migrations` przechowuje
wersję, checksum exact SQL bytes i czas. Init jest serializowane własnym advisory lock;
ponowny init jest no-op, zmieniony checksum lub nieznana migracja to błąd.
Stosowanych SQL nie edytuj: dodaj kolejną migrację. Nie ma resetu schematów.

## SELECT i testy

```sql
SELECT dataset_id, data_kind, status, loaded_at,
       capabilities->>'quantitative_gold_supported' AS gold_supported
FROM meta.datasets ORDER BY loaded_at;

SELECT dataset_id, count(*) AS records FROM silver.stop_times GROUP BY dataset_id;

SELECT trip_id, stop_sequence, arrival_time, arrival_seconds
FROM silver.stop_times
WHERE dataset_id = 'gtfs_00a11db35a3dff8c854a5bdba9ee73842ff795561a9a50480119e7d6fb799546'
ORDER BY trip_id, stop_sequence LIMIT 10;
```

Testy offline: `python -m pytest -m "not integration"`. Test dystrybucji buduje i instaluje
wheel bez sieci; dev dependencies zawierają wymagane setuptools/wheel.
Integracja wymaga TEST_DATABASE_URL z dedykowaną bazą `wta_test*` i administratorem
wyłącznie zasobów testowych. Każdy przypadek tworzy i usuwa własną bazę o losowej nazwie.
Brak DSN lokalnie jest jawnym skip; CI ustawia WTA_REQUIRE_INTEGRATION=1 i brak DSN,
błąd połączenia lub jakikolwiek skip to FAIL. Nigdy nie używa DATABASE_URL jako fallback.

CI ma trzy niezależne joby: jakość/offline, realny PostgreSQL 17, build/Compose.
Compose smoke sprawdza non-root, CLI, role, idempotencję i restart named volume.
Repozytorium nie wysyła prawdziwych Parquet/ZIP do CI.

Sprawdzone oficjalne źródła implementacji:
[Psycopg COPY](https://www.psycopg.org/psycopg3/docs/basic/copy.html),
[PostgreSQL 17 COPY](https://www.postgresql.org/docs/17/sql-copy.html),
[BIGINT](https://www.postgresql.org/docs/17/datatype-numeric.html),
[Compose healthy dependencies](https://docs.docker.com/compose/how-tos/startup-order/),
[GitHub PostgreSQL service containers](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers).
