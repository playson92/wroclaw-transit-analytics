# Zakres wydania 0.2.0

Produkt to lokalna przeglądarka rozkładu Wrocławia z mapą, liniami, wariantami,
konkretnymi kursami i przystankami, uzupełniona analityką SQL i odtwarzalnym pipeline'em.
GTFS opisuje rozkład deklarowany, nie wykonanie przewozu ani aktualny GPS.

## Zaimplementowane

- Jawny oficjalny GTFS lub oznaczone demo syntetyczne; raw ZIP, walidacja, manifesty i hashe.
- Strumieniowe bronze i typowane silver Parquet, kontrola jakości i zachowanie pochodzenia.
- PostgreSQL 17, wersjonowane migracje, transakcyjny COPY, izolacja i idempotencja datasetów.
- SQL gold: kalendarze i wyjątki, dzienne instancje kursów, regularne znane odjazdy,
  headways, service spans i pokrycie danych; definicje `wta-gold-v1` pozostają zachowane.
- Streamlit: Mapa i linie, Analityka oraz Dane i jakość, z osobnym readerem bez praw zapisu.
- Geometria shapes właściwego kursu, przystanki i odjazdy; tekstowe ID, powtarzane wizyty,
  czasy ponad 24:00, brak czasu oraz dokładny/przybliżony timepoint.
- Docker Compose, cienki starter istniejącej bazy, świeżego demo i jawnego źródła GTFS.
- Testy offline/AppTest, PostgreSQL, Compose/browser, syntetyczny raster i regresja dwóch
  snapshotów z rozłącznymi kalendarzami; osobny lokalny odbiór rzeczywistego feedu.

Status merge i konkretne wyniki odbioru są zapisane w końcowym raporcie testowanego SHA.
Historyczne raporty nie opisują stanu nowszego kodu.

## Jawne ograniczenia

Snapshot GTFS może być archiwalny; obwiednia kalendarza nie zapewnia kursów każdego dnia.
Bez shapes mapa nie udaje przebiegu ulic. Czasy nie są interpolowane. Rozwijanie
frequencies/flex nie należy do obsługi ilościowej tego wydania.

Eksperymentalne obserwacje CUI są domyślnie wyłączone. Niepotwierdzony czas i warunki
użycia nie pozwalają przedstawiać ich jako ukończonego live GPS ani przypisywać do kursów.
Awaria tej warstwy nie powinna blokować rozkładowej mapy i tabel.

Poza zakresem pozostają punktualność, pasażerowie i occupancy, predykcje/ML, planer
przesiadek, konta użytkowników, osobny frontend/mobile i wdrożenie chmurowe.

[README](../README.md) · [Stan implementacji](project-plan.md) · [Przeglądarka](transit-explorer.md)
· [Kontrakt danych](data-contract.md).
