# Implementation plan

The implementation follows the plan supplied on 6 October 2026.
Statuses describe code present, not a release announcement.

| Stage | Deliverable | Status |
| --- | --- | --- |
| 00 | Bootstrap and accepted ingestion in main | Merged through PR #1 and #2 with merge commits and successful CI |
| 01 | Bronze/silver, DQ, prepare CLI and synthetic sample generator | Implemented on feat/gtfs-data-foundation; needs review/merge before Sprint 02 |
| 02 | PostgreSQL 17, transactional COPY, migrations, Compose and real SQL tests | Planned |
| 03 | Service calendars/instances, departure metrics, headways and coverage in gold SQL | Planned |
| 04 | Polish Streamlit dashboard, read-only role, full demo start and portfolio documentation | Planned |

Sprint 01 adds no PostgreSQL, Docker, quantitative gold or UI.
Synthetic data exercises the same prepare pipeline as official data and never impersonates an HTTP download.
Before the next sprint, review the complete draft PR, require green CI and merge it.
Do not create dependent feature branches before the preceding sprint is in main.
