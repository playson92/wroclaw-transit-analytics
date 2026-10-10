# GTFS data contract — wta-silver-v1

This is the implemented file-based profile, not full GTFS conformance.
The existing downloader and wroclaw-static-mvp-v1 archive validator remain unchanged.

## Raw admission and identity

Only manifest_version=1 with validation.status=passed, the expected profile and empty issues is admitted.
The complete raw contract includes run_id, byte size, SHA-256, safe archive_path and provenance.
The ZIP and manifest hashes are checked before processing and before bronze publication.
The existing archive validator is reused with its limits: 100 MiB archive, 1 GiB decompressed,
100 entries and 64 KiB logical CSV headers/records. No extraction or source repairs occur.

archive_path must identify a regular file inside the manifest directory.
Absolute/drive paths, traversal and symlink components are rejected.
Historical manifests without source_kind mean official_https / real_gtfs.
Requested/final URLs obey the existing official-host policy; downloaded_at is UTC.
The generator extends v1 with source_kind=local_synthetic, data_kind=synthetic_demo and generated_at UTC.
Its requested_url, final_url, catalog_url and downloaded_at are null.

The versioned portfolio subset uses `source_kind=local_derivative` and
`data_kind=real_gtfs`: its rows come from an official archive, but its filtered ZIP
is a new local artifact, not an original download. Top-level requested/final/catalog
URLs and downloaded_at are null; generated_at is UTC. Top-level size_bytes and
sha256 describe the derivative ZIP. `derivative_sample.sample_sha256` must match it.
`derivative_sample.original` preserves the original official URLs, downloaded_at
and SHA-256; selection, license and row_counts describe the subset. Admission
verifies these original URL/hash/time fields and runs the same archive validator.
Derivative provenance is retained in silver and PostgreSQL metadata, without
editing or replacing historical manifests. See the [packaged sample manifest](../src/wroclaw_transit_analytics/portfolio/assets/manifest.json)
and [reproduction script](../scripts/build_portfolio_sample.py).

MODEL_VERSION is wta-silver-v1. Change it when transformation semantics change.
The exact identity algorithm is:

    dataset_id = "gtfs_" + sha256(utf8(model_version + "\0" + source_sha256)).hexdigest()

The separator is a single NUL byte. source_sha256 is lowercase hex.
processing_run_id is a fresh UTC timestamp and UUID. Same ZIP/model => same dataset, distinct run directories.
Batch size, timestamps and paths do not affect dataset_id.

## Bronze

Selected files: agency, stops, routes, trips, stop_times, calendar, calendar_dates.
All original columns and parsed text values are retained: leading zeros, NA, NULL and empty strings.
A strict stdlib CSV reader supplies Pandas DataFrames. There is no type inference,
NA vocabulary, implicit CSV index, or bad-line skipping. UTF-8/BOM and logical quoted records are supported.
Raw preserves exact ZIP bytes; bronze is a representation of logical CSV values.

Blank logical records (all fields empty or whitespace after inspection) are skipped before width checking.
_wta_source_record is the 1-based logical data-record number after the header, including skipped records.
Numbers can have gaps. It is a nonnullable int64; every other bronze column is string.
Source names beginning _wta_ and _agency_key/arrival_seconds/departure_seconds/route_type_description
are reserved and cause a structural failure.

Missing optional calendars have source_present=false and no bronze path.
A present header-only calendar has an actual zero-row Parquet file.
The inventory labels files bronze_and_silver, bronze_only or raw_only.
Extras remain in raw; they are not implicitly modeled.
frequencies.txt is also preserved as textual bronze and counted if present.

## Silver schemas

All source columns remain, with known types below. Missing optional model columns are added.
Extra columns remain strings; names ending _id also receive nullable-ID and whitespace handling.
References to unprocessed extension tables are not validated.
Only _wta_source_record is physically nonnullable; DQ enforces other required values before success.

| Table | Grain/key within one dataset | Typed fields |
| --- | --- | --- |
| agency | _agency_key | agency_id: nullable string; agency_name/agency_url/agency_timezone: required text; _agency_key: string |
| stops | stop_id | stop_id: string; stop_name: text; stop_lat/stop_lon: nullable float64; location_type: int64; parent_station: nullable string |
| routes | route_id | route_id: string; agency_id: nullable string; route_short_name/route_long_name: text; route_type: int64; _agency_key/route_type_description: string |
| trips | trip_id | trip_id/route_id/service_id: string; direction_id: nullable int64; trip_headsign: text |
| stop_times | trip_id + stop_sequence | trip_id/stop_id: string; stop_sequence: int64; original arrival_time/departure_time: text; arrival_seconds/departure_seconds: nullable int64; pickup_type/drop_off_type/timepoint: int64 |
| calendar | service_id | service_id: string; seven weekday flags: int64; start_date/end_date: date32 |
| calendar_dates | service_id + date | service_id: string; date: date32; exception_type: int64 |

Every table retains _wta_source_record. dataset_id lives in the manifest; the transactional loader adds it to SQL keys.
The static trips row count is not a daily count of trip instances.

### Values and defaults

Required IDs cannot be empty. IDs remain strings and are never stripped or deduplicated.
Whitespace is an error. Optional empty IDs become null in silver only.
Dates strictly accept YYYYMMDD and actual dates, then become date32.
Integers are nonnegative signed int64 values; sequence can start at zero and have gaps.

- location_type: empty/missing => 0; allowed 0..4.
- pickup_type/drop_off_type: empty/missing => 0; allowed 0..3.
- timepoint: empty/missing => 1; allowed 0/1.
- direction_id: empty/missing => null; allowed 0/1. No geographic direction is invented.
- Missing optional text fields => empty text.
- Coordinates are finite WGS84 values in [-90,90]/[-180,180].
  Names and coordinates are required for location types 0/1/2, optional for 3/4.
- parent_station is required for 2/3/4 and forbidden for 1.
  Types 0/2/3 point to a station (1); type 4 to a platform (0).
  stop_times can reference only platforms (0).
- Unknown nonnegative route_type codes are retained, labeled other rather than silently bus.

A single agency may omit agency_id; its technical _agency_key is __single_agency__.
Otherwise the source agency ID is the key. Missing route agency_id maps only to one unambiguous agency.
Multiple agencies require unique source IDs, explicit route mapping and a shared valid agency_timezone.

### Service times

H:MM:SS / HH:MM:SS and larger hour values are accepted; minutes/seconds are 0..59.
25:10:00 => 90600 seconds. Original text remains; no modulo 24, datetime.time, UTC conversion or interpolation.
Allowed empty times become null seconds and coverage warnings, not zero.
timepoint=1 requires both times. First/last sequence records require arrival.
Missing intermediate times do not reset the known-time ordering check.
Arrival/departure events must be nondecreasing by trip, sequence and event phase,
regardless of CSV ordering or batch boundaries. timepoint=0 is approximate source information.

## Global quality and capabilities

All batches feed a private SQLite scratch index of keys/references/typed times.
It is a disposable implementation detail, not a published database layer or a replacement for PostgreSQL.
The page cache is bounded, sorting can spill to disk, and the owned index is removed after checks.
All stop_times DataFrames are never concatenated into RAM.

Checks cover required types/values, whitespace, global unique keys, trips→routes,
stop_times→trips/stops, routes→agency, parent hierarchy, service IDs in the union of calendars,
date ranges/flags, exact/endpoint times and complete known-time ordering.
Source duplicates and orphaned records are never silently dropped.
Errors block silver. Allowed missing-time coverage produces warnings.
Counts are complete; examples are bounded to 50 total and 5 per check, with table/record/column/code.
Duplicate counts describe conflicting keys; other counts describe matched rows/values.
The summed error_count is a count of findings, not distinct rejected records.

quality.json reports row_counts, calendar envelope, known arrival/departure coverage,
regular/no-pickup/on-request records, approximate timepoints, unknown directions, agencies and capabilities.
The calendar envelope does not assert service on every date. Calendar expansion and KPI belong to Sprint 03.

Nonempty frequencies sets quantitative_gold_supported=false without invalidating otherwise valid silver.
Later gold must reject unsupported frequency templates rather than count them as daily trips.
Header-only frequencies has present=true, row_count=0; absence has present=false.
Populated flexible location/window fields block silver as unsupported.
Raw-only files and untyped extra columns are inventoried. Shapes, fares, transfers and municipal extensions are not modeled.
These are restrictions of this project profile, not assertions that richer GTFS is invalid.

## Artifacts and publication

    data/bronze/gtfs/<processing_run_id>/manifest.json
    data/silver/gtfs/<processing_run_id>/manifest.json
    data/silver/gtfs/<processing_run_id>/quality.json

Each stage writes in its own private .working directory and closes all Parquet writers.
The completion manifest is created through an owned .part file, then the directory is renamed.
A failed publication removes its owned completion marker. Runs never overwrite previous runs.
Partial artifacts remain failed or private. Bronze may pass while silver fails.
Rejected raw creates no downstream run; inability to write diagnostics is reported without inventing a manifest path.

Manifest v1 contains stage/status, model_version, source_sha256, dataset_id, processing_run_id,
UTC timestamps, measured duration, provenance, input hashes, batch size, inventory and capabilities.
Each table includes a relative path, row_count, source presence, schema types/nullability, byte size and file SHA-256.
Silver also records normalized_empty, added columns and the quality report path/hash/status.

content_sha256 hashes ordered schema name/type pairs, then each row as compact UTF-8 JSON with ISO dates,
nulls and one newline per item. It includes _wta_source_record and is invariant to batch size/row groups.
Physical SHA-256 protects exact Parquet bytes. Loader fingerprints use logical hashes and contract metadata
rather than classify a different physical row-group layout as a conflicting dataset.

## References and tested dependencies

Checked on 7 October 2026: Python 3.12.10, Pandas 2.3.3, PyArrow 25.0.1.
PyArrow 25.0.1 provides a CPython 3.12 Windows wheel; the dependency range is >=25.0.1,<26.

- [GTFS Schedule](https://gtfs.org/documentation/schedule/reference/)
- [Pandas 2.3 CSV](https://pandas.pydata.org/pandas-docs/version/2.3/reference/api/pandas.read_csv.html)
- [PyArrow ParquetWriter](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.ParquetWriter.html)
- [PyArrow compatibility](https://arrow.apache.org/docs/python/install.html)
