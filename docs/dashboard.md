# Dashboard i jedno demo

Wymagania: Docker z działającym daemonem i Compose v2. Obraz zawiera Python 3.12,
zainstalowany pakiet oraz opcjonalny Streamlit 1.57. Podstawowy pakiet i `--help`
działają bez Streamlita i bazy. Instalacja do projektowego `.venv`:
`python -m pip install -c constraints.txt -e ".[dev,dashboard,ui-test]"`.
Constraints pochodzą z zależności projektu; CI sprawdza je także na Linuxie.

## Windows PowerShell

```powershell
Set-Location 'C:\projekty\wroclaw-transit-analytics'
& ([scriptblock]::Create((Get-Content -Encoding UTF8 -LiteralPath '.\scripts\start-demo.ps1' -Raw))) -RepoRoot (Get-Location).Path -DashboardPort 8501 -PostgresPort 5433
```

Ta forma wykonuje odczytany skrypt również w środowisku, które nie pozwala uruchamiać
plików `.ps1`; nie zmienia ExecutionPolicy. Jeśli pliki skryptów są dozwolone,
równoważne polecenie to `& .\scripts\start-demo.ps1 -DashboardPort 8501 -PostgresPort 5433`.
Skrypt tworzy ignorowane `.env.demo` z trzema losowymi hasłami, zachowuje istniejącą
konfigurację, używa projektu `wta-demo` i trwałych named volumes. Nie nadpisuje `.env`.
Wolumen bez konfiguracji powoduje odmowę zgadywania/regeneracji haseł.
Sprawdza porty i kody wyjścia programów. Zajęty port wymaga zmiany parametru;
żaden cudzy proces nie jest zatrzymywany. Po gotowości wypisuje rzeczywisty URL.
Adres oczekiwany przy domyślnych parametrach: `http://127.0.0.1:8501`.

Linux/macOS: `sh scripts/start-demo.sh`; inne porty:
`DASHBOARD_PORT=8502 POSTGRES_PORT=5434 sh scripts/start-demo.sh`.
Odmowa bind portu jest błędem startu; skrypt nie zatrzymuje innych usług.

## Jeden pipeline

```powershell
.\.venv\Scripts\python.exe -m wroclaw_transit_analytics demo --json
.\.venv\Scripts\python.exe -m wroclaw_transit_analytics run --raw-manifest 'C:\dane\raw\manifest.json' --start-date 2026-10-07 --end-date 2026-10-08 --json
```

Python wymaga jawnego DATABASE_URL roli loadera. Compose pipeline ma własne poświadczenia
i katalog `/work`. run wywołuje istniejące prepare, load_silver i analyze. Demo dodaje
istniejący generator i zakres 2026-10-01…2026-10-07. Raport JSON podaje faktyczne ścieżki,
identyfikatory i status każdego etapu. Błąd zatrzymuje dalsze kroki; zakończone pliki/import
pozostają. To osobne transakcje i publikacje plików. Powtórzenie wykorzystuje idempotencję.
Odświeżenie UI wykonuje wyłącznie SELECT.

## Reader i upgrade istniejącego wolumenu

Dodaj lokalnie WTA_READER_PASSWORD do konfiguracji Compose. Administrator wykonuje:

```powershell
docker compose --profile tools build
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
docker compose run --rm initializer db-init --loader-role wta_loader --reader-role wta_reader --json
if ($LASTEXITCODE -ne 0) { throw 'Init/grants failed' }
docker compose up -d --wait dashboard
if ($LASTEXITCODE -ne 0) { throw 'Dashboard failed' }
```

Reader powstaje podczas db-init również w istniejącej bazie, bez ponownego entrypoint
Postgresa i bez migracji 003. Migracje 001/002 oraz SQL KPI są niezmienione.
Istniejący reader zachowuje hasło. Obca rola z uprzywilejowanymi atrybutami,
członkostwem lub prawami zapisu powoduje odmowę grantowania. Reader ma USAGE meta/gold
i SELECT meta.datasets/meta.analyses oraz dziewięciu potrzebnych relacji gold.
Gold.active_services nie jest czytane przez UI i nie otrzymuje grantu. Nie ma USAGE silver, członkostw,
superuser ani CREATE chronionych schematów. Testy naprawdę próbują zabronione
INSERT/UPDATE/DELETE/TRUNCATE/ALTER/DROP/CREATE poza transakcją READ ONLY.

UI wymaga osobnego READONLY_DATABASE_URL, sprawdza current_user=wta_reader i major 17.
DSN musi zawierać host, dbname, user=wta_reader i własne password; port domyślnie 5432.
Nie używa DATABASE_URL ani hasła z PGPASSWORD. Każdy odczyt zamyka własną transakcję READ ONLY, z timeoutem 15 s
i lock timeoutem 3 s. Cache ma TTL 60 s i limity 64/128 wpisów; klucz obejmuje hash
źródła DB (bez DSN), dataset, analizę, daty i filtry. „Odśwież dane” czyści cache.
Błąd nie jest cache'owany jako pusty sukces. Serwer ogranicza widoki do 20 000 wierszy;
przekroczenie daje błąd, nie częściowe KPI. Top 20 rankingu nie ogranicza populacji KPI.
Dashboard nie czyta silver.stop_times.

## Widoki i poprawność

Wybierasz jeden snapshot i jedną kompletną analizę wta-gold-v1. Daty pochodzą z analizy
i mogą być jej domkniętym podzakresem. Zmiana kontekstu resetuje filtry. Przegląd sumuje
rozłączne liczniki; linie liczy DISTINCT w całym okresie. Obsługiwane punkty to odwiedzone
stop_id z service_span; katalog zawiera też inne typy. Brak analizy nie daje zerowych KPI.

Widok linii wybiera tekstowe route_id/stop_id i źródłowy direction_id. Nazwy nie scalają ID.
„Niepodany” oznacza NULL, oddzielnie od wszystkich i 0. Nie pokazujemy trip_count całej linii
jako KPI punktu/kierunku. Pokrycie grupy pochodzi z service_span. Medianę/p90 pokazujemy
per dzień i kierunek. Procenty mają zgodne liczniki i mianowniki; mianownik 0 daje wynik
nieokreślony. Poza obwiednią NULL jest nieznane, w pokrytym dniu zero jest zerem.
Godziny >24 i bardzo duże mają rzadką oś tylko obserwowanych kategorii.

Dane/jakość oddziela pobranie, import, analizę i statyczną jakość silver od pokrycia gold.
Syntetyczne dane mają stałą etykietę. Brak data_kind nie potwierdza realnego źródła.
GTFS nie jest HTML/JavaScript. Shapes/realne trasy na mapie, realtime, punktualność
i pasażerowie są poza zakresem.

## Dowody

AppTest sprawdza widoki, filtry, reset, cache, puste dane i błędy. PostgreSQL sprawdza
ręczne liczby, izolację i ACL. Compose/Chromium sprawdza trzy widoki, rzeczywiste wartości,
filtry, reload i restart z zachowaniem gold. Osobny workflow real-gtfs uruchamia się tylko
po zmianie `.github/real-e2e-request.json` na feat/dashboard-demo; nie pobiera danych
podczas zwykłego pytest/push/PR i nie wymaga merge ani workflow_dispatch z main.
Dowody zawierają SHA, manifesty, SELECT i screenshoty; duże dane i hasła są wykluczone.
