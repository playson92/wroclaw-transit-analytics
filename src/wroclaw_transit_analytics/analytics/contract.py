"""Semantic identity is independent of execution limits and wall-clock time."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date

from ..database.connection import DatabaseError

METRICS_VERSION = "wta-gold-v1"


class AnalyticsError(DatabaseError):
    """A safe, explicit rejection of incomplete/unsupported/oversized analytics."""


def dates(start: str | date, end: str | date) -> tuple[date, date]:
    try:
        values = []
        for value in (start, end):
            if type(value) is date:
                values.append(value)
            elif isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                values.append(date.fromisoformat(value))
            else:
                raise ValueError
        if values[0] > values[1]:
            raise ValueError
        return tuple(values)
    except ValueError:
        raise AnalyticsError(
            "INVALID_DATES: wymagany domknięty zakres YYYY-MM-DD, start <= end."
        ) from None


def analysis_id(dataset_id: str, start: date, end: date, version: str = METRICS_VERSION) -> str:
    value = [dataset_id, start.isoformat(), end.isoformat(), version]
    return (
        "analysis_" + hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()
    )


@dataclass(frozen=True)
class AnalyticsResult:
    status: str
    analysis_id: str
    dataset_id: str
    metrics_version: str
    start_date: str
    end_date: str
    row_counts: dict[str, int]
    coverage: dict
    source_context: dict
