"""Basic project health check."""


def health_check() -> dict[str, str]:
    """Return the current health status of the project."""
    return {"status": "ok"}
