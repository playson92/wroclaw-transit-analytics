"""Source policy and project resource limits (not GTFS standard limits)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from .exceptions import ConfigurationError

CATALOG_URL = "https://open-data.cui.wroclaw.pl/hdb/ft/6/"
ALLOWED_HOST = "open-data.cui.wroclaw.pl"
PROFILE = "wroclaw-static-mvp-v1"
TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=10.0)
MAX_REDIRECTS = 3


@dataclass(frozen=True)
class Limits:
    """Bound network, decompression and individual CSV header/record reads."""

    max_download_bytes: int = 100 * 1024**2
    max_uncompressed_bytes: int = 1024**3
    max_entries: int = 100
    max_header_bytes: int = 64 * 1024
    max_record_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        if any(value <= 0 for value in vars(self).values()):
            raise ConfigurationError("Wszystkie limity muszą być dodatnie.")


DEFAULT_LIMITS = Limits()


def validate_url(url: str) -> str:
    """Validate the exact HTTPS host before any request, including redirects."""
    try:
        parts = urlsplit(url)
        port = parts.port
        parsed = httpx.URL(url)
    except (ValueError, httpx.InvalidURL) as exc:
        raise ConfigurationError(f"Niepoprawny URL: {exc}") from exc
    if (
        not url
        or url != url.strip()
        or any(ord(char) <= 32 or ord(char) == 127 for char in url)
        or "\\" in url
        or parts.scheme != "https"
        or parts.hostname != ALLOWED_HOST
        or parsed.host != ALLOWED_HOST
        or port not in (None, 443)
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
    ):
        raise ConfigurationError(
            f"URL musi używać HTTPS i hosta {ALLOWED_HOST}, bez loginu, hasła i fragmentu."
        )
    return url


def resolve_url(cli_url: str | None, environ: Mapping[str, str] | None = None) -> str:
    """An explicitly supplied CLI value always takes precedence, even if invalid."""
    environment = os.environ if environ is None else environ
    url = cli_url if cli_url is not None else environment.get("GTFS_URL")
    if url is None:
        raise ConfigurationError("Podaj --url albo ustaw zmienną środowiskową GTFS_URL.")
    return validate_url(url)
