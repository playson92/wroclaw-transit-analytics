# Implementation plan

The implementation follows the plan supplied on 6 October 2026.
Statuses describe code present, not a release announcement.

| Stage | Deliverable | Status |
| --- | --- | --- |
| 00 | Bootstrap and accepted ingestion in main | Merged through PR #1 and #2 with merge commits and successful CI |
| 01 | Bronze/silver, DQ, prepare CLI and synthetic sample generator | Merged in main |
| 02 | PostgreSQL 17, transactional COPY, migrations, Compose and real SQL tests | Reviewed; CI-01 added and PR #4 merged |
| 03 | Service calendars/instances, departure metrics, headways and coverage in gold SQL | Implemented on feat/transit-analytics; draft review, no merge |
| 04 | Polish Streamlit dashboard, read-only role, full demo start and portfolio documentation | Planned |

Sprint 01 adds no PostgreSQL, Docker, quantitative gold or UI.
Synthetic data exercises the same prepare pipeline as official data and never impersonates an HTTP download.
Sprint 03 extends the existing runtime with SQL aggregates and a new migration;
it does not change ingestion/prepare/silver or create a dashboard.
Review the complete draft PR and actual CI before approving the next sprint.
Only one dependent branch is permitted when an operational parent merge is blocked,
as explicitly authorized by the current task; otherwise start from main.
