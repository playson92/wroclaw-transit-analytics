"""File-based GTFS data foundation; no network or database is started on import."""

from .pipeline import PrepareResult, prepare
from .source import MODEL_VERSION, PrepareError, dataset_id

__all__ = ["MODEL_VERSION", "PrepareError", "PrepareResult", "dataset_id", "prepare"]
