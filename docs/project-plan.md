# Stan implementacji

Plan z 6 października 2026 doprowadził do lokalnego produktu rozkładowo-analitycznego.
Tabela opisuje dostarczony kod; końcowy odbiór, CI i merge mają osobne dowody dla SHA.

| Etap | Dostarczony zakres | Stan |
| --- | --- | --- |
| 00 | Bootstrap, jawne pobieranie i walidacja GTFS | Scalone przez PR #1 i #2 |
| 01 | Bronze/silver, DQ, prepare i generator oznaczonego demo | Scalone |
| 02 | PostgreSQL 17, migracje, transakcyjny COPY, Compose i testy SQL | PR #4 scalony |
| 03 | Kalendarze, instancje kursów, odjazdy, headways i pokrycie gold | PR #5 scalony |
| 04 | Polski dashboard, reader, demo i dokumentacja portfolio | PR #6 scalony; lokalny Docker Desktop/PostgreSQL i dashboard uruchomione |
| 05 | Explorer, shapes, przystanki, stabilizacja filtrów, starter i wydanie portfolio 0.2.0 | Zaimplementowane w PR #7; wyniki odbioru i stan merge w końcowym raporcie |

PostgreSQL, Compose, dashboard i SQL gold są częścią aplikacji. Shapes są obsługiwane
przez explorer i zachowują powiązanie ze snapshotem i konkretnym kursem. Nie zmieniono
tożsamości silver, zastosowanych migracji ani definicji `wta-gold-v1`.

Odbiór 0.2.0 obejmuje offline/AppTest, PostgreSQL, Compose/browser, obowiązkową regresję
dwóch syntetycznych kalendarzy, lokalne realne dane, podkład ulic, restart/idempotencję,
świeży start i niezależne review. Wyniki dawnego runu z błędem resetu daty pozostają
[historyczną reprodukcją](explorer-review-closeout.md), a nie bieżącym statusem produktu.

Live GPS, predykcje, chmura i planer podróży pozostają [poza zakresem wydania](project-scope.md).
Nie powstaje kolejny plan sprintów ani osobny frontend.
