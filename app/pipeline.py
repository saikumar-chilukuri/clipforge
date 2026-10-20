"""Run the full job pipeline in a background thread."""

import threading
import traceback

from . import analyzer, downloader, renderer, store, transcriber


def _set(job_id: str, stage: str = None, progress: float = None, message: str = None, **fields):
    payload = {}
    if stage is not None:
        payload["stage"] = stage
    if progress is not None:
        payload["progress"] = round(min(max(progress, 0.0), 1.0), 4)
    if message is not None:
        payload["message"] = message
    payload.update(fields)
    store.update_job(job_id, **payload)


def _seconds_to_mmss(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def run_job(job_id: str):
    job = store.get_job(job_id)
    if job is None:
        return

    settings = None
    from .config import load_settings

    settings = load_settings()
    api_key = settings["groq_api_key"]
    options = job.get("options", {})
    work_dir = store.job_dir(job_id)

    try:
        if not api_key:
            raise RuntimeError(
                "No Groq API key configured. Open Settings and paste a free key from console.groq.com/keys."
            )

        # 1. Download -------------------------------------------------------
        _set(job_id, stage="downloading", progress=0.0, message="Starting download")

        def dl_progress(p, msg):
            _set(job_id, progress=p * 0.25, message=msg)

        meta = downloader.download(
            job["url"], work_dir, max_height=int(settings.get("max_height", 720)), progress_cb=dl_progress
        )
        duration = float(meta["duration"] or 0)
        if duration < 15:
            raise RuntimeError("This video is too short to clip (needs at least 15 seconds).")
        if duration > 4 * 3600:
            raise RuntimeError("This video is longer than 4 hours, which is not supported yet.")

        _set(
            job_id,
            progress=0.25,
            message=f"Downloaded “{meta['title']}”",
            meta={
                "title": meta["title"],
                "duration": duration,
                "thumbnail": meta["thumbnail"],
                "uploader": meta["uploader"],
            },
        )

        # 2. Transcribe -----------------------------------------------------
        _set(job_id, stage="transcribing", progress=0.26, message="Preparing audio")
        from pathlib import Path

        def tr_progress(p, msg):
            _set(job_id, progress=0.26 + p * 0.29, message=msg)

        transcript = transcriber.transcribe(
            Path(meta["path"]),
            work_dir,
            api_key=api_key,
            model=settings["whisper_model"],
            duration=duration,
            progress_cb=tr_progress,
        )

        # 3. Analyze --------------------------------------------------------
        _set(job_id, stage="analyzing", progress=0.56, message="Finding the best moments")

        def an_progress(p, msg):
            _set(job_id, progress=0.56 + p * 0.14, message=msg)

        clips = analyzer.analyze(
            transcript,
            duration=duration,
            api_key=api_key,
            model=settings["llm_model"],
            num_clips=int(options.get("num_clips", 8)),
            min_len=int(options.get("min_len", 30)),
            max_len=int(options.get("max_len", 60)),
            progress_cb=an_progress,
        )

        # 4. Render ---------------------------------------------------------
        _set(job_id, stage="rendering", progress=0.70, message=f"Rendering {len(clips)} clips")
        from pathlib import Path as P

        source = P(meta["path"])
        rendered = []
        for i, clip in enumerate(clips):
            _set(
                job_id,
                progress=0.70 + (i / len(clips)) * 0.29,
                message=f"Rendering clip {i + 1} of {len(clips)}: {clip['title']}",
            )
            filename = f"clip_{i + 1:02d}.mp4"
            try:
                renderer.render_clip(
                    source=source,
                    out_path=work_dir / filename,
                    work_dir=work_dir,
                    words=transcript["words"],
                    start=clip["start"],
                    end=clip["end"],
                    ass_name=f"clip_{i + 1:02d}.ass",
                    mode=options.get("layout", "vertical_blur"),
                )
            except renderer.RenderError:
                # Skip a failed clip instead of killing the whole job.
                continue
            rendered.append(
                {
                    **clip,
                    "file": filename,
                    "duration": round(clip["end"] - clip["start"], 1),
                    "label": _seconds_to_mmss(clip["start"]),
                }
            )

        if not rendered:
            raise RuntimeError("All clips failed to render. Try again.")

        _set(job_id, stage="done", progress=1.0, message=f"{len(rendered)} clips ready", clips=rendered)

    except Exception as exc:
        message = str(exc)
        if not message or message == "None":
            message = traceback.format_exc(limit=3)[-400:]
        _set(job_id, stage="error", progress=1.0, message="Failed", error=message)


def start_job(job_id: str):
    thread = threading.Thread(target=run_job, args=(job_id,), daemon=True)
    thread.start()
