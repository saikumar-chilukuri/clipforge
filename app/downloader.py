"""Download a YouTube video with yt-dlp."""

from pathlib import Path

import yt_dlp


class DownloadError(Exception):
    pass


def download(url: str, out_dir: Path, max_height: int = 720, progress_cb=None) -> dict:
    """Download the video to out_dir/source.mp4 and return metadata."""

    def hook(d):
        if progress_cb is None:
            return
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            if total:
                progress_cb(min(done / total, 1.0), "Downloading video")
        elif d.get("status") == "finished":
            progress_cb(1.0, "Download complete")

    opts = {
        "format": f"bv*[height<={max_height}]+ba/b[height<={max_height}]/b",
        "outtmpl": str(out_dir / "source.%(ext)s"),
        "merge_output_format": "mp4",
        "progress_hooks": [hook],
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "retries": 3,
    }
    try:
        from .ffutil import find_ffmpeg

        opts["ffmpeg_location"] = find_ffmpeg()
    except RuntimeError:
        pass

    last_error = None
    # YouTube often blocks the default web client for some videos; try alternates.
    client_attempts = [
        None,
        ["android"],
        ["ios"],
        ["web_embedded"],
        ["tv"],
    ]
    for clients in client_attempts:
        attempt_opts = dict(opts)
        if clients:
            attempt_opts["extractor_args"] = {"youtube": {"player_client": clients}}
        try:
            with yt_dlp.YoutubeDL(attempt_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                break
        except yt_dlp.utils.DownloadError as exc:
            last_error = str(exc)
            continue
    else:
        raise DownloadError(last_error or "Download failed.") from None

    source = out_dir / "source.mp4"
    if not source.exists():
        # Some formats merge to mkv/webm; normalize later. Look for any source.* file.
        candidates = list(out_dir.glob("source.*"))
        if not candidates:
            raise DownloadError("Download finished but no file was produced.")
        source = candidates[0]

    return {
        "path": str(source),
        "title": info.get("title") or "Untitled video",
        "duration": info.get("duration") or 0,
        "thumbnail": info.get("thumbnail") or "",
        "uploader": info.get("uploader") or info.get("channel") or "",
        "webpage_url": info.get("webpage_url") or url,
    }
