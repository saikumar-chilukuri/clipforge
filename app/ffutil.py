"""Locate an ffmpeg binary that has the filters we need (libass for subtitles)."""

import shutil
from pathlib import Path

_PREFERRED = [
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",  # Homebrew "ffmpeg-full" (keg-only, has libass)
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
    "/opt/homebrew/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    "/usr/bin/ffmpeg",
]

_resolved: str | None = None
_probe_resolved: str | None = None


def find_ffmpeg() -> str:
    global _resolved
    if _resolved:
        return _resolved
    for path in _PREFERRED:
        if Path(path).exists():
            _resolved = path
            return _resolved
    found = shutil.which("ffmpeg")
    if found:
        _resolved = found
        return _resolved
    raise RuntimeError(
        "ffmpeg not found. Install it with: brew install ffmpeg ffmpeg-full"
    )


def has_subtitles_filter(ffmpeg_path: str) -> bool:
    import subprocess

    try:
        out = subprocess.run([ffmpeg_path, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=20)
        return " subtitles " in out.stdout or "\tsubtitles" in out.stdout
    except Exception:
        return False


def best_ffmpeg() -> str:
    """Return an ffmpeg path that supports the subtitles filter if possible."""
    path = find_ffmpeg()
    if has_subtitles_filter(path):
        return path
    full = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
    if Path(full).exists() and full != path:
        return full
    return path


def find_ffprobe() -> str:
    """ffprobe sits next to the ffmpeg binary we use."""
    global _probe_resolved
    if _probe_resolved:
        return _probe_resolved
    sibling = Path(find_ffmpeg()).parent / "ffprobe"
    if sibling.exists():
        _probe_resolved = str(sibling)
        return _probe_resolved
    found = shutil.which("ffprobe")
    if found:
        _probe_resolved = found
        return _probe_resolved
    raise RuntimeError("ffprobe not found. Install it with: brew install ffmpeg ffmpeg-full")
