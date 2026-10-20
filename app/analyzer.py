"""Pick the best clip moments from a transcript using a free Groq LLM."""

import json
import re


class AnalyzeError(Exception):
    pass


def _fmt_ts(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _build_transcript(segments: list[dict], max_chars: int = 60000) -> str:
    lines = []
    size = 0
    for seg in segments:
        line = f"[{_fmt_ts(seg['start'])}] {seg['text'].strip()}"
        if size + len(line) > max_chars:
            # For very long videos, keep samples evenly spread across the runtime.
            lines.append(f"[{_fmt_ts(seg['start'])}] ...")
            break
        lines.append(line)
        size += len(line) + 1
    return "\n".join(lines)


PROMPT = """You are an expert short-form video editor who turns long videos into viral clips for TikTok, Instagram Reels and YouTube Shorts.

You are given a TRANSCRIPT of a YouTube video with a timestamp before each line, like [12:34].

Select exactly {num_clips} moments that would make the best standalone short clips.

Rules for each clip:
- Start and end must be timestamp-based; pick a natural start (mid-thought openers and strong hooks are fine) and a natural end (punchline, conclusion, completed idea).
- Duration must be between {min_len} and {max_len} seconds. Prefer clips in the middle of that range.
- Each clip must be self-contained: someone who never saw the full video should understand it.
- Prioritize: strong hook in the first 2 seconds, emotion/debate/surprise/storytelling, practical value, bold claims, tension and payoff.
- Clips must not overlap each other.
- Choose moments spread across the whole video, not all from one section.

Also write for each clip:
- "title": a short internal title, max 8 words.
- "hook": the first on-screen caption line that grabs attention, max 12 words, in the video's language.
- "caption": a ready-to-post social caption, 1-3 sentences, in the video's language, no hashtags.
- "hashtags": 3-6 relevant hashtags with # prefix.
- "reason": one short sentence on why this moment has retention potential.

Respond with ONLY a JSON object, no markdown, no commentary:
{{"clips": [{{"start": <seconds as number>, "end": <seconds as number>, "title": "...", "hook": "...", "caption": "...", "hashtags": ["#..."], "reason": "..."}}]}}

TRANSCRIPT:
{transcript}
"""


def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        raise AnalyzeError(f"Model did not return JSON: {raw[:200]}")
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AnalyzeError(f"Could not parse model JSON: {exc}") from exc


def _validate(clips: list[dict], duration: float, num_clips: int, min_len: float, max_len: float) -> list[dict]:
    cleaned = []
    for clip in clips:
        try:
            start = max(0.0, min(float(clip["start"]), duration))
            end = max(0.0, min(float(clip["end"]), duration))
        except (KeyError, TypeError, ValueError):
            continue
        if end - start < 3:
            continue
        if end - start > max_len:
            end = start + max_len
        if end - start < min_len:
            # Try to grow the clip; clamp to video bounds.
            grow = (min_len - (end - start)) / 2
            start = max(0.0, start - grow)
            end = min(duration, start + min_len)
            if end - start < min_len:
                start = max(0.0, end - min_len)
        if end - start < min_len * 0.6 or start >= end:
            continue
        cleaned.append(
            {
                "start": round(start, 2),
                "end": round(end, 2),
                "title": str(clip.get("title") or "Clip")[:80],
                "hook": str(clip.get("hook") or "")[:120],
                "caption": str(clip.get("caption") or ""),
                "hashtags": [str(h) for h in (clip.get("hashtags") or [])][:6],
                "reason": str(clip.get("reason") or "")[:200],
            }
        )

    # Drop overlaps: keep the earlier clip.
    cleaned.sort(key=lambda c: c["start"])
    unique = []
    for clip in cleaned:
        if unique and clip["start"] < unique[-1]["end"] - 0.5:
            if clip["end"] - clip["start"] > unique[-1]["end"] - unique[-1]["start"]:
                unique[-1] = clip
            continue
        unique.append(clip)
    return unique[:num_clips]


def analyze(
    transcript: dict,
    duration: float,
    api_key: str,
    model: str,
    num_clips: int = 8,
    min_len: int = 30,
    max_len: int = 60,
    progress_cb=None,
) -> list[dict]:
    from groq import Groq

    client = Groq(api_key=api_key)
    prompt = PROMPT.format(
        num_clips=num_clips,
        min_len=min_len,
        max_len=max_len,
        transcript=_build_transcript(transcript["segments"]),
    )

    if progress_cb:
        progress_cb(0.1, "Asking the model for the best moments")

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            max_tokens=4096,
        )
    except Exception as exc:
        # If the chosen model vanished from Groq's lineup, fall back to a known-good one.
        if "model_not_found" in str(exc) or "does not exist" in str(exc):
            model = "openai/gpt-oss-120b"
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.6,
                    max_tokens=4096,
                )
            except Exception as exc2:
                raise AnalyzeError(f"Groq request failed: {exc2}") from exc2
        else:
            raise AnalyzeError(f"Groq request failed: {exc}") from exc

    if progress_cb:
        progress_cb(0.9, "Selecting highlights")

    raw = response.choices[0].message.content or ""
    data = _extract_json(raw)
    clips = data.get("clips")
    if not isinstance(clips, list) or not clips:
        raise AnalyzeError("The model returned no clips. Try again.")

    result = _validate(clips, duration, num_clips, min_len, max_len)
    if not result:
        raise AnalyzeError("No valid clips were found in the model response. Try again.")
    if progress_cb:
        progress_cb(1.0, f"Found {len(result)} moments")
    return result
