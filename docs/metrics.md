# Rozkładowe KPI — wta-gold-v1

Program rozwija kalendarze usług i liczy agregaty SQL na PostgreSQL 17. To analityka
deklarowanego rozkładu: nie pomiar rzeczywistych odjazdów ani czasu oczekiwania pasażera.
Silver i jego tożsamość pozostają bez zmian. Dashboard należy do Sprintu 04.

## Dni usług, kursy i czasy

Zakres start-date/end-date jest obowiązkowy i obustronnie domknięty. Dzień usługowy
ma aktywne identyfikatory z calendar według dat i właściwej flagi weekday; calendar_dates
type=1 dodaje, type=2 usuwa. UNION zapobiega podwajaniu dodania aktywnej usługi.
Kalendarz tylko calendar_dates działa bez domyślania tygodniowego rozkładu lub świąt.
silver.services jest wyłącznie katalogiem ID, nie kalendarzem dni.

Kurs to `(dataset_id, service_date, trip_id)`. Liczba stop_times nie mnoży liczby kursów.
Wizyta przystanku ma dodatkowo stop_sequence; dwa odwiedzenia tego samego stop_id
w jednym kursie to dwie obserwacje. Wszystkie dane i katalogi ogranicza dataset_id.
Punkty stop_daily to platformy location_type=0, nie scalone nazwy/stacje.

Czas jest parą service_date + seconds z silver, bez timestamp wall-clock/UTC.
23:50=85800, 25:10=90600. service_hour to całkowite `departure_seconds / 3600`,
zatem godzina 25 pozostaje 25. BIGINT może dawać bardzo duże godziny; siatka godzin
nie jest rozwijana do maksimum. Oryginalny tekst czasu jest nadal w silver.
Przy DST nie dodajemy sekund do lokalnej północy. agency_timezone jest kontekstem
źródła (np. Europe/Warsaw), bez nowej interpretacji stref/czasu rzeczywistego.

## Relacje i filtry

W każdej relacji trwałej klucz obejmuje analysis_id i dataset_id; niżej podano dalszy grain.
Direction NULL zostaje NULL/niepodany. 0 i 1 to kody źródłowe, nie kierunki geograficzne.
UNIQUE NULLS NOT DISTINCT chroni grupy z niepodanym kierunkiem.

| Relacja gold | Dalszy grain | Definicja |
| --- | --- | --- |
| analysis_days | service_date | domena wszystkich żądanych dni; stan kalendarza, aktywne usługi i instancje kursów |
| active_services | service_date, service_id | aktywny kalendarz po wyjątkach |
| route_daily | service_date, route_id | COUNT instancji trips, niezależny od dostępności czasu |
| stop_daily | service_date, stop_id | liczba regularnych znanych odjazdów i COUNT(DISTINCT route_id) w tym samym filtrze |
| route_stop_hourly | service_date, route_id, stop_id, direction_id, service_hour | znane regularne odjazdy; licznik przybliżonych |
| route_stop_headways | service_date, route_id, stop_id, direction_id | odjazdy, odstępy, avg/median/p90 w sekundach |
| service_span | service_date, route_id, stop_id, direction_id | min/max znanej sekundy regularnego odjazdu i liczniki pokrycia grupy |
| coverage_daily | service_date | mianowniki, wykluczenia, braki czasu i odsetki dla aktywnych instancji |
| route_catalog / stop_catalog | route_id / stop_id (bez analysis_id) | widoki statycznego silver tego samego datasetu, nazwy, typy i kontekst |

Regularny znany odjazd: `pickup_type=0 AND departure_seconds IS NOT NULL`.
pickup_type=1 jest wykluczone; 2/3 to osobna grupa na żądanie z oddzielnymi licznikami.
Ostatniego sequence nie wykluczamy automatycznie. Brak czasu pozostaje null i nie jest
interpolowany. timepoint=0 oznacza przybliżenie źródłowe, także gdy czas jest znany.

## Pokrycie, zera i sparse tables

Przyjęta obwiednia to MIN/MAX z calendar.start/end oraz calendar_dates.date.
Nie dowodzi ważności całego feedu ani danych na każdy dzień wewnątrz. Każdy żądany
dzień ma własne calendar_covered i coverage_state. Nie ma jednego boolean dla zakresu.

- within-calendar-envelope: dni bez aktywnych kursów mają potwierdzone według tej
  metody zero; ograniczona siatka dat × katalog linii/platform wypełnia zera daily.
- outside-calendar-envelope: counts daily są NULL/unknown, nie pozorne zero.
- W calendar_dates-only dzień w obwiedni bez dodanej usługi nie ma aktywnych usług.
- Godziny są rzadkie: brak wiersza w pokrytym dniu oznacza brak znanych regularnych
  odjazdów w tej grupie/godzinie; może istnieć brak czasu lub wykluczenie pickup.
  Rozstrzygają coverage_daily/service_span. Poza obwiednią brak wiersza nie dowodzi zera.
- Headways/span mają tylko grupy odwiedzone przez aktywne kursy. Grupa bez znanego
  regularnego czasu ma 0 obserwacji, NULL min/max/statystyki, zachowane mianowniki.

coverage_daily liczy stop_times rozwinięte **wyłącznie na aktywnych żądanych dniach**.
Kolumny total_events, known/missing_arrivals, known/missing_departures, regular_events,
regular_known/missing_departures, no_pickup_events, on_request_events, pickup_type_2/3_events,
exact/approximate_timepoint_events i approximate_regular_departures są licznikami zdarzeń.
Ratios to znane arrivals/total_events, departures/total_events i regular_known/regular_events.
Mianownik 0 daje NULL; poza obwiednią liczniki i ratios również NULL.
Sumaryczne coverage w meta.analyses opisuje znaną część wybranego zakresu; przy całości
poza obwiednią total_events jest NULL. Pokrycie per dzień pozostaje w gold.
source_context.static_silver_time_coverage to osobny statyczny raport silver,
z innym mianownikiem, nigdy pokrycie aktywnych dni tej analizy.

## Headways, span i agregowalność

LAG liczymy po pełnym dniu/grupie `(dataset, date, route, stop, direction)`.
Sortowanie: departure_seconds, trip_id, stop_sequence. Granica godziny nie resetuje LAG.
Jedna obserwacja daje 0 odstępów i NULL statystyki. Odjazdy równoczesne pozostają różnymi
zdarzeniami i tworzą rzeczywisty odstęp 0. Nie ma dedup według samej sekundy/stop_id.

`avg_seconds = SUM(gap)/COUNT(gap)` (PostgreSQL numeric).
Median i p90 to percentile_cont(0.5/0.9), interpolacja liniowa na rzeczywistych odstępach;
PostgreSQL zwraca double precision, więc te statystyki są przybliżone zmiennoprzecinkowo.
Sekundy źródłowe, first/last, godziny, sekwencje i counts zachowują BIGINT.
Nie stosujemy 3600/count ani headway/2 jako rzeczywistego oczekiwania pasażera.

Przykład ręczny: R1/platforma 0001/kierunek 0, odjazdy 07:50, 08:10, 08:10, 08:40.
Czwarta wizyta jest powrotem pierwszego kursu na tę samą platformę.
Odstępy: 1200, 0, 1800 s; avg=1000, median=1200, p90=1680.
Hourly: godzina 7 → 1, godzina 8 → 3. Kursy R1 są 3, nie 4 ani count stop_times.
W scenariuszu 12 zdarzeń: 11 znanych odjazdów; 9 regularnych, 8 regularnych znanych,
1 no-pickup i 2 on-request; ratio znanych zwykłych to 8/9. Jedno brakujące zdarzenie
ma timepoint=0; drugie przybliżone ma znany czas. Testy wartości są niezależne od SQL KPI.

Trip_count i event counts można sumować po rozłącznych dniach w ramach definicji.
Distinct linii nie sumuj po dniach; wymaga DISTINCT dla okresu. Median/p90 nie uśredniaj.
AVG okresu wymaga wszystkich odstępów lub ważenia ich counts, z ustaloną definicją
granic dni. Pierwszy/ostatni znany odjazd przy brakach czasu nie gwarantuje pełnego span.
Grupy route/stop/direction mogą łączyć warianty tras; brak porównania przebiegu shapes.

## Capabilities i granice wykonania

quantitative_gold_supported musi być true; dodatnie frequencies.row_count powoduje
UNSUPPORTED_FREQUENCIES i brak nowego gold. Inne niespełnione wymagania powodują
UNSUPPORTED_CAPABILITIES. flexible_service_supported=false jest informacją o profilu
silver i samo w sobie nie blokuje poprawnego datasetu. Ekspansja frequencies nie jest v1.

Domyślne limity: 31 dni, 5 000 000 rozwiniętych zdarzeń/instancji, 5 000 000 wierszy
daily grid i 120 s dla pojedynczej instrukcji SQL (w tym oczekiwania na lock).
CLI pozwala jawnie je podnieść. max-days ma sufit 3660, timeout 3600 s.
Przed joinem stop_times SQL sumuje per-trip counts aktywnych instancji oraz rozmiar grid.
LIMIT_EXCEEDED i TIMEOUT nie publikują częściowego wyniku. Nie ma pełnego route × stop ×
direction × hour, ani trwałej tabeli wszystkich rozwiniętych zdarzeń. Tabele robocze TEMP
są lokalne dla połączenia i kończą życie wraz z transakcją. ANALYZE aktualizuje ich statystyki.

## Idempotencja i upgrade

analysis_id to `analysis_` + SHA-256 compact JSON listy
`[dataset_id, start_date ISO, end_date ISO, metrics_version]` w UTF-8.
metrics_version=wta-gold-v1. Zmiana definicji KPI wymaga nowej metrics_version.
meta.analyses zachowuje fingerprint źródła i SHA-256 reguł pakietowych SQL.
Inne reguły/fingerprint/parametry pod istniejącym ID dają CONFLICT, nie stary sukces.
Limity wykonawcze nie zmieniają identity; zapisane są pierwsze użyte limity.
Advisory lock z pierwszych 8 bajtów SHA-256 analysis_id (signed BIGINT), unikalność
i jedna transakcja chronią równoległość. Powtórzenie daje ALREADY_ANALYZED.
Żadne polecenie nie usuwa innych analiz ani silver.

Nowa 002_gold jest dopisywana przez dotychczasowy db-init. 001_warehouse i checksum
pozostają nienaruszone, również przy upgrade bazy z datasetem. Administrator musi
ponownie wykonać db-init --loader-role wta_loader: grants rozszerzają USAGE gold,
SELECT meta.migrations oraz SELECT/INSERT meta.analyses/gold. Zwykła rola nie dostaje
UPDATE/DELETE/TRUNCATE, CREATE danych, superuser/createdb/createrole. TEMP jest uprawnieniem
w dedykowanej bazie, nie CREATE w schematach silver/gold. Runtime SQL jest zasobem wheel/obrazu.

## Polecenia

Repozytorium/gałąź: `C:\projekty\wroclaw-transit-analytics`, `feat/transit-analytics`.
Najpierw uruchom bazę i zainicjalizuj/upgrade zgodnie z [runtime](postgres-runtime.md).

```powershell
Set-Location C:\projekty\wroclaw-transit-analytics
docker compose --profile tools build
if ($LASTEXITCODE -ne 0) { throw "Build failed" }
docker compose up -d --wait postgres
if ($LASTEXITCODE -ne 0) { throw "Database startup failed" }
docker compose run --rm initializer db-init --loader-role wta_loader --json
if ($LASTEXITCODE -ne 0) { throw "Upgrade/grants failed" }
docker compose run --rm --entrypoint python pipeline /app/scripts/compose_smoke.py
if ($LASTEXITCODE -ne 0) { throw "Demo load/analytics failed" }
```

To pełne syntetyczne demo; skrypt wypisuje rzeczywiste dataset_id, analysis_id,
counts i wybrane SELECT-y. Nie pobiera miejskich danych ani nie udaje ich wyników.
Istniejący realny manifest można idempotentnie załadować:

```powershell
docker compose run --rm pipeline db-load --silver-manifest /input/silver/gtfs/20261007T124031398819Z_07856434a78f4eaa8bf92916d05cea09/manifest.json --json
if ($LASTEXITCODE -ne 0) { throw "Real silver load failed" }
```

Przed realną analizą odczytaj obwiednię quality.json istniejącego silver. Nie używaj
dzisiejszej daty jako automatycznego zakresu i nie wnioskuj obecności datasetu w bazie.
Dla jawnego demo, którego ID jest stałe dla sample-data v1, lokalny Python:

```powershell
$env:DATABASE_URL = "host=127.0.0.1 port=5433 dbname=wta user=wta_loader"
$passwordInput = Read-Host "Hasło wta_loader" -AsSecureString
$env:PGPASSWORD = [System.Net.NetworkCredential]::new('', $passwordInput).Password
$analysis = (& .\.venv\Scripts\python.exe -m wroclaw_transit_analytics analytics --dataset-id gtfs_e8daea5cce299621c82fb742d73075957bdc8cfb3ec395fd5b71f9a802c040d6 --start-date 2026-10-01 --end-date 2026-10-07 --json) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "Analytics failed" }
$analysis | Format-List
$analysis.analysis_id
Remove-Item Env:PGPASSWORD
```

Python nie ładuje .env. Compose odczytuje go do interpolacji; hasła pozostają lokalne.
Help, błędne daty i limity nie wymagają połączenia. Błędy bazy są redagowane na stderr.
SELECT z ID wypisanym przez CLI (w psql stosuj własną zmienną analysis_id):

```sql
SELECT service_date, route_id, trip_count, calendar_covered
FROM gold.route_daily WHERE analysis_id = :'analysis_id' ORDER BY service_date, route_id;
SELECT * FROM gold.coverage_daily WHERE analysis_id = :'analysis_id' ORDER BY service_date;
SELECT service_date, route_id, stop_id, direction_id, departure_count, interval_count,
       avg_seconds, median_seconds, p90_seconds
FROM gold.route_stop_headways WHERE analysis_id = :'analysis_id' ORDER BY 1,2,3,4;
```

CI uruchamia offline, prawdziwe PostgreSQL 17 testy z upgrade/rollback/równoległością
i Compose E2E z SELECT-ami oraz zachowaniem gold po restarcie. Jeden benchmark ma jawnie
syntetyczne 1000 trips × 20 stop_times × 7 dni = 140 000 zdarzeń. Artefakt zawiera zmierzony
czas oraz EXPLAIN (ANALYZE, BUFFERS) okna/kwantyli; nie jest obietnicą wydajności realnego feedu.
Status Windows i realnego load/gold znajduje się oddzielnie w raporcie runu.

Sprawdzone źródła: [GTFS Schedule](https://gtfs.org/documentation/schedule/reference/),
[źródłowa specyfikacja GTFS](https://raw.githubusercontent.com/google/transit/master/gtfs/spec/en/reference.md),
[PostgreSQL windows](https://www.postgresql.org/docs/17/functions-window.html),
[aggregates](https://www.postgresql.org/docs/17/functions-aggregate.html),
[NULLS NOT DISTINCT](https://www.postgresql.org/docs/17/ddl-constraints.html),
[locks](https://www.postgresql.org/docs/17/explicit-locking.html),
[Psycopg transactions](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).
