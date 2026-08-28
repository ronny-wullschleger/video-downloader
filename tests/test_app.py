from unittest.mock import patch

from fastapi.testclient import TestClient

import app as appmod
from downloader import Job


client = TestClient(appmod.app)


def test_index_serves_ui():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Celluloid" in response.text
    assert "Pull down" in response.text


def test_download_rejects_non_http_url():
    response = client.post("/api/download", json={"url": "ftp://x", "quality": "best"})
    assert response.status_code == 400
    assert "http" in response.json()["detail"].lower()
    assert "Traceback" not in response.text


def test_download_rejects_unknown_quality():
    response = client.post(
        "/api/download",
        json={"url": "https://example.com/v", "quality": "nope"},
    )
    assert response.status_code == 400
    assert "quality" in response.json()["detail"].lower()


def test_download_starts_when_orchestrator_is_mocked():
    fake = Job(id="deadbeefcafe", url="https://example.com/v", quality="best")

    with patch("app.start_download", return_value=fake):
        response = client.post(
            "/api/download",
            json={"url": "https://example.com/v", "quality": "best"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "deadbeefcafe"
    assert body["status"] == "queued"


def test_probe_validates_url():
    response = client.post("/api/probe", json={"url": "javascript:alert(1)"})
    assert response.status_code == 400


def test_unknown_job_is_404():
    response = client.get("/api/jobs/does-not-exist")
    assert response.status_code == 404


def test_status_reports_ffmpeg_flag():
    response = client.get("/api/status")
    assert response.status_code == 200
    assert "ffmpeg" in response.json()
    assert isinstance(response.json()["ffmpeg"], bool)
