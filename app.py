"""Celluloid — local video downloader web UI."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from downloader import (
    VALID_QUALITIES,
    ffmpeg_available,
    human_error,
    probe,
    start_download,
    store,
)
from downloader import DOWNLOAD_DIR
from validation import InvalidURL

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Celluloid", docs_url=None, redoc_url=None)


class DownloadRequest(BaseModel):
    url: str = Field(..., min_length=1)
    quality: str = "best"


class ProbeRequest(BaseModel):
    url: str = Field(..., min_length=1)


def _detail(exc: BaseException, fallback: str) -> str:
    if isinstance(exc, (InvalidURL, ValueError)):
        return str(exc)
    return human_error(exc) or fallback


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
def api_status() -> dict:
    return {"ffmpeg": ffmpeg_available()}


@app.post("/api/probe")
def api_probe(body: ProbeRequest) -> dict:
    try:
        return probe(body.url)
    except InvalidURL as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=_detail(exc, "Could not read that URL.")) from None


@app.post("/api/download")
def api_download(body: DownloadRequest) -> dict:
    quality = (body.quality or "best").strip().lower()
    if quality not in VALID_QUALITIES:
        raise HTTPException(
            status_code=400,
            detail="Unknown quality. Choose best, 1080p, 720p, or audio.",
        )
    try:
        job = start_download(body.url, quality)
    except InvalidURL as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=_detail(exc, "Could not start the download.")) from None
    return job.snapshot()


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str) -> dict:
    snap = store.snapshot(job_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="Unknown download.")
    return snap


@app.get("/api/jobs/{job_id}/events")
async def api_job_events(job_id: str) -> StreamingResponse:
    if store.get(job_id) is None:
        raise HTTPException(status_code=404, detail="Unknown download.")

    async def generate():
        last = None
        while True:
            snap = store.snapshot(job_id)
            if snap is None:
                yield f"data: {json.dumps({'status': 'error', 'error': 'Unknown download.'})}\n\n"
                break
            encoded = json.dumps(snap)
            if encoded != last:
                yield f"data: {encoded}\n\n"
                last = encoded
                if snap["status"] in {"done", "error"}:
                    break
            await asyncio.sleep(0.25)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


app.mount("/files", StaticFiles(directory=str(DOWNLOAD_DIR)), name="files")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def main() -> None:
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()
