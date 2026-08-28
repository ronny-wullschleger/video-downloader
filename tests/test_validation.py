import pytest

from validation import InvalidURL, validate_url


def test_https_ok():
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert validate_url(url) == url


def test_http_direct_file_ok():
    url = "http://cdn.example.com/films/reel.mp4"
    assert validate_url(url) == url


def test_strips_whitespace():
    assert validate_url("  https://vimeo.com/123  ") == "https://vimeo.com/123"


def test_rejects_empty():
    with pytest.raises(InvalidURL, match="Paste"):
        validate_url("")
    with pytest.raises(InvalidURL, match="Paste"):
        validate_url("   ")
    with pytest.raises(InvalidURL, match="Paste"):
        validate_url(None)  # type: ignore[arg-type]


def test_rejects_javascript():
    with pytest.raises(InvalidURL, match="http"):
        validate_url("javascript:alert(1)")


def test_rejects_file_scheme():
    with pytest.raises(InvalidURL, match="http"):
        validate_url("file:///etc/passwd")


def test_rejects_ftp():
    with pytest.raises(InvalidURL, match="http"):
        validate_url("ftp://files.example.com/a.mp4")


def test_rejects_relative():
    with pytest.raises(InvalidURL):
        validate_url("/videos/foo.mp4")


def test_rejects_scheme_without_host():
    with pytest.raises(InvalidURL, match="complete"):
        validate_url("https://")


def test_rejects_spaces_inside():
    with pytest.raises(InvalidURL, match="spaces"):
        validate_url("https://example.com/some video")


def test_rejects_too_long():
    with pytest.raises(InvalidURL, match="too long"):
        validate_url("https://example.com/" + ("a" * 3000))
