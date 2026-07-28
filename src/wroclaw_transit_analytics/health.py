"""Application health check."""


def health_check() -> dict[str, str]:
    """Return the current application status."""
    return {"status": "ok"}
