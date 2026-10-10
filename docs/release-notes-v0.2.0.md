# Wydanie portfolio 0.2.0

Wersja pakietu i `__version__` to **0.2.0**. Przed zmianą sprawdzono wersję 0.1.0
oraz brak lokalnych i zdalnych tagów. To uporządkowanie lokalnego wydania portfolio:
nie utworzono tagu, GitHub Release ani wdrożenia chmurowego.

## Dostarczony zakres

- Lokalny explorer jako pierwszy ekran: dzień, komunikacja, linia, kierunek/wariant,
  kurs, kliknięcie przystanku i rozkładowe odjazdy.
- Zweryfikowane shapes właściwego snapshotu; opcjonalny rzeczywisty raster OSM
  z atrybucją, działanie własnej geometrii i tabel bez podkładu.
- Naprawiony stan daty i zależnych filtrów przy zmianie datasetu; pierwsza data
  kalendarza, zgodny klient/session_state/SQL, obsługa wyczyszczonych pól,
  poprawnych dni bez kursów i dat poza zakresem. Powrót między widokami zachowuje filtry.
- Kolumna **Czas** w tabeli odjazdów: Dokładny / Przybliżony, a brak godziny pozostaje
  Brak czasu. Godziny ponad 24:00, tekstowe ID i powtarzane wizyty są zachowane.
- Obowiązkowa regresja dwóch syntetycznych snapshotów z rozłącznymi kalendarzami
  w standardowym Compose/browser CI; brak fixture daje błąd, bez zależności od danych autora.
- `scripts/start-explorer.ps1`: restart bez importu/pobrania, świeże demo,
  jawny raw manifest lub oficjalny URL, przekazywanie faktycznych wyników pipeline'u.
- Czytelne pochodzenie snapshotów, szczegóły techniczne w rozwijanych sekcjach
  i dokumentacja aktualnej aplikacji z mapą ulic oraz pięcioma odtwarzalnymi wnioskami SQL.

Istniejące ingestion, prepare, PostgreSQL, loader i SQL gold są wykorzystane ponownie.
Zależności i zastosowane migracje nie zostały zmienione. Migracja explorer 003 jest
częścią wcześniejszego rozszerzenia; definicje KPI `wta-gold-v1` pozostają takie same.

## Odbiór i dowody

Końcowy run zapisuje Ruff, offline/AppTest, prawdziwy PostgreSQL, Compose/browser,
regresję snapshotów, osobny realny scenariusz Wrocławia i podkład ulic, restart,
idempotencję, świeży checkout oraz niezależne review. Wyniki JUnit, CI, testowane SHA
i stan merge są w `output/codex_runs/<UTC_TIMESTAMP>/final-review-bundle.zip`.
Raport odróżnia Windows od Linux CI i nie liczy tego samego testu dwa razy.

[Poprzedni closeout](explorer-review-closeout.md) zachowuje historyczny failing reset
daty i ograniczenie dawnej zgody R1; nie jest bieżącym raportem odbioru nowej wersji.
Historyczne screenshoty analityki mają zapisane własne SHA. Nowy screenshot ulic
przedstawia aktualny explorer; syntetyczny raster jest wyłącznie dowodem technicznym.

## Granice wydania

Snapshot GTFS jest archiwalny, bez potwierdzenia dzisiejszego rozkładu.
Demo jest jawnie syntetyczne. SQL opisuje rozkład, bez pasażerów i punktualności.
Eksperymentalne CUI pozostaje domyślnie wyłączone i szare; czas oraz warunki pozycji
nie są potwierdzone. **Ukończony live GPS nie należy do 0.2.0.**

Kod MIT, warunki GTFS, warunki OSM oraz niepotwierdzony status pozycji są opisane
oddzielnie w [README](../README.md) i [studium portfolio](portfolio-case-study.md).
