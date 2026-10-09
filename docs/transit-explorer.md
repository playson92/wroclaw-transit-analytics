# Mapa, linie i konkretne kursy

Pierwszy ekran „Mapa i linie” przegląda jeden zaimportowany snapshot GTFS. Rzeczywisty
dataset ma pierwszeństwo przed demo. Filtry: dzień usługi, rodzaj transportu, wyszukiwana
linia, kierunek/wariant, konkretny kurs i przystanek. Numery linii pochodzą z GTFS;
niejednoznaczne oznaczenia zawierają też operatora, agency_id i route_id.

Mapa wyróżnia wybrany punkt i pokazuje shapes konkretnego kursu. Kliknięcie punktu
otwiera jego odjazdy; lista przystanków stanowi alternatywę klawiaturową. Tabela kursu
zachowuje każdą wizytę stop_sequence, tekstowe ID, godziny powyżej 24:00 i brak czasu.
Widok przystanku obejmuje wybraną linię i wszystkie jej aktywne warianty w tym dniu,
z oznaczeniami wsiadania i czasów przybliżonych. Rozkładowe vehicle_id/brigade_id
są metadanymi źródła, nie potwierdzeniem numeru bocznego ani pomiarem GPS.

## Model i aktualizacja bazy

Migracja **003_explorer.sql** dodaje schemat `explorer`, indeksy i widoki właściciela
nad niezbędnymi kolumnami silver. Nie zmienia zastosowanych migracji 001/002, kontraktu
silver, tożsamości datasetu, źródłowych manifestów ani definicji gold KPI. Reader otrzymuje
SELECT/USAGE explorer i dotychczasowe prawa gold/meta; nadal nie ma USAGE silver ani
INSERT/UPDATE/DELETE/DDL. Loader może tylko dopisywać geometrię.

Aktywność usług wykorzystuje dokładny SELECT z istniejącego `analytics/sql/services.sql`:
kalendarz tygodniowy plus dodania calendar_dates, następnie wyjątki usuwające. Przeglądarka
nie wymaga analizy gold dla każdego dnia. Data poza kalendarzem daje brak aktywnych kursów.
Wariant odróżnia kierunek, headsign, źródłowy wariant/shape i uporządkowaną listę stop_id;
różne kolejności punktów nie są łączone w jedną trasę.

`explorer-import --raw-manifest PATH` korzysta z istniejącej ponownej walidacji raw,
weryfikuje SHA-256 i wymaga załadowanego silver o tej samej tożsamości. Czyta shapes.txt
strumieniowo z ZIP, z limitami rekordów/dekompresji oraz 2 mln punktów, bez ekstrakcji.
COPY i metadane importu są jedną transakcją. Klucz geometrii obejmuje dataset_id,
source_sha256, shape_id i shape_pt_sequence. Powtórny import zachowuje zawartość;
błędne współrzędne, duplikaty sekwencji lub inny snapshot nie publikują częściowego wyniku.
ZIP nie jest czytany podczas odświeżenia UI. Brak shapes daje same przystanki, bez
domyślnych prostych linii udających przebieg ulic.

Odczyty są parametryzowane, w zamykanych transakcjach READ ONLY i z timeoutem 15 s.
Limity: 2000 linii, 500 wariantów, 2000 kursów wariantu, 1000 wizyt wybranego kursu,
20 000 punktów jednej geometrii i 5000 odjazdów wybranego punktu/linii/dnia.
Przekroczenie jest jawnym błędem, bez milczącego obcięcia. Cache rozkładu ma TTL 60 s,
limit wpisów i klucz źródła/datasetu/dnia/linii/wariantu/kursu/punktu. „Odśwież dane”
czyści cache rozkładu. Całe stop_times nie jest wysyłane do przeglądarki.

## Izolowane uruchomienie obok dotychczasowego demo

Kontekst lokalnego Docker Desktop: desktop-linux. Poniżej projekt `wta-explorer` ma
własne named volumes, port dashboardu 8502 i PostgreSQL 5434. Projekt `wta-demo`
na 8501/5433 pozostaje niezależny. Użyj istniejącej `.env.demo`; nie kopiuj ani nie
nadpisuj haseł. Świeże środowisko może najpierw utworzyć ją istniejącym start-demo.ps1.

```powershell
Set-Location 'C:\projekty\wroclaw-transit-analytics'
$env:DOCKER_CONTEXT = 'desktop-linux'
$env:DASHBOARD_PORT = '8502'
$env:POSTGRES_PORT = '5434'
$env:SILVER_DIR = 'C:/projekty/wroclaw-transit-analytics/data/silver'
$env:RAW_DIR = 'C:/projekty/wroclaw-transit-analytics/data/raw'
$compose = @('compose','--project-name','wta-explorer','--env-file','.env.demo','-f','compose.yaml')
docker @compose --profile tools build
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
docker @compose up -d --wait postgres
if ($LASTEXITCODE -ne 0) { throw 'Postgres failed' }
docker @compose run --rm initializer
if ($LASTEXITCODE -ne 0) { throw 'Migration/grants failed' }
```

Załaduj **rzeczywistą ścieżkę** istniejącego zweryfikowanego silver. Polecenie nie pobiera
nowego feedu. Dla snapshotu sprawdzonego w tym zadaniu:

```powershell
docker @compose run --rm pipeline db-load --silver-manifest /input/silver/gtfs/20261007T124031398819Z_07856434a78f4eaa8bf92916d05cea09/manifest.json --json
if ($LASTEXITCODE -ne 0) { throw 'Load failed' }
docker @compose run --rm pipeline explorer-import --raw-manifest /input/raw/gtfs/2026-10-04/20261004T211121447987Z_bedf8372967c4777a7b2c097fe9dc26b/manifest.json --json
if ($LASTEXITCODE -ne 0) { throw 'Geometry import failed' }
docker @compose run --rm pipeline analytics --dataset-id gtfs_00a11db35a3dff8c854a5bdba9ee73842ff795561a9a50480119e7d6fb799546 --start-date 2026-10-03 --end-date 2026-10-09 --json
if ($LASTEXITCODE -ne 0) { throw 'Analytics failed' }
docker @compose run --rm pipeline demo --json
if ($LASTEXITCODE -ne 0) { throw 'Demo failed' }
docker @compose up -d --wait dashboard
if ($LASTEXITCODE -ne 0) { throw 'Dashboard failed' }
```

Adres po sukcesie: **http://127.0.0.1:8502**. Ponowne otwarcie działającej aplikacji
nie wymaga importu; do restartu służy `docker @compose up -d --wait dashboard` w tej
samej konfiguracji. Nie używaj down -v/prune. Zajęty port wymaga zmiany zmiennej portu;
nie zatrzymuj innej aplikacji. Porty są publikowane wyłącznie na 127.0.0.1.

Snapshot pobrano **2026-10-04 21:11:22 UTC** z [oficjalnego ZIP-a](https://open-data.cui.wroclaw.pl/hdb/download/141/).
Obwiednia kalendarza: **2026-10-03–2026-10-18**, 137 linii, 2486 punktów katalogu,
42 643 statyczne szablony kursów i 363 002 punkty shapes. To historyczny snapshot;
nie zweryfikowano jego zgodności z dzisiejszą ofertą. Szczegóły kursów nie są pomiarem
faktycznego wykonania przewozu. Demo pozostaje wyraźnie syntetyczne.

## Podkład mapy

Pydeck 0.9.3 i Streamlit 1.57 obsługują wybór obiektów bez aktualizacji zależności.
Opcjonalny raster [OpenStreetMap](https://www.openstreetmap.org/copyright) ma widoczną
atrybucję. Stosujemy [Tile Usage Policy](https://operations.osmfoundation.org/policies/tiles/),
sprawdzoną 2026-10-09: ograniczona pojemność, brak SLA, poprawny Referer i standardowy
User-Agent przeglądarki, jej cache HTTP; bez proxy, pobierania masowego i prefetch/offline.
Nie jest to obietnica darmowej usługi bez limitów. „Podkład OpenStreetMap” wyłącza
zewnętrzny raster, pozostawiając własną geometrię i punkty. Awaria podkładu nie usuwa tabel.
Automatyczne testy przeglądarki blokują żądania kafelków zamiast obciążać publiczny serwer.

## Pozycje pojazdów — stan integracji

Osobny adapter odczytuje [eksport JSON CUI](https://open-data.cui.wroclaw.pl/hdb/db/14?download=json)
oraz [metadane pozycji](https://open-data.cui.wroclaw.pl/hdb/metadane/json/51/).
Nie jest to GTFS Realtime. Przełącznik „Obserwacje pojazdów z CUI” jest domyślnie
wyłączony. Po włączeniu nakłada oznaczone szare obserwacje numeru wybranej linii
na snapshot z ostrzeżeniem o oddzielnym źródle i dacie; nie wiąże ich z trip_id.
Zakładka szczegółów „Pojazdy” pokazuje status, czas pobrania UTC, źródłowe czasy pozycji,
wiek (tylko dla jawnej strefy), numery boczne, duplikaty i liczbę odrzuconych rekordów.

Próba 2026-10-09: HTTP 200, 984 rekordy, wszystkie Data_Aktualizacji bez offsetu/strefy;
Nr_Boczny -1 i 9552 były zduplikowane. Nie znaleziono potwierdzenia strefy czasu w
oficjalnych opisach. Nie przypisujemy Europe/Warsaw na podstawie samego podobieństwa zegarów.
Eksport wskazał w `meta` „Rozkład jazdy transportu publicznego” i CC0 1.0, podczas gdy
dedykowane metadane pozycji wskazały poprawny tytuł, ale `licencja=null`.
**Aktualność i warunki użycia pozycji pozostają niepotwierdzone; integracja live jest
zablokowana.** Nie przedstawiamy odbioru HTTP jako pomiaru aktualności. MPK również
opisuje [mapę pozycji jako poglądową](https://mpk.wroc.pl/strefa-pasazera/zaplanuj-podroz/mapa-pozycji-pojazdow).

Żądania: tylko stałe oficjalne HTTPS URL, bez przekierowań, timeout 10 s, maksymalnie
2 MiB zdekompresowanego JSON i 10 000 rekordów. Wspólny lock/cache ogranicza próby
do jednej na godzinę na proces, także błędy i przycisk ręcznego odświeżania.
Metadane są sprzeczne co do częstotliwości (10 minut / godzina); wybrano wolniejszą,
bez obietnicy częstotliwości pomiaru. Niepoprawne/niefinitywne współrzędne i (0,0)
są odrzucane. Stare, przyszłe, nieokreślone czasowo lub licencyjnie rekordy nigdy
nie otrzymują etykiety live. Awaria źródła nie wyłącza rozkładu.

## Testowanie

Offline: parser/limity/mock HTTP, strefy/stare pozycje/duplikaty/rate limit oraz AppTest
filtrów, pustego dnia, braku shapes, godzin >24, resetu snapshotu i awarii pozycji.
PostgreSQL: rzeczywiste calendar_dates, powtórne wizyty, rozdzielenie wariantów,
izolacja dwóch snapshotów z tymi samymi ID, idempotencja/rollback geometrii,
aktualizacja 002 → 003 bez zmiany silver/gold i próby odmowy zapisu readera.
Dotychczasowe testy definicji KPI pozostają aktywne.

`tests/ui/test_explorer_browser.py` wybiera przykłady z JSON zapytań SELECT rzeczywistej
bazy, zmienia autobus/tramwaj/wariant, sprawdza konkretne czasy i kolejność, klika punkt
na canvasie, sprawdza odjazdy, brak kursów, przełączenie datasetu i demo bez shapes.
Zapisuje prawdziwe screenshoty. `WTA_BROWSER_CHANNEL=msedge` używa zainstalowanego
Edge na Windows; CI może pozostawić Chromium. Testy awarii i starych pozycji używają
mocków; rzeczywista próba eksportu jest osobnym dowodem.
