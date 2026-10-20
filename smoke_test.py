"""Smoke test: render a captioned vertical clip from a synthetic source."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app import renderer

work = Path(__file__).parent / "data" / "smoke"
work.mkdir(parents=True, exist_ok=True)

# Synthetic 16:9 test video with tone audio
import subprocess

src = work / "source.mp4"
if not src.exists():
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
        "-t", "10", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src),
    ], check=True, capture_output=True)

words = []
t = 1.0
for w in ["This", "is", "a", "viral", "moment", "that", "everyone", "needs", "to", "see", "right", "now"]:
    words.append({"word": w, "start": t, "end": t + 0.32})
    t += 0.35

out = work / "clip_test.mp4"
renderer.render_clip(src, out, work, words, start=1.0, end=5.0, ass_name="clip_test.ass")
print("rendered:", out, out.stat().st_size, "bytes")

# Extract a frame at 2.5s to visually verify captions
frame = work / "frame.jpg"
subprocess.run(["ffmpeg", "-y", "-ss", "2.5", "-i", str(out), "-frames:v", "1", str(frame)], check=True, capture_output=True)
print("frame:", frame)
