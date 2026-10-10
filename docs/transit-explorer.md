# Mapa, linie i konkretne kursy

Publiczną prezentację z małą próbką archiwalnego GTFS uruchamia jeden plik
`compose.demo.yaml`: [quick start](../README.md#quick-start-from-a-fresh-download).
Poniższe instrukcje dotyczą zachowanych starterów oraz trybu jawnego pełnego GTFS;
nie są dodatkowymi krokami wymaganymi do portfolio demo.

Pierwszy ekran **Mapa i kursy** przegląda jeden zaimportowany snapshot GTFS. Panel wyboru
nazywa dane według ich pochodzenia i zapisanego czasu: snapshot GTFS Wrocławia albo
demo syntetyczne. Brak informacji o czasie pozostaje jawny. Pełne dataset_id, hashe,
parametry i metadane są w szczegółach technicznych.

Wybierz dzień usługi, rodzaj transportu, linię, kierunek/wariant i konkretny kurs.
Numery linii pochodzą z GTFS; niejednoznaczne oznaczenia zawierają kontekst operatora
i identyfikatora. Mapa pokazuje **rozkładowy przebieg shapes**, nie GPS pojazdu.
Kliknięcie przystanku otwiera jego odjazdy; lista **Przystanek** umożliwia ten sam wybór
bez myszy. Turkusowe punkty są przystankami kursu, zaznaczony punkt jest pomarańczowy;
osobne obserwacje CUI, po ich włączeniu, są szare.

Tabela kursu zachowuje każdą wizytę stop_sequence, tekstowe ID, godziny ponad 24:00
i brak czasu. Odjazdy obejmują wybraną linię i jej aktywne warianty w wybranym dniu,
z zasadami wsiadania oraz oznaczeniami **Dokładny / Przybliżony**.
**Brak czasu** nie jest przedstawiany jako 00:00. Rozkładowe vehicle_id/brigade_id
są metadanymi źródła, bez potwierdzenia numeru bocznego ani pomiaru GPS.

## Odtwarzalny start

Wymagany lokalny Docker Desktop albo Docker Engine z silnikiem Linux i Compose.
Starter respektuje aktywny lokalny kontekst i odmawia użycia zdalnego endpointu. Nie instaluje narzędzi,
nie zmienia globalnego PATH ani ExecutionPolicy.

Z katalogu repozytorium uruchom istniejącą instancję:

```powershell
& .\scripts\start-explorer.ps1
```

Domyślne parametry: `-ProjectName wta-explorer -DashboardPort 8502 -PostgresPort 5434`,
konfiguracja `.env.demo`. Restart buduje dashboard i uruchamia własne usługi;
**nie wykonuje init, download, prepare, load ani importu geometrii**.
Używa istniejących haseł i wolumenów. Brak konfiguracji lub istniejącej bazy daje
konkretny błąd zamiast zgadywania haseł. Stare `wta-demo` na 8501/5433 jest niezależne.

Świeże demo, z czystego checkoutu:

```powershell
& .\scripts\start-explorer.ps1 -Demo -ProjectName wta-explorer-demo -DashboardPort 8503 -PostgresPort 5436
```

To odrębny projekt i named volumes. Konfiguracja `.env.wta-explorer-demo` powstaje
tylko przy pierwszym uruchomieniu. Starter wykonuje migracje oraz istniejący pipeline
`demo`, przekazuje zwrócony raw manifest do `explorer-import` i uruchamia dashboard.
Demo nie ma shapes; status ich braku jest prawidłowy, mapa pokazuje przystanki.
Dla 2026-10-01–2026-10-07 oczekiwane KPI to **16 instancji kursów, 25 regularnych
znanych odjazdów, 2 aktywne linie i 3 obsługiwane punkty**.

Rzeczywisty, już pobrany snapshot — jawny raw manifest:

```powershell
& .\scripts\start-explorer.ps1 -RawManifest 'C:\dane GTFS\raw\manifest.json' -StartDate 2026-10-03 -EndDate 2026-10-09
```

Nowe pobranie wyłącznie na jawne polecenie, ze wskazanym adresem oficjalnego ZIP-a:

```powershell
& .\scripts\start-explorer.ps1 -GtfsUrl '<jawny HTTPS URL ZIP-a z open-data.cui.wroclaw.pl>' -StartDate 2026-10-03 -EndDate 2026-10-09
```

URL wybierz z linku **Pobierz** w [oficjalnym katalogu](https://open-data.cui.wroclaw.pl/hdb/ft/6/);
daty muszą odpowiadać temu konkretnemu źródłu. Tryby `-Demo`, `-RawManifest`
i `-GtfsUrl` są wzajemnie wykluczające. Starter nie wybiera „latest”.
Prepare/load/analytics wykorzystują istniejący `run`; wynik przekazuje rzeczywiste
dataset_id i ścieżki do importu geometrii. Nie trzeba ręcznie przepisywać identyfikatorów.
Powtórzony import i analiza zachowują idempotencję, bez regenerowania haseł.

Wspólne parametry to także `-EnvFile '<własny plik konfiguracji>'` i
`-RepoRoot 'C:\projekty ze spacjami\wroclaw-transit-analytics'`.
Porty można zmienić parametrami; zajęty port jest błędem, żaden cudzy proces nie jest
zatrzymywany. Usługi publikują wyłącznie 127.0.0.1. Rzeczywisty adres pojawia się po
gotowości bazy i dashboardu; HTTP health jest sprawdzeniem startu, a nie testem całego UI.
Nie używaj `down -v` ani `prune` do restartu.

### Polityka PowerShell

Najpierw sprawdź `Get-ExecutionPolicy -List`. Jeśli jedyną blokadą jest lokalne
`Restricted`, a `MachinePolicy` i `UserPolicy` są `Undefined`, w tej samej sesji
możesz wykonać `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned`,
a następnie zwykłe polecenie sprawdzonego startera. Nie obniżaj `AllSigned`,
nie obchodź polityk administratora i nie zmieniaj CurrentUser/LocalMachine.
Starter sam nie zmienia żadnej polityki.

## Polityka stanu i filtrów

Nowa sesja lub zmiana snapshotu wybiera pierwszy dzień jego obwiedni kalendarza.
To jawna data początkowa archiwum, bez wyszukiwania dnia z usługami. Resetuje rodzaj
transportu do **Wszystkie**, wyszukiwanie do pustego oraz linię, wariant, kurs, punkt
i szczegóły do zgodnych pierwszych wyborów; CUI wraca do wyłączonego. Linia początkowa
jest pierwszą aktywną linią tego dnia, a gdy usług nie ma — linią z katalogu.
Preferencja włączenia podkładu pozostaje zachowana.

Kolejne interakcje używają daty widocznej w przeglądarce, stanu sesji i zapytań tego samego
snapshotu. Wybrany przez użytkownika dzień poza obwiednią nie jest automatycznie
przestawiany; ma komunikat o zakresie. Poprawny dzień bez usług pozostaje takim dniem.
Wyczyszczona data lub lista wyboru daje instrukcję uzupełnienia, bez błędnego zapytania.

Przejście Mapa i kursy → Analityka → Dane → O projekcie → Mapa i kursy zachowuje kontekst tego snapshotu.
Odświeżenie strony lub nowa karta tworzy nową sesję: domyślny snapshot preferuje dane
realne przed demo, następnie najnowszy zapisany import w tej kategorii. To wybór spośród
danych już w bazie, bez pobierania ani automatycznego resolvera „latest” źródła.

## Dane, SQL i geometria

Migracja **003_explorer.sql** dodaje schemat explorer, indeksy i widoki właściciela nad
potrzebnymi kolumnami silver. Nie zmienia zastosowanych 001/002, tożsamości datasetu,
kontraktu silver ani definicji gold KPI. Reader otrzymuje SELECT/USAGE explorer
i dotychczasowe prawa gold/meta; nie ma USAGE silver ani praw zapisu i DDL.

Aktywność usług wykorzystuje reguły istniejącego `analytics/sql/services.sql`:
kalendarz tygodniowy, dodania calendar_dates, następnie wyjątki usuwające. Explorer
nie wymaga analizy gold każdego dnia. Wariant odróżnia kierunek, headsign, źródłowy
wariant/shape i uporządkowane stop_id; różnych przebiegów nie scala w jedną trasę.

`explorer-import --raw-manifest PATH` ponownie weryfikuje raw i jego SHA-256,
wymaga silver tego samego snapshotu i strumieniowo importuje shapes.txt.
COPY i metadane są jedną transakcją. Klucz geometrii obejmuje dataset_id,
source_sha256, shape_id i shape_pt_sequence; błędny lub inny snapshot nie publikuje
częściowego wyniku. ZIP nie jest czytany podczas rerunu UI. Brak shapes daje punkty
bez prostych linii udających przebieg ulic.

Odczyty są parametryzowane, w krótkich transakcjach READ ONLY z timeoutem 15 s.
Limity: 2000 linii, 500 wariantów, 2000 kursów wariantu, 1000 wizyt kursu,
20 000 punktów geometrii i 5000 odjazdów punktu/linii/dnia. Przekroczenie jest błędem,
bez cichego obcięcia. Cache ma TTL 60 s, limit wpisów i pełny kontekst
źródła/datasetu/dnia/linii/wariantu/kursu/punktu; **Odśwież dane** czyści cache rozkładu.

Lokalny snapshot pobrano **2026-10-04 21:11:22.391308 UTC** z oficjalnego ZIP-a.
Jego kalendarz 2026-10-03–2026-10-18 nie potwierdza dzisiejszej oferty.
[Odtwarzalne wnioski SQL](portfolio-case-study.md) dotyczą jawnego zakresu 2026-10-03–09.

## Podkład i eksperymentalne CUI

Opcjonalny raster [OpenStreetMap](https://www.openstreetmap.org/copyright) zachowuje
atrybucję i [Tile Usage Policy](https://operations.osmfoundation.org/policies/tiles/).
Zwykła przeglądarka używa standardowego User-Agent, Referer i cache HTTP; bez proxy,
masowego pobierania, prefetch/offline i obietnicy SLA. Wyłączenie **Podkład OpenStreetMap**
zachowuje własną geometrię i punkty. Niedostępny raster nie usuwa tabel.

Zwykłe testy browser blokują publiczne kafelki albo odpowiadają własnym małym PNG.
Test `RASTER_RENDER_TEST` sprawdza faktyczne piksele syntetycznego rastera, znaczniki
i kliknięcie przystanku. Jego obraz nie jest mapą ulic Wrocławia. Osobny lokalny
`REAL_BASEMAP_CHECK` sprawdza rzeczywisty podkład; dowody nie są zamienne.

Obserwacje z [eksportu CUI](https://open-data.cui.wroclaw.pl/hdb/db/14?download=json)
pozostają eksperymentalne i domyślnie wyłączone. Szare punkty nie oznaczają położenia
„teraz”, nie są GTFS Realtime i nie są przypisywane do trip_id.
Czasy bez potwierdzonej strefy nie dostają domyślnego Europe/Warsaw; warunki danych
pozycji nie są potwierdzone przez metadane GTFS. Awaria eksportu nie blokuje rozkładu.
Istniejące limity, wspólny cache i ostrzeżenia pozostają zachowane, bez rozszerzania live.
