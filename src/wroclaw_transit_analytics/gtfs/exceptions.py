"""Expected ingestion failures presented by the CLI without a traceback."""


class GTFSError(Exception):
    """Base class for expected GTFS failures."""


class ConfigurationError(GTFSError):
    """Invalid or missing source configuration."""


class DownloadError(GTFSError):
    """Incomplete or rejected HTTP transfer."""


class ValidationError(GTFSError):
    """Completed snapshot failed the MVP profile."""


class StorageError(GTFSError):
    """Local read, write, rename or cleanup failed."""
