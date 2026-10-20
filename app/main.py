"""ClipForge — turn YouTube videos into vertical AI-clipped shorts."""

import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import pipeline, store
from .config import load_settings, save_settings
from .renderer import MODES

app = FastAPI(title="ClipForge")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.middleware("http")
async def no_stale_static(request, call_next):
    """Always revalidate static files so UI fixes show up on plain reload."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response

YOUTUBE_RE = re.compile(
    r"^https?://(www\.|m\.|music\.)?(youtube\.com/(watch\?|shorts/|live/|embed/)|youtu\.be/)[^\s]+$",
    re.IGNORECASE,
)


class JobRequest(BaseModel):
    url: str
    num_clips: int = 8
    min_len: int = 30
    max_len: int = 60
    layout: str = "vertical_blur"


class SettingsRequest(BaseModel):
    groq_api_key: str | None = None
    llm_model: str | None = None
    whisper_model: str | None = None
    max_height: int | None = None


@app.post("/api/jobs")
def create_job(req: JobRequest):
    url = req.url.strip()
    if not YOUTUBE_RE.match(url):
        raise HTTPException(400, "Please paste a valid YouTube link.")
    if req.num_clips < 1 or req.num_clips > 20:
        raise HTTPException(400, "Number of clips must be between 1 and 20.")
    if req.min_len < 10 or req.max_len > 180 or req.min_len >= req.max_len:
        raise HTTPException(400, "Clip length must be between 10 and 180 seconds, with a valid range.")
    if req.layout not in MODES:
        raise HTTPException(400, "Unknown layout mode.")

    settings = load_settings()
    if not settings["groq_api_key"]:
        raise HTTPException(
            400, "Add your free Groq API key in Settings first (console.groq.com/keys)."
        )

    job = store.create_job(
        url,
        options={
            "num_clips": req.num_clips,
            "min_len": req.min_len,
            "max_len": req.max_len,
            "layout": req.layout,
        },
    )
    pipeline.start_job(job["id"])
    return {"id": job["id"]}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    return job


@app.get("/api/jobs")
def list_jobs():
    return {"jobs": store.all_jobs()}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    if not store.delete_job(job_id):
        raise HTTPException(404, "Job not found.")
    return {"ok": True}


@app.get("/api/settings")
def get_settings():
    settings = load_settings()
    key = settings["groq_api_key"]
    return {
        **settings,
        "groq_api_key": key,
        "has_key": bool(key),
        "key_masked": (key[:6] + "…" + key[-4:]) if len(key) > 12 else ("••••" if key else ""),
    }


@app.put("/api/settings")
def put_settings(req: SettingsRequest):
    settings = save_settings(req.model_dump())
    key = settings["groq_api_key"]
    return {**settings, "has_key": bool(key)}


class RangeFileResponse(Response):
    """Minimal HTTP Range support so <video> seeking works in the browser."""

    media_type = "video/mp4"

    def __init__(self, path: Path):
        self.path = path
        self.size = path.stat().st_size
        super().__init__()

    async def __call__(self, scope, receive, send):
        headers = {
            b"content-type": self.media_type.encode(),
            b"accept-ranges": b"bytes",
            b"content-disposition": f'inline; filename="{self.path.name}"'.encode(),
        }
        range_header = None
        for key, value in scope.get("headers", []):
            if key == b"range":
                range_header = value.decode()
        start, end = 0, self.size - 1
        status = 200
        if range_header and range_header.startswith("bytes="):
            try:
                part = range_header[6:].split(",")[0]
                s, _, e = part.partition("-")
                if s:
                    start = int(s)
                if e:
                    end = min(int(e), self.size - 1)
                elif not s:
                    start = max(self.size - int(e), 0)
                status = 206
            except ValueError:
                start, end = 0, self.size - 1

        if start > end or start >= self.size:
            await send({"type": "http.response.start", "status": 416, "headers": [(b"content-range", f"bytes */{self.size}".encode())]})
            await send({"type": "http.response.body", "body": b""})
            return

        length = end - start + 1
        headers.append((b"content-length", str(length).encode()))
        if status == 206:
            headers.append((b"content-range", f"bytes {start}-{end}/{self.size}".encode()))

        await send({"type": "http.response.start", "status": status, "headers": headers})
        with open(self.path, "rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                await send({"type": "http.response.body", "body": chunk, "more_body": remaining > 0})


@app.get("/api/clips/{job_id}/{filename}")
def get_clip(job_id: str, filename: str, download: int = 0):
    if "/" in filename or ".." in filename or not filename.endswith(".mp4"):
        raise HTTPException(400, "Bad filename.")
    path = store.job_dir(job_id) / filename
    if not path.exists():
        raise HTTPException(404, "Clip not found.")
    if download:
        return FileResponse(path, media_type="video/mp4", filename=filename)
    return RangeFileResponse(path)


@app.get("/api/jobs/{job_id}/thumb")
def job_thumb(job_id: str):
    """Serve the source video's first frame as a placeholder."""
    path = store.job_dir(job_id) / "source.mp4"
    if not path.exists():
        raise HTTPException(404, "Not found.")
    import subprocess
    import tempfile

    from .ffutil import find_ffmpeg

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        out = Path(tmp.name)
    try:
        subprocess.run(
            [find_ffmpeg(), "-y", "-i", str(path), "-ss", "00:00:03", "-frames:v", "1", "-q:v", "4", str(out)],
            capture_output=True,
        )
        if not out.exists():
            raise HTTPException(404, "No frame.")
        return FileResponse(out, media_type="image/jpeg")
    finally:
        out.unlink(missing_ok=True)


@app.exception_handler(404)
async def spa_fallback(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"detail": "Not found"}, status_code=404)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
