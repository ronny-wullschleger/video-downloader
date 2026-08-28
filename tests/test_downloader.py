from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

import downloader as dl
from validation import InvalidURL


class FakeYDL:
    """Stand-in for yt_dlp.YoutubeDL. No network."""

    last_opts: dict | None = None

    def __init__(self, opts):
        type(self).last_opts = opts
        self.opts = opts
        self.hooks = opts.get("progress_hooks") or []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        dest = Path(self.opts["outtmpl"]).parent
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / "Demo Clip [abc123].mp4"
        if download:
            for hook in self.hooks:
                hook(
                    {
                        "status": "downloading",
                        "downloaded_bytes": 50,
                        "total_bytes": 100,
                        "speed": 2048.0,
                        "eta": 4,
                        "info_dict": {
                            "title": "Demo Clip",
                            "thumbnail": "https://example.com/t.jpg",
                        },
                    }
                )
                hook({"status": "finished", "filename": str(path)})
            path.write_bytes(b"fake-video")
        return {
            "id": "abc123",
            "title": "Demo Clip",
            "thumbnail": "https://example.com/t.jpg",
            "_filename": str(path),
            "requested_downloads": [{"filepath": str(path)}],
        }

    def prepare_filename(self, info):
        return info["_filename"]


class ProbeYDL(FakeYDL):
    def extract_info(self, url, download=False):
        return {
            "id": "xyz",
            "title": "Hello World",
            "thumbnail": "https://img.example/t.jpg",
            "duration": 91,
            "uploader": "Studio",
            "extractor_key": "Generic",
        }


class PlaylistYDL(FakeYDL):
    def extract_info(self, url, download=False):
        return {
            "_type": "playlist",
            "entries": [
                {
                    "id": "first",
                    "title": "First item",
                    "thumbnail": "https://img.example/1.jpg",
                    "duration": 10,
                    "uploader": "A",
                    "extractor_key": "Youtube",
                }
            ],
        }


class FfmpegMissingYDL(FakeYDL):
    def extract_info(self, url, download=True):
        raise Exception(
            "ERROR: You have requested merging of multiple formats but ffmpeg is not installed. "
            "Please install ffmpeg"
        )


class GenericFailYDL(FakeYDL):
    def extract_info(self, url, download=True):
        raise Exception("ERROR: [generic] Unsupported URL: https://example.com/nope")


def wait_job(job_id: str, timeout: float = 2.0) -> dict:
    deadline = time.time() + timeout
    snap = None
    while time.time() < deadline:
        snap = dl.store.snapshot(job_id)
        if snap and snap["status"] in {"done", "error"}:
            return snap
        time.sleep(0.02)
    assert snap is not None, "job never appeared"
    return snap


def test_start_download_rejects_bad_url():
    with pytest.raises(InvalidURL):
        dl.start_download("not-a-url", "best")


def test_start_download_rejects_unknown_quality():
    with pytest.raises(ValueError, match="quality"):
        dl.start_download("https://example.com/watch?v=1", "4k")


def test_download_orchestration_with_mocked_ydl(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "DOWNLOAD_DIR", tmp_path)
    with patch("downloader.yt_dlp.YoutubeDL", FakeYDL):
        job = dl.start_download("https://example.com/watch?v=1", "best")
        snap = wait_job(job.id)
    assert snap["status"] == "done"
    assert snap["filename"] == "Demo Clip [abc123].mp4"
    assert snap["title"] == "Demo Clip"
    assert snap["percent"] == 100
    assert (tmp_path / "Demo Clip [abc123].mp4").is_file()
    assert FakeYDL.last_opts["format"] == dl.QUALITY_FORMATS["best"]
    assert FakeYDL.last_opts["merge_output_format"] == "mp4"


def test_audio_quality_skips_mp4_merge(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "DOWNLOAD_DIR", tmp_path)
    with patch("downloader.yt_dlp.YoutubeDL", FakeYDL):
        job = dl.start_download("https://example.com/a.mp4", "audio")
        snap = wait_job(job.id)
    assert snap["status"] == "done"
    assert "merge_output_format" not in FakeYDL.last_opts
    assert FakeYDL.last_opts["format"] == dl.QUALITY_FORMATS["audio"]


def test_ffmpeg_missing_is_plain_language(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "DOWNLOAD_DIR", tmp_path)
    with patch("downloader.yt_dlp.YoutubeDL", FfmpegMissingYDL):
        job = dl.start_download("https://example.com/watch?v=1", "best")
        snap = wait_job(job.id)
    assert snap["status"] == "error"
    assert "ffmpeg" in snap["error"].lower()
    assert "PATH" in snap["error"]
    assert "Traceback" not in snap["error"]


def test_generic_ydl_error_is_plain_language(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "DOWNLOAD_DIR", tmp_path)
    with patch("downloader.yt_dlp.YoutubeDL", GenericFailYDL):
        job = dl.start_download("https://example.com/nope", "720p")
        snap = wait_job(job.id)
    assert snap["status"] == "error"
    assert "Unsupported URL" in snap["error"]
    assert "Traceback" not in snap["error"]


def test_human_error_strips_traceback():
    text = dl.human_error(
        Exception("ERROR: boom\nTraceback (most recent call last):\n  File x")
    )
    assert text == "boom"
    assert "Traceback" not in text


def test_probe_mocked():
    with patch("downloader.yt_dlp.YoutubeDL", ProbeYDL):
        info = dl.probe("https://youtube.com/watch?v=1")
    assert info["title"] == "Hello World"
    assert info["thumbnail"] == "https://img.example/t.jpg"
    assert info["duration"] == 91
    assert info["uploader"] == "Studio"


def test_probe_unwraps_playlist():
    with patch("downloader.yt_dlp.YoutubeDL", PlaylistYDL):
        info = dl.probe("https://youtube.com/playlist?list=x")
    assert info["title"] == "First item"
    assert info["id"] == "first"


def test_probe_rejects_bad_url():
    with pytest.raises(InvalidURL):
        dl.probe("ftp://x")
