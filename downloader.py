"""yt-dlp job orchestration: probe, download, live progress."""

from __future__ import annotations

import shutil
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp

from validation import InvalidURL, validate_url

ROOT = Path(__file__).resolve().parent
DOWNLOAD_DIR = ROOT / "downloads"

QUALITY_FORMATS: dict[str, str] = {
    "best": "bv*+ba/b",
    "1080p": "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b",
    "720p": "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b",
    "audio": "ba/b",
}
VALID_QUALITIES = frozenset(QUALITY_FORMATS)

# Template keeps titles readable and includes the extractor id.
OUTTMPL = "%(title).200B [%(id)s].%(ext)s"


@dataclass
class Job:
    id: str
    url: str
    quality: str
    status: str = "queued"  # queued | downloading | processing | done | error
    percent: float | None = None
    eta: int | None = None
    speed: float | None = None
    title: str | None = None
    thumbnail: str | None = None
    filename: str | None = None
    error: str | None = None
    message: str | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "quality": self.quality,
            "status": self.status,
            "percent": self.percent,
            "eta": self.eta,
            "speed": self.speed,
            "title": self.title,
            "thumbnail": self.thumbnail,
            "filename": self.filename,
            "error": self.error,
            "message": self.message,
        }


class JobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}

    def create(self, url: str, quality: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], url=url, quality=quality)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in fields.items():
                setattr(job, key, value)

    def snapshot(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.snapshot() if job else None


store = JobStore()


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def human_error(exc: BaseException) -> str:
    """Turn yt-dlp / OS errors into a short UI-safe sentence. Never a traceback."""
    if isinstance(exc, InvalidURL):
        return str(exc)

    text = str(exc).strip() or exc.__class__.__name__
    if "Traceback (most recent call last)" in text:
        text = text.split("Traceback (most recent call last)", 1)[0].strip() or "Download failed."

    lower = text.lower()
    ffmpeg_missing_markers = (
        "ffmpeg is not installed",
        "ffmpeg not found",
        "ffprobe not found",
        "ffmpeg/avconv not found",
        "set your --ffmpeg-location",
        "merging of multiple formats but ffmpeg",
    )
    if any(marker in lower for marker in ffmpeg_missing_markers):
        return (
            "Merging video and audio needs ffmpeg on your PATH. "
            "Install ffmpeg and try again."
        )
    if "ffmpeg" in lower and any(
        marker in lower for marker in ("errno 2", "winerror 2", "no such file")
    ):
        return (
            "Merging video and audio needs ffmpeg on your PATH. "
            "Install ffmpeg and try again."
        )
    if "ffmpeg" in lower and any(
        marker in lower for marker in ("failed", "error", "postprocess", "merge")
    ):
        return (
            "ffmpeg failed while merging or converting this file. "
            "Check that ffmpeg is installed and try a different quality."
        )

    line = _first_useful_line(text)
    if line.lower().startswith("error:"):
        line = line[6:].strip()
    if not line:
        return "Download failed."
    if len(line) > 280:
        line = line[:277] + "…"
    return line


def _first_useful_line(text: str) -> str:
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("File ") or line.startswith("Traceback"):
            continue
        if line.startswith("~") or line.startswith("^"):
            continue
        return line
    return ""


def _ydl_base_opts() -> dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "playlistend": 1,
        "nocheckdir": False,
        "windowsfilenames": True,
        "overwrites": True,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 1,
    }


def probe(url: str) -> dict[str, Any]:
    """Return title / thumbnail / duration without downloading."""
    url = validate_url(url)
    opts = {
        **_ydl_base_opts(),
        "skip_download": True,
        "extract_flat": False,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001 — surface as a plain probe error
        raise RuntimeError(human_error(exc)) from None

    if not info:
        raise RuntimeError("Could not read video information from that URL.")

    info = _unwrap_playlist(info)
    return {
        "title": info.get("title") or info.get("id") or "Untitled",
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader") or info.get("channel"),
        "extractor": info.get("extractor_key") or info.get("extractor"),
        "id": info.get("id"),
    }


def start_download(url: str, quality: str = "best") -> Job:
    """Validate, enqueue, and run yt-dlp on a background thread."""
    url = validate_url(url)
    quality = (quality or "best").strip().lower()
    if quality not in VALID_QUALITIES:
        raise ValueError("Unknown quality. Choose best, 1080p, 720p, or audio.")

    if quality != "audio" and not ffmpeg_available():
        # Still allow the attempt — some URLs are a single file — but the
        # merge-failure path below will spell out the ffmpeg requirement.
        pass

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    job = store.create(url, quality)
    thread = threading.Thread(target=_run_download, args=(job.id,), daemon=True)
    thread.start()
    return job


def _run_download(job_id: str) -> None:
    job = store.get(job_id)
    if job is None:
        return

    store.update(job_id, status="downloading", message="Starting download…")

    def hook(d: dict[str, Any]) -> None:
        try:
            _apply_progress(job_id, d)
        except Exception:
            return

    opts: dict[str, Any] = {
        **_ydl_base_opts(),
        "format": QUALITY_FORMATS[job.quality],
        "outtmpl": str(DOWNLOAD_DIR / OUTTMPL),
        "progress_hooks": [hook],
    }
    if job.quality != "audio":
        opts["merge_output_format"] = "mp4"

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(job.url, download=True)
            info = _unwrap_playlist(info) if info else info
            filename = _basename_from_info(info, ydl)
            title = None
            thumbnail = None
            if info:
                title = info.get("title") or info.get("id")
                thumbnail = info.get("thumbnail")
            if filename:
                _keep_only_in_downloads(filename)
            store.update(
                job_id,
                status="done",
                percent=100,
                eta=0,
                title=title,
                thumbnail=thumbnail,
                filename=filename,
                error=None,
                message="Saved.",
            )
    except Exception as exc:  # noqa: BLE001 — mapped to job.error for the UI
        store.update(
            job_id,
            status="error",
            error=human_error(exc),
            message=None,
        )


def _apply_progress(job_id: str, d: dict[str, Any]) -> None:
    status = d.get("status")
    info = d.get("info_dict") or {}
    extras: dict[str, Any] = {}
    if info.get("title"):
        extras["title"] = info["title"]
    if info.get("thumbnail"):
        extras["thumbnail"] = info["thumbnail"]

    if status == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        downloaded = d.get("downloaded_bytes") or 0
        percent: float | None = None
        if total:
            percent = round(min(100.0, downloaded / total * 100.0), 1)
        store.update(
            job_id,
            status="downloading",
            percent=percent,
            eta=d.get("eta"),
            speed=d.get("speed"),
            message="Downloading…",
            **extras,
        )
    elif status == "finished":
        fname = d.get("filename")
        extras_finished: dict[str, Any] = {"message": "Processing / merging…"}
        if fname:
            extras_finished["filename"] = Path(fname).name
        store.update(
            job_id,
            status="processing",
            percent=100,
            **extras,
            **extras_finished,
        )
    elif status == "error":
        store.update(job_id, status="error", error="Download failed.")


def _unwrap_playlist(info: dict[str, Any]) -> dict[str, Any]:
    if info.get("_type") != "playlist":
        return info
    for entry in info.get("entries") or []:
        if entry:
            return entry
    return info


def _keep_only_in_downloads(filename: str) -> None:
    """Make sure the finished file exists only in DOWNLOAD_DIR, never in two places."""
    dest = DOWNLOAD_DIR / filename
    extra = ROOT / filename
    try:
        if not extra.is_file():
            return
        if extra.resolve() == dest.resolve():
            return
        if dest.is_file():
            extra.unlink()
            return
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(extra), str(dest))
    except OSError:
        return


def _basename_from_info(info: dict[str, Any] | None, ydl: Any) -> str | None:
    if not info:
        return None
    candidates: list[str] = []
    for key in ("filepath", "_filename"):
        val = info.get(key)
        if val:
            candidates.append(str(val))
    for item in info.get("requested_downloads") or []:
        if not item:
            continue
        for key in ("filepath", "filename"):
            val = item.get(key)
            if val:
                candidates.append(str(val))
    try:
        prepared = ydl.prepare_filename(info)
    except Exception:
        prepared = None
    if prepared:
        candidates.append(prepared)
        path = Path(prepared)
        for ext in ("mp4", "mkv", "webm", "m4a", "mp3", "opus", "ogg", "mov"):
            candidates.append(str(path.with_suffix("." + ext)))

    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return path.name
    if candidates:
        return Path(candidates[0]).name
    return None
