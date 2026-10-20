import json
import threading
import time
import uuid
from pathlib import Path

from .config import JOBS_DIR

_lock = threading.Lock()

STAGES = ["queued", "downloading", "transcribing", "analyzing", "rendering", "done"]
STAGE_LABELS = {
    "queued": "Queued",
    "downloading": "Downloading video",
    "transcribing": "Transcribing audio",
    "analyzing": "Finding the best moments",
    "rendering": "Rendering clips",
    "done": "Done",
    "error": "Failed",
}


def job_dir(job_id: str) -> Path:
    return JOBS_DIR / job_id


def _path(job_id: str) -> Path:
    return job_dir(job_id) / "job.json"


def create_job(url: str, options: dict) -> dict:
    job_id = uuid.uuid4().hex[:12]
    job_dir(job_id).mkdir(parents=True, exist_ok=True)
    job = {
        "id": job_id,
        "url": url,
        "options": options,
        "stage": "queued",
        "progress": 0.0,
        "message": "Waiting to start",
        "error": None,
        "created": time.time(),
        "meta": {},
        "clips": [],
    }
    _write(job)
    return job


def _write(job: dict) -> None:
    _path(job["id"]).write_text(json.dumps(job, indent=2))


def get_job(job_id: str) -> dict | None:
    path = _path(job_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def update_job(job_id: str, **fields) -> dict | None:
    with _lock:
        job = get_job(job_id)
        if job is None:
            return None
        job.update(fields)
        _write(job)
        return job


def all_jobs(limit: int = 20) -> list[dict]:
    jobs = []
    for meta in sorted(JOBS_DIR.glob("*/job.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            job = json.loads(meta.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        jobs.append(
            {
                "id": job["id"],
                "url": job["url"],
                "stage": job["stage"],
                "created": job["created"],
                "title": job.get("meta", {}).get("title", ""),
                "clip_count": len(job.get("clips", [])),
            }
        )
        if len(jobs) >= limit:
            break
    return jobs


def delete_job(job_id: str) -> bool:
    job = get_job(job_id)
    if job is None:
        return False
    import shutil

    shutil.rmtree(job_dir(job_id), ignore_errors=True)
    return True
