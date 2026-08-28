"""URL validation for the local downloader."""

from __future__ import annotations

from urllib.parse import urlparse

ALLOWED_SCHEMES = frozenset({"http", "https"})
MAX_URL_LENGTH = 2048


class InvalidURL(ValueError):
    """Raised when a pasted URL is not a downloadable http(s) address."""


def validate_url(url: str) -> str:
    """Return a stripped http(s) URL or raise InvalidURL with a plain message."""
    if not isinstance(url, str):
        raise InvalidURL("Paste a webpage or video URL.")

    url = url.strip()
    if not url:
        raise InvalidURL("Paste a webpage or video URL.")
    if len(url) > MAX_URL_LENGTH:
        raise InvalidURL("That URL is too long.")
    if any(ch.isspace() for ch in url):
        raise InvalidURL("URL cannot contain spaces.")

    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise InvalidURL("Only http and https URLs are allowed.")
    if not parsed.netloc:
        raise InvalidURL("That does not look like a complete URL.")
    return url
