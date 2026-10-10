# Domknięcie review mapy i kursów — 2026-10-10

Baza review: `9040ddc97411ea878c68009598d1328717bbb16e`, gałąź
`feat/transit-explorer`, istniejący PR #7. Jedyna dodatkowa zmiana runtime to
kolumna `Czas` w tabeli odjazdów widoku **Przystanek**, przez istniejące
`timetable([r])[0]["Czas"]`. Bez zmian SQL, migracji, KPI, mapy ani zależności.

SHA-256 `explorer/ui.py`, UTF-8 po normalizacji CRLF → LF:

- baza: `ae06d4759179bcf1dc22769cd5bafa208c73adc67f35613ab5eab7f1c12efe5f`;
- kandydat R1: `2df906d728ade0b258762fd32a8ed9ea81cba7dccb3d053e52ba7fd2f6fef600`.

Trzy przypadki AppTest odczytują rzeczywiście wyświetlony dataframe odjazdów:
`timepoint=0` → Przybliżony, `timepoint=1` → Dokładny, brak czasu → Brak czasu.
Nie testują wyłącznie funkcji formatującej ani tabeli kursu.

## RASTER_RENDER_TEST — PASS

`tests/ui/test_raster_browser.py` działa w istniejącym jobie Compose/browser CI,
korzystając z `WTA_BROWSER_URL`, `WTA_BROWSER_EXPECTED` i `WTA_BROWSER_EVIDENCE`.
Nie wymaga lokalnej bazy rzeczywistego Wrocławia ani `WTA_EXPLORER_URL`.
Żądania kafelków przechwytuje Playwright; wszystkie dostają własny syntetyczny
obraz PNG 64 × 64. Publiczny serwer nie otrzymuje tych żądań.

Test z włączonym podkładem sprawdza ponad 10 000 pikseli koloru testowego i piksele
znacznika. Następnie naprawdę klika przystanek NA, sprawdza jego identyfikator,
odjazdy, widoczny zaznaczony punkt oraz zachowany raster. Wyłączenie podkładu
usuwa piksele testowego obrazu, pozostawiając znacznik. Zaznaczenie Streamlit
może nadpisać kolor Pydeck, więc punkt po kliknięciu jest sprawdzany w jego
rzeczywistym położeniu. Demo nie ma shapes; nie dopisano udawanej trasy.

Screenshoty `TECHNICAL-synthetic-raster-*` są dowodem technicznym, nie mapą ulic
Wrocławia. Dotychczasowy test `test_real_explorer_map_trips_click_filters_and_snapshot`
pozostaje testem własnej geometrii, kursów, filtrów i awarii/braku podkładu:
blokuje kafelki i wyłącza raster. Zachowano wszystkie jego asercje. Doprecyzowano
dzień zapisany w dowodzie SQL i wpisywanie daty w formacie wyświetlanym przez widżet.

## REAL_BASEMAP_CHECK — PASS, oddzielny lokalny odczyt

Sprawdzono [aktualną politykę OSM](https://operations.osmfoundation.org/policies/tiles/).
Edge otworzył zwykły widok na 8502 z domyślnym User-Agent, poprawnym Referer i
trwałym cache. Nie przechwytywano ani nie przepisywano rzeczywistych żądań;
bez pan/zoom, skanowania miasta, pobierania na zapas, no-cache czy proxy.

Pierwszy widok: 12 odpowiedzi kafelków HTTP 200, bez błędów. Oceniony obraz
pokazuje rzeczywiste ulice, atrybucję OSM, shapes i przystanki linii 0. Powtórny
widok i wybór następnego kursu tej samej geometrii dały 32 odpowiedzi, z czego
24 z cache dyskowego. Dzień 2026-10-10; zmiana `3_17347737` → `3_17347760`,
12:19:00–12:35:00, kliknięty stop_id=1437. Rozkładowe odjazdy otworzyły się
poprawnie, bez błędów JavaScript. Nie zastępujemy tego dowodu kafelkami mock.

## Walidacja i działające aplikacje

Lokalnie: Ruff check/format i git diff --check PASS; offline **275 passed,
2 skipped** (uprawnienia symlinków Windows); PostgreSQL **29 passed**, bez skipów;
**3 przypadki browser**: analityka demo, rzeczywiste kursy bez rastera i aktywny
syntetyczny raster. Końcowy SHA, XML/logi, screenshoty oraz aktualne wyniki CI
znajdują się w nowym `output/codex_runs/<UTC_TIMESTAMP>/closeout.zip`.
Wyników Linux CI nie utożsamiamy z lokalnymi pominięciami Windows.

Zbudowano i odtworzono wyłącznie dashboard `wta-explorer`,
<http://127.0.0.1:8502>, PostgreSQL na 5434. Wszystkie 65 śledzonych plików
zainstalowanego pakietu odpowiada lokalnym plikom po normalizacji końców linii.
Nie inicjalizowano ponownie baz aplikacji i nie pobierano GTFS.

`wta-demo` na 8501/5433 zachowano. W obu bazach syntetyczne demo dla
2026-10-01–2026-10-07 ma KPI **16 kursów / 25 regularnych odjazdów /
2 aktywne linie / 3 obsługiwane punkty**. Stara baza zachowuje 1 dataset,
1 analizę i 14 wierszy route_daily; explorer 2 datasety, 2 analizy i 973 wiersze.
Oddzielna istniejąca baza testowa używa 15435, ponieważ 5435 jest zajęty;
jej wolumen zachowano. Nie zatrzymywano aplikacji właściciela zajętego portu.

Snapshot GTFS pozostaje historyczny. CUI ma niepotwierdzony czas i warunki
źródła; live pozostaje zablokowane, szare obserwacje nie oznaczają aktualnego GPS
i nie są przypisywane do trip_id. Te ograniczenia nie blokują rozkładowej mapy.

Merge PR #7 jest dopuszczalny dopiero po zielonym CI dla końcowego SHA,
ponownym sprawdzeniu diffu i braku konfliktów/blokującego review, przez merge
commit z `--match-head-commit`. Wynik tej operacji zapisuje raport closeout.
