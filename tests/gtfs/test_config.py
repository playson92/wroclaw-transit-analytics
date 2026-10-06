"""URL precedence and exact trusted-host policy."""

import pytest

from wroclaw_transit_analytics.gtfs.config import Limits, resolve_url, validate_url
from wroclaw_transit_analytics.gtfs.exceptions import ConfigurationError

from .conftest import URL


def test_precedence_and_environment() -> None:
    assert resolve_url(URL, {"GTFS_URL": "bad"}) == URL
    assert resolve_url(None, {"GTFS_URL": URL}) == URL


@pytest.mark.parametrize("url", ["", "http://open-data.cui.wroclaw.pl/feed", "bad"])
def test_invalid_explicit_value_does_not_fall_back(url: str) -> None:
    with pytest.raises(ConfigurationError):
        resolve_url(url, {"GTFS_URL": URL})


def test_missing_configuration() -> None:
    with pytest.raises(ConfigurationError, match="GTFS_URL"):
        resolve_url(None, {})


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/",
        "https://open-data.cui.wroclaw.pl.evil.example/",
        "https://other.wroclaw.pl/",
        "ftp://open-data.cui.wroclaw.pl/",
        "https://user:password@open-data.cui.wroclaw.pl/",
        "https://@open-data.cui.wroclaw.pl/",
        "https://open-data.cui.wroclaw.pl:444/",
        "https://open-data.cui.wroclaw.pl:bad/",
        URL + "#fragment",
        " " + URL,
        URL + "\n",
        "https://open-data.cui.wroclaw.pl\\@evil.example/",
    ],
)
def test_rejected_urls(url: str) -> None:
    with pytest.raises(ConfigurationError):
        validate_url(url)


def test_limits_are_positive() -> None:
    with pytest.raises(ConfigurationError):
        Limits(max_entries=0)
