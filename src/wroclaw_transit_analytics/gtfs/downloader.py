"""Stream an unchanged HTTP entity to a unique local snapshot."""

import hashlib
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx

from .config import MAX_REDIRECTS, TIMEOUT, Limits, validate_url
from .exceptions import ConfigurationError, DownloadError, StorageError
from .models import DownloadResult


def download(
    url: str, destination: Path, limits: Limits, *, client: httpx.Client | None = None
) -> DownloadResult:
    """Own only the created client and .part; reject encoded HTTP representations."""
    validate_url(url)
    part = destination.with_suffix(".zip.part")
    owns_part = False
    try:
        if destination.exists():
            raise StorageError(f"Archiwum już istnieje: {destination}")
        context = httpx.Client(verify=True) if client is None else nullcontext(client)
        with context as http:
            current_url = url
            redirects = 0
            while True:
                with http.stream(
                    "GET",
                    current_url,
                    headers={"Accept-Encoding": "identity"},
                    timeout=TIMEOUT,
                    follow_redirects=False,
                ) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location or redirects >= MAX_REDIRECTS:
                            raise DownloadError(
                                "Brak celu lub przekroczony limit przekierowań (3)."
                            )
                        try:
                            current_url = validate_url(urljoin(current_url, location))
                        except (ConfigurationError, ValueError, httpx.InvalidURL) as exc:
                            raise DownloadError(f"Zabronione przekierowanie: {exc}") from exc
                        redirects += 1
                        continue
                    if response.status_code != 200:
                        raise DownloadError(
                            f"Oczekiwano HTTP 200, otrzymano {response.status_code}."
                        )
                    encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
                    if encoding != "identity":
                        raise DownloadError(f"Nieobsługiwane Content-Encoding: {encoding}.")
                    length = response.headers.get("Content-Length")
                    if length is not None and (
                        not length.isascii() or not length.isdecimal() or len(length) > 20
                    ):
                        raise DownloadError("Niepoprawny Content-Length.")
                    expected_size = int(length) if length is not None else None
                    digest = hashlib.sha256()
                    size = 0
                    with part.open("xb") as output:
                        owns_part = True
                        for chunk in response.iter_raw():
                            size += len(chunk)
                            if size > limits.max_download_bytes:
                                raise DownloadError("Przekroczono limit rozmiaru pobrania.")
                            output.write(chunk)
                            digest.update(chunk)
                    if size == 0:
                        raise DownloadError("Otrzymano pustą odpowiedź.")
                    if expected_size is not None and size != expected_size:
                        raise DownloadError("Rozmiar transferu nie zgadza się z Content-Length.")
                    part.rename(destination)
                    owns_part = False
                    return DownloadResult(
                        requested_url=url,
                        final_url=str(response.url),
                        size_bytes=size,
                        sha256=digest.hexdigest(),
                        downloaded_at=datetime.now(UTC).isoformat(),
                        content_type=response.headers.get("Content-Type"),
                        etag=response.headers.get("ETag"),
                        last_modified=response.headers.get("Last-Modified"),
                    )
    except httpx.HTTPError as exc:
        raise DownloadError(f"Błąd HTTP/transferu: {exc}") from exc
    except OSError as exc:
        raise StorageError(f"Błąd zapisu archiwum: {exc}") from exc
    finally:
        if owns_part:
            try:
                part.unlink(missing_ok=True)
            except OSError as exc:
                raise StorageError(f"Nie można usunąć niekompletnego pliku {part}: {exc}") from exc
