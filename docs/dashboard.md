# Dashboard, explorer i odczyt bazy

Aplikacja ma cztery widoki we wspólnym pasku: **Mapa i kursy** jako pierwszy ekran,
**Analityka**, **Dane** oraz **O projekcie**. Explorer pokazuje rozkład wybranego snapshotu,
kursy, shapes i przystanki. Analityka czyta wersjonowane agregaty SQL gold.
[Publiczne demo z jedną komendą Compose](../README.md#quick-start-from-a-fresh-download)
jest punktem wejścia bez hostowego Pythona i `.env`.
[Instrukcja startera i pełnych danych](transit-explorer.md) opisuje odrębny zachowany tryb.

## Uruchomienie

Docker z lokalnym silnikiem Linux i Compose; obraz zawiera Python 3.12 oraz
Streamlit 1.57. Podstawowy pakiet i CLI `--help` nie wymagają Streamlita ani bazy.

Publiczne demo uruchamia `docker compose -f compose.demo.yaml up --build -d --wait`.
Autonomiczny projekt `wta-portfolio` używa pakowanej pochodnej próbki GTFS, własnych
trwałych poświadczeń i wolumenów, bez opublikowanego portu bazy. Inicjalizacja,
załadowanie, analiza i geometria kończą się przed startem UI na 127.0.0.1:8504.
Polecenia PowerShell poniżej są zachowaną ścieżką dla innych projektów i pełnego feedu.

```powershell
& .\scripts\start-explorer.ps1
```

Restart obecnego `wta-explorer` zachowuje bazę 5434, dashboard 8502, `.env.demo`
i wolumeny, bez ponownego importu/pobrania. Świeże, osobne demo:

```powershell
& .\scripts\start-explorer.ps1 -Demo -ProjectName wta-explorer-demo -DashboardPort 8503 -PostgresPort 5436
```

Polecenie działa z czystego checkoutu: własna konfiguracja, migracje, pipeline demo,
import geometrii jeśli źródło ma shapes, dashboard. Rzeczywiste dane przekazuje się
jawnie przez `-RawManifest` lub `-GtfsUrl` wraz z zakresem dat; nie wpisuje się dataset_id.

Dotychczasowe `scripts/start-demo.ps1` i `start-demo.sh` pozostają dostępne dla starego
projektu `wta-demo` na 8501/5433. Nowy starter nie przebudowuje go.
Zasady lokalnego Restricted/Process RemoteSigned opisuje [instrukcja PowerShell](transit-explorer.md#polityka-powershell).

## Pipeline i trwałość

`run --raw-manifest PATH --start-date DATE --end-date DATE --json` wywołuje istniejące
prepare, load_silver i analyze. `demo --json` dodaje jawnie syntetyczny generator
i zakres 2026-10-01–2026-10-07. JSON zwraca faktyczne manifesty, identyfikatory
i statusy etapów. Błąd zatrzymuje dalsze kroki, bez usuwania opublikowanych danych.
Granice plików/importu/analizy pozostają odrębnymi publikacjami i transakcjami.
Ponowienie wykorzystuje idempotencję; odświeżenie UI wykonuje SELECT.

Named volumes zachowują bazę i pipeline_work po restarcie/stop.
Starter zachowuje istniejącą konfigurację i hasła; wolumen bez konfiguracji powoduje
odmowę ich zgadywania. Nie używaj down -v/prune do uruchamiania.

## Reader i migracje

`db-init` stosuje wersjonowane 001/002/003 i przyznaje role w istniejącej własnej bazie.
Nie zmienia zapisanych migracji ani reguł `wta-gold-v1`. Rola `wta_reader` zachowuje
istniejące hasło. Obca rola z uprzywilejowanymi atrybutami, członkostwem lub prawami
zapisu powoduje odmowę grantowania.

Reader ma USAGE meta/gold/explorer i SELECT potrzebnych relacji. Nie ma USAGE silver,
zapisu, DDL, CREATE w chronionych schematach ani superuser. Explorer korzysta z widoków
właściciela nad potrzebnymi kolumnami silver, w tym stop_times; UI nie otrzymuje
bezpośredniego dostępu do tabel silver. Testy ACL próbują rzeczywistych zabronionych
INSERT/UPDATE/DELETE/TRUNCATE/ALTER/DROP/CREATE poza transakcją READ ONLY.

UI wymaga osobnego `READONLY_DATABASE_URL`, sprawdza current_user=wta_reader
i major PostgreSQL 17. Nie zastępuje go DATABASE_URL ani hasłem z PGPASSWORD.
Każdy odczyt zamyka własną transakcję READ ONLY, z timeoutem instrukcji 15 s
i lock timeoutem 3 s. Cache TTL 60 s ma limit wpisów i klucze całego kontekstu,
bez DSN. Błąd nie jest cache'owany jako pusty sukces; limity nie obcinają KPI po cichu.

## Widoki i znaczenie liczb

Explorer uwzględnia calendar/calendar_dates i zależności snapshot → dzień → linia →
wariant → kurs → przystanek. [Jawna polityka resetu i pustych wyborów](transit-explorer.md#polityka-stanu-i-filtrów)
oddziela poprawny dzień bez kursów od daty poza obwiednią oraz brakującego wyboru.
Mapa używa shapes właściwego kursu; czas, ID i powtarzane wizyty są zachowane.

Analityka wybiera kompletną analizę `wta-gold-v1`; zakres dat może być jej domkniętym
podzakresem. Sumuje rozłączne liczniki, a linie liczy DISTINCT w okresie. Obsługiwane
punkty to odwiedzone stop_id z service_span, nie cały katalog. Brak analizy nie daje
zerowych KPI. Top 20 rankingu nie ogranicza populacji KPI.

route_id/stop_id są tekstowe; nazwy nie scalają ID. Kierunek NULL jest oddzielny od
0 i wszystkich kierunków. UI nie pokazuje trip_count całej linii jako KPI punktu.
Median/p90 są dzienne i kierunkowe; nie uśrednia się median ani dziennych DISTINCT.
Mianownik 0 daje wartość nieokreśloną. Poza obwiednią NULL oznacza brak wiedzy,
a zero w pokrytym dniu oznacza zero według reguł analizy.

Dane oddziela pobranie, import, analizę, statyczne silver i pokrycie aktywnych
dni gold. Syntetyczne D1/D2 ma stałą etykietę syntetyczności; portfolio ma stałą
etykietę próbki archiwalnego rozkładu wybranych linii. Historyczny snapshot nie jest
obietnicą aktualnego rozkładu. Eksperymentalne CUI jest domyślnie wyłączone;
punktualność, pasażerowie i ukończony live GPS pozostają poza wydaniem.

## Weryfikacja

AppTest obejmuje tabele, reset i puste stany. PostgreSQL sprawdza ręczne liczniki,
rollback, idempotencję, izolację i ACL. Standardowy Compose/browser CI korzysta
z dwóch jawnie syntetycznych datasetów o rozłącznych kalendarzach i obowiązkowo
sprawdza reset także po następnej interakcji, zmianie widoku oraz odświeżeniu.
Brak wymaganej fixture jest błędem zamiast skip. Test rastera przechwytuje publiczne
żądania i bada piksele technicznego obrazu; test awarii podkładu zachowuje własną mapę.

Osobny test lokalnego Wrocławia korzysta z już zaimportowanego źródła. Zwykłe pytest/PR
nie pobiera GTFS ani CUI. Odbiór Windows/Docker Desktop, rzeczywistych ulic,
czytelności w mniejszym oknie, restartu i świeżego checkoutu ma własne dowody.
Końcowy raport i JUnit są przypisane do testowanych SHA; dawne wyniki są historią.
