"""Transcribe audio with Groq's free Whisper API, chunked for the 25MB file limit."""

import subprocess
from pathlib import Path

CHUNK_SECONDS = 600  # 10 minutes per chunk, well under Groq's upload limit


class TranscribeError(Exception):
    pass


def _get(obj, key, default=None):
    """Read a field from either a dict or an SDK object (Groq returns both shapes)."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_chunk(source: Path, out: Path, start: float, seconds: float) -> None:
    from .ffutil import find_ffmpeg

    cmd = [
        find_ffmpeg(), "-y",
        "-ss", f"{start:.2f}",
        "-i", str(source),
        "-t", f"{seconds:.2f}",
        "-vn",
        "-ac", "1", "-ar", "16000",
        "-b:a", "48k",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise TranscribeError(f"Audio extraction failed: {result.stderr[-500:]}")


def _fallback_words(segments: list[dict]) -> list[dict]:
    """Distribute words evenly across a segment when word timestamps are missing."""
    words = []
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        tokens = text.split()
        span = max(seg["end"] - seg["start"], 0.01)
        step = span / len(tokens)
        for i, token in enumerate(tokens):
            words.append(
                {"word": token, "start": seg["start"] + i * step, "end": seg["start"] + (i + 1) * step}
            )
    return words


def transcribe(source: Path, work_dir: Path, api_key: str, model: str, duration: float, progress_cb=None) -> dict:
    """Return {"segments": [...], "words": [...]} with absolute timestamps."""
    from groq import Groq

    client = Groq(api_key=api_key)
    all_segments: list[dict] = []
    all_words: list[dict] = []
    chunk_paths: list[Path] = []

    start = 0.0
    index = 0
    total_chunks = max(int(duration // CHUNK_SECONDS) + (1 if duration % CHUNK_SECONDS else 0), 1)

    while start < duration:
        index += 1
        length = min(CHUNK_SECONDS, duration - start)
        chunk_path = work_dir / f"chunk_{index:03d}.mp3"
        _extract_chunk(source, chunk_path, start, length)
        chunk_paths.append(chunk_path)

        if progress_cb:
            progress_cb((index - 1) / total_chunks * 0.9, f"Transcribing part {index} of {total_chunks}")

        try:
            with open(chunk_path, "rb") as fh:
                result = client.audio.transcriptions.create(
                    file=(chunk_path.name, fh.read()),
                    model=model,
                    response_format="verbose_json",
                    timestamp_granularities=["word", "segment"],
                )
        except Exception as exc:
            raise TranscribeError(f"Groq transcription failed: {exc}") from exc

        for seg in _get(result, "segments", None) or []:
            seg_start = _get(seg, "start")
            seg_end = _get(seg, "end")
            if seg_start is None or seg_end is None:
                continue
            seg_dict = {
                "start": float(seg_start) + start,
                "end": float(seg_end) + start,
                "text": str(_get(seg, "text", "")).strip(),
            }
            all_segments.append(seg_dict)

        words = _get(result, "words", None) or []
        if words:
            for w in words:
                w_start = _get(w, "start")
                w_end = _get(w, "end")
                if w_start is None or w_end is None:
                    continue
                all_words.append(
                    {"word": str(_get(w, "word", "")).strip(), "start": float(w_start) + start, "end": float(w_end) + start}
                )
        else:
            chunk_segs = [
                {"start": float(_get(s, "start", 0.0)), "end": float(_get(s, "end", 0.0)), "text": str(_get(s, "text", "")).strip()}
                for s in (_get(result, "segments", None) or [])
            ]
            all_words.extend(_fallback_words(chunk_segs))

        chunk_path.unlink(missing_ok=True)
        start += length

    if progress_cb:
        progress_cb(1.0, "Transcription complete")

    if not all_segments:
        raise TranscribeError("No speech detected in this video.")

    return {"segments": all_segments, "words": all_words}
