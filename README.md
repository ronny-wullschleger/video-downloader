# Celluloid

A local web UI that pulls a video onto this machine. Paste either:

- a webpage URL that contains a video (YouTube, Vimeo, news sites — anything [yt-dlp](https://github.com/yt-dlp/yt-dlp) supports), or
- a direct video file URL

then pick a quality and download. Files are written to `./downloads` and never uploaded anywhere.

**Only download content you have the right to download.**

## Prerequisites

**Either** Docker (see [Docker](#docker)), **or** a local Python install:

- Python **3.11+**
- **ffmpeg** on your `PATH` (needed to merge DASH/HLS video+audio; without it, some sites will fail with a clear error)
- **yt-dlp** is installed from `requirements.txt` via pip (do not rely on a system copy)

Check ffmpeg:

```bash
ffmpeg -version
```

On Debian/Ubuntu: `sudo apt install ffmpeg`. On macOS: `brew install ffmpeg`. On Windows: install from [ffmpeg.org](https://ffmpeg.org/) and add it to PATH.

## Install

```bash
cd video-downloader
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run

From the project directory, with the venv active:

```bash
python app.py
```

Or:

```bash
python -m uvicorn app:app --host 127.0.0.1 --port 8765
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). The same process serves the UI, the API, and saved files under `/files/…`.

Quality options: **best** (default, merged video+audio), **1080p**, **720p**, **audio**.

`python app.py` listens on `127.0.0.1:8765` by default. Override with `CELLULOID_HOST` and `CELLULOID_PORT` if needed.

## Docker

The image includes Python, ffmpeg, and the app. Files land in `./downloads` on the host via a bind mount. The UI is published only on localhost, same as a local `python app.py` run.

Start Docker Desktop / Rancher Desktop first so the daemon is running.

### docker compose (recommended)

From the project directory:

```bash
docker compose up --build
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). Stop with `Ctrl+C`, or `docker compose down`.

### docker build / run

```bash
docker build -t celluloid .
docker run --rm -p 127.0.0.1:8765:8765 -v ./downloads:/app/downloads celluloid
```

PowerShell:

```powershell
docker build -t celluloid .
docker run --rm -p 127.0.0.1:8765:8765 -v ${PWD}/downloads:/app/downloads celluloid
```

The container listens on `0.0.0.0:8765` inside the network namespace (`CELLULOID_HOST` / `CELLULOID_PORT`). The compose file maps that to `127.0.0.1:8765` on the host.

## Tests

```bash
python -m pytest
```

Tests mock yt-dlp. They do not hit the network.

## Notes

- URLs must be `http` or `https`.
- Playlist links download the first item only.
- Saved names look like `Title [id].mp4` inside `downloads/`.
