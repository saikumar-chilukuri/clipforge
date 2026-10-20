"""Cut vertical (and other) clips with burned-in karaoke captions using ffmpeg."""

import subprocess
from pathlib import Path

# Render modes: id -> (label, aspect-correct output size handled per-mode)
MODES = {
    "vertical_blur": "Vertical 9:16 · full frame (blurred background)",
    "vertical": "Vertical 9:16 · close-up (crops the sides)",
    "square": "Square 1:1 · center crop",
    "original": "Original aspect · no crop",
}

MAX_WORDS_PER_LINE = 4
MAX_CHARS_PER_LINE = 20
LINE_GAP = 0.6  # start a new caption line when the pause exceeds this


class RenderError(Exception):
    pass


def _escape_ass(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def _group_words(words: list[dict], start: float, end: float) -> list[list[dict]]:
    inside = [w for w in words if w["end"] > start and w["start"] < end and w.get("word")]
    lines: list[list[dict]] = []
    current: list[dict] = []
    for word in inside:
        if current:
            too_big = len(current) >= MAX_WORDS_PER_LINE
            too_long = len(" ".join(w["word"] for w in current)) + len(word["word"]) + 1 > MAX_CHARS_PER_LINE
            gap = word["start"] - current[-1]["end"]
            if too_big or too_long or gap > LINE_GAP:
                lines.append(current)
                current = []
        current.append(word)
    if current:
        lines.append(current)
    return lines


def build_ass(words: list[dict], start: float, end: float, width: int, height: int) -> str:
    """Build an ASS subtitle file sized for the output video."""
    font = max(int(width * 0.085), 12)
    outline = max(int(width * 0.0065), 2)
    margin_v = int(height * 0.29)
    margin_s = int(width * 0.065)

    style = (
        f"Style: Clip,Impact,{font},&H00FFFFFF,&H0000FFFF,&H00101010,&H96000000,"
        f"-1,0,0,0,100,100,0.6,0,1,{outline},2,2,{margin_s},{margin_s},{margin_v},1"
    )
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        style,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    def ts(seconds: float) -> str:
        seconds = max(seconds, 0.0)
        h = int(seconds // 3600)
        m = int(seconds % 3600 // 60)
        s = seconds % 60
        return f"{h}:{m:02d}:{s:05.2f}"

    groups = _group_words(words, start, end)
    for i, group in enumerate(groups):
        line_start = max(group[0]["start"], start) - 0.05
        hard_end = group[-1]["end"] + 0.25
        if i + 1 < len(groups):
            next_start = groups[i + 1][0]["start"] - 0.05
            line_end = min(hard_end, next_start, end)
        else:
            line_end = min(hard_end, end)
        if line_end <= line_start:
            continue

        # Karaoke: each word lights up (turns yellow) as it is spoken.
        # \k tags inside a brace block apply to the plain text that follows it,
        # so interleave one brace block per word.
        segments = []
        cursor = line_start
        for idx, w in enumerate(group):
            gap_cs = max(int((w["start"] - cursor) * 100), 0)
            dur_cs = max(int((w["end"] - w["start"]) * 100), 1)
            lead = gap_cs if gap_cs else (1 if idx else 0)
            if lead:
                segments.append("{" + f"\\k{lead}" + "}")
            segments.append("{" + f"\\k{dur_cs}" + "}")
            segments.append(_escape_ass(w["word"]))
            cursor = w["end"]
            if idx < len(group) - 1:
                segments.append(" ")
        text = "".join(segments)
        lines.append(f"Dialogue: 0,{ts(line_start)},{ts(line_end)},Clip,,0,0,0,,{text}")

    return "\n".join(lines) + "\n"


def probe_size(video: Path) -> tuple[int, int]:
    from .ffutil import find_ffprobe

    result = subprocess.run(
        [find_ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video)],
        capture_output=True,
        text=True,
    )
    try:
        w, h = result.stdout.strip().split(",")[:2]
        return int(w), int(h)
    except ValueError:
        raise RenderError("Could not read source video dimensions.")


def _output_size(mode: str, src_w: int, src_h: int) -> tuple[int, int]:
    if mode == "square":
        return 1080, 1080
    if mode == "original":
        return 1080, max(round(1080 * src_h / src_w), 2)
    return 1080, 1920  # both vertical modes


def render_clip(
    source: Path,
    out_path: Path,
    work_dir: Path,
    words: list[dict],
    start: float,
    end: float,
    ass_name: str,
    mode: str = "vertical_blur",
) -> None:
    from .ffutil import best_ffmpeg

    if mode not in MODES:
        mode = "vertical_blur"
    ffmpeg = best_ffmpeg()
    duration = max(end - start, 0.5)

    src_w, src_h = probe_size(source)
    out_w, out_h = _output_size(mode, src_w, src_h)

    ass_path = work_dir / ass_name
    ass_path.write_text(build_ass(words, start, end, out_w, out_h), encoding="utf-8")

    common_out = [
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "160k",
        "-movflags", "+faststart",
        out_path.name,
    ]

    if mode == "vertical_blur":
        # Full frame preserved: source scaled to width, blurred & darkened copy fills the rest.
        fc = (
            f"[0:v]scale={out_w}:-2:flags=lanczos[fg];"
            f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={out_w}:{out_h},gblur=sigma=25,eq=brightness=-0.12:saturation=0.85[bg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2:format=auto,"
            f"subtitles={ass_name}[v]"
        )
        cmd = [
            ffmpeg, "-y",
            "-ss", f"{start:.2f}",
            "-i", source.name,
            "-t", f"{duration:.2f}",
            "-filter_complex", fc,
            "-map", "[v]",
            "-map", "0:a",
            *common_out,
        ]
    else:
        if mode == "vertical":
            crop = "crop=ih*9/16:ih"
        elif mode == "square":
            crop = r"crop=min(iw\,ih):min(iw\,ih)"
        else:  # original
            crop = ""
        scale = f"scale={out_w}:{out_h}:flags=lanczos" if mode != "original" else f"scale={out_w}:-2:flags=lanczos"
        parts = [p for p in (crop, scale, f"subtitles={ass_name}") if p]
        cmd = [
            ffmpeg, "-y",
            "-ss", f"{start:.2f}",
            "-i", source.name,
            "-t", f"{duration:.2f}",
            "-vf", ",".join(parts),
            *common_out,
        ]

    result = subprocess.run(cmd, capture_output=True, text=True, cwd=work_dir)
    if result.returncode != 0 or not out_path.exists():
        raise RenderError(f"ffmpeg failed: {result.stderr[-600:]}")
