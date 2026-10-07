# Przygotowanie GTFS — Sprint 01

Polecenia wykonuj z katalogu repozytorium. Używamy istniejącego środowiska Python 3.12.

```powershell
Set-Location C:\projekty\wroclaw-transit-analytics
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m wroclaw_transit_analytics prepare --help
```

## Syntetyczny przykład bez pobierania

Po wcześniejszej instalacji pakietów ta ścieżka nie korzysta z sieci.
To mały syntetyczny GTFS, a nie aktualny rozkład MPK.

```powershell
$demo = (& .\.venv\Scripts\python.exe -m wroclaw_transit_analytics sample-data --output-root data --json) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "Generator demo nie zakończył się poprawnie." }
$result = (& .\.venv\Scripts\python.exe -m wroclaw_transit_analytics prepare --raw-manifest $demo.raw_manifest --output-root data --batch-size 50000 --json) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "Prepare nie zakończyło się poprawnie." }
$result | Format-List
Get-Content -LiteralPath $result.quality_report -Raw -Encoding UTF8
```

Bez --json CLI wyświetla opis, ID i rzeczywiste ścieżki.
--json zwraca obiekt sukcesu na stdout; błędy są na stderr i zwracają kod 1.
Każdy generator tworzy nowy raw run, ale ZIP ma deterministyczne bajty.
Każde prepare tworzy nowy processing_run_id; dataset_id tego samego źródła/modelu pozostaje stały.

## Wcześniej pobrany oficjalny GTFS

Skopiuj dokładną ścieżkę manifestu wypisaną przez istniejące ingestion:

```powershell
$rawManifest = "C:\sciezka\do\raw\manifest.json"
.\.venv\Scripts\python.exe -m wroclaw_transit_analytics prepare --raw-manifest $rawManifest --output-root data --batch-size 50000
```

Prepare nie pobiera źródła ponownie. Nowy, jawny oficjalny ZIP nadal obsługuje:
python -m wroclaw_transit_analytics.gtfs --url "<OFFICIAL_ZIP_URL>".
Nie ma resolvera latest.

## Wynik i błędy

Manifest bronze opisuje tekstowe Parquet wybranych tabel.
Manifest silver opisuje typowane Parquet, jakość, pochodzenie, zakres kalendarza i capabilities.
25:10:00 pozostaje 90600 sekundami dnia usługi; brak dozwolonego czasu jest null, nie zerem.

Przy nieudanym silver CLI zwraca kod 1 i ścieżki istniejących manifestów diagnostycznych.
Czytaj status — częściowe pliki nie są kompletnym datasetem.
Bronze może być poprawne, gdy relacje lub typowanie blokują silver.
Nie edytuj raw, aby wymusić sukces.

Szczegóły: [kontrakt danych](data-contract.md).
Prepare pozostaje etapem plikowym. Gotowe silver obsługuje teraz
[loader PostgreSQL 17](postgres-runtime.md); gold i dashboard pozostają planowane.
