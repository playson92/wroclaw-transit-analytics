# Static GTFS ingestion

This module implements the first portfolio pipeline: explicit source URL → streaming
download → unchanged raw ZIP → local MVP validation → JSON manifest → terminal result.
It uses HTTPX and the standard library. No extraction to disk, Pandas processing,
database, dashboard, deduplication or automated scheduling happens at this stage.

## Official source and choosing a URL

Dataset description: <https://open-data.cui.wroclaw.pl/hdb/metadane/13/>.
File catalogue: <https://open-data.cui.wroclaw.pl/hdb/ft/6/>.
GTFS Schedule reference: <https://gtfs.org/documentation/schedule/reference/>.

Open the catalogue, choose a specific archive and copy the link address of its
**Pobierz** action (in a browser, right-click → copy link address). Use the download
address rather than the catalogue page address. Download URLs need not end in `.zip`.
The application does not parse HTML, resolve an API, or select “latest”.
The date in a filename and the catalogue's “Data pobrania” column are not interpreted
as the schedule's validity date or resource publication date.

Only HTTPS on the exact host `open-data.cui.wroclaw.pl` is permitted, using the default
HTTPS port or explicit port 443. Credentials and fragments are rejected.
Every redirect is checked before another request; at most three redirects are allowed.
No additional host or unofficial mirror is configured.

## PowerShell execution

Use the existing environment; activation is optional:

```powershell
Set-Location C:\projekty\wroclaw-transit-analytics
.\.venv\Scripts\python.exe -m wroclaw_transit_analytics.gtfs --help
.\.venv\Scripts\python.exe -m wroclaw_transit_analytics.gtfs --url "<OFFICIAL_ZIP_URL>"

$env:GTFS_URL = "<OFFICIAL_ZIP_URL>"
.\.venv\Scripts\python.exe -m wroclaw_transit_analytics.gtfs

.\.venv\Scripts\python.exe -m wroclaw_transit_analytics.gtfs --url "<OFFICIAL_ZIP_URL>" --output-dir data/raw/gtfs
```

With an activated `.venv`, these commands can use `python` instead of the full
interpreter path. `--url` has precedence, including when its value is invalid:
there is no silent fallback to `GTFS_URL`. Missing configuration is an error.
`.env.example` documents the setting; creating `.env` does not set a PowerShell
environment variable and the application does not load that file.
Relative `--output-dir` paths are resolved from the current working directory.
Help and importing the package do not start a download.

## Transfer and raw layout

The HTTP connection timeout is 10 seconds; read and write timeouts are 60 seconds,
and the pool timeout is 10 seconds. Standard TLS verification is enabled for the
application's client. Only a complete HTTP 200 response is accepted, with no range
request. HTTPX clients supplied to the Python API remain owned by the caller.

The request uses `Accept-Encoding: identity`. If the server returns a different
`Content-Encoding`, the transfer is rejected. The module writes `iter_raw()` bytes;
it does not silently decompress an HTTP representation or compare a compressed
Content-Length against decoded bytes. For accepted responses, an available
Content-Length must match the actual count. Content-Type and a filename suffix do
not establish ZIP validity; `application/octet-stream` is supported.

```text
data/raw/gtfs/<UTC_DATE>/<UTC_TIMESTAMP>_<UUID>/
    feed.zip
    manifest.json
```

Each run creates a new directory, even for identical data. Server-provided filenames
are never used as local paths. During transfer, a privately created `feed.zip.part`
is written and hashed incrementally. The byte limit applies even without
Content-Length. The file is closed and renamed on the same filesystem before
validation. Source bytes are never repaired or rewritten.

Manifest format version 1 records the run ID, UTC download-completion timestamp
with timezone, official catalogue, requested/final URLs, `archive_path` relative to
the manifest directory, byte count, SHA-256, nullable Content-Type/ETag/Last-Modified,
validation profile, scope, status and issues (`code`, `file`, `description`).
Download time does not describe the schedule's service period.

The manifest is written through its own temporary file and rename. It marks a
completed run; ZIP and manifest are separate operations, not an atomic transaction.
SHA-256 prepares for future deduplication, which is not implemented here.

## Validation profile: wroclaw-static-mvp-v1

This is an archive-integrity and analytical-input profile, not a full GTFS validator
or a check that the schedule is current. These limits belong to this project:

| Limit | Default |
| --- | --- |
| Received archive bytes | 100 MiB |
| Total decompressed bytes | 1 GiB |
| ZIP entries (including directory entries) | 100 |
| CSV logical header bytes, including BOM/newlines | 64 KiB |
| Inspected CSV logical data-record bytes, including newlines | 64 KiB |

Limits can be changed through `config.Limits` passed to the Python `ingest` API
or local validator; the minimal CLI uses these defaults.

Before member content is opened, validation checks ZIP opening, entry count,
declared decompressed size, unsafe paths (including traversal, backslashes,
absolute and Windows drive paths, and NUL in original entry names), duplicate names,
encryption and symbolic links. Original ZIP names are checked before matching root
files, since the ZIP library can truncate the visible name at NUL.
If these metadata checks fail, content is not read. Safe members, including optional
files, are streamed to EOF for decompression/CRC verification, with an additional
actual decompressed-byte budget. A decompression or integrity failure stops that scan.
The specific corrupt-data error raised by CPython's BZIP2 decoder is reported as
an integrity/decompression issue, while filesystem errors such as EIO and permission
denial remain storage failures. Valid stored, deflated and BZIP2 archives are supported.
No `extractall()` or disk extraction is used.

Required root files and minimum columns of **our analytical profile**:

| File | Columns |
| --- | --- |
| agency.txt | agency_name, agency_url, agency_timezone |
| stops.txt | stop_id, stop_name, stop_lat, stop_lon |
| routes.txt | route_id, route_type, plus route_short_name or route_long_name |
| trips.txt | route_id, service_id, trip_id |
| stop_times.txt | trip_id, arrival_time, departure_time, stop_id, stop_sequence |
| calendar.txt, if present | service_id, monday, tuesday, wednesday, thursday, friday, saturday, sunday, start_date, end_date |
| calendar_dates.txt, if present | service_id, date, exception_type |

At least one calendar file must exist. Both may exist. The five basic tables must
have data after their headers, and at least one calendar must have data.
A header-only calendar_dates.txt is allowed alongside a populated calendar.txt.
The nonempty check reads logical records through the CSV parser until at least one
field is nonempty after `strip()`. Records containing only delimiters, empty quoted
fields or whitespace-only fields do not count as data. Such empty records before a
populated record are allowed. Each inspected record has its own bounded byte budget,
including quoted multiline records; an oversized record reports `record_limit`.
After finding data, the rest is streamed to EOF for CRC and byte accounting without
parsing every row. This does not validate field counts or all record values.
Required files under `folder/`
are not treated as root files. Safe extras such as shapes.txt and transfers.txt
are allowed.

Headers use the CSV parser, support quoted fields, UTF-8/BOM, LF and CRLF, and reject
empty or duplicate column names. UTF-8 checks cover headers and records inspected
while finding data, not every data record in the archive.
The table above must not be read as universal, unconditional GTFS requirements:
the standard has conditional and optional fields, notably in stops and stop_times.
No identifier uniqueness, cross-table relation, full value validation or current
service-period check is performed. Times are not parsed as `datetime.time`;
GTFS values such as `25:10:00` remain untouched.

## Failure semantics and exit codes

- Incomplete transfer, empty response or download limit failure: remove only this
  run's incomplete `.part`; no complete snapshot or manifest is reported.
- Complete valid feed: preserve ZIP and manifest with `validation.status = passed`.
- Complete invalid ZIP/feed, including an HTML response: preserve original bytes
  and manifest with `validation.status = failed` and detailed issues.
- Storage or manifest failure: exit with an error. A ZIP without a manifest is an
  incomplete run and cannot be admitted for future processing.

CLI exit code 0 requires download, validation and manifest success. Expected errors
go to stderr with code 1; argument parsing errors use argparse's code 2.
Success shows archive/manifest paths, size and SHA-256. Future processing must admit
only runs with a `passed` manifest. There is no separate quarantine system.
Raw data and `output/codex_runs/` are ignored by Git; existing `.gitkeep` files remain.

## Offline verification and next stage

From the repository directory:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest
```

Tests use MockTransport, temporary files and small generated ZIPs. Existing health
tests remain. The live official-source smoke test is a separate manual CLI run,
never part of pytest or CI. Reports record its exact URL and result; offline tests
alone do not prove current portal availability.

Next work: review and publish this ingestion change, then design parsing and cleaned
analytical datasets from completed `passed` runs. Bronze/silver/gold, PostgreSQL,
Docker Compose, dashboard and cloud remain later project stages.
