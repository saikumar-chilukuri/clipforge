"""Verify burned captions: white text present + karaoke yellow highlight direction."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from app import renderer, ffutil

work = Path(__file__).parent / "data" / "verify"
work.mkdir(parents=True, exist_ok=True)
ffmpeg = ffutil.best_ffmpeg()
print("using ffmpeg:", ffmpeg)

# Solid black 16:9 source so any non-black pixel in caption area = caption text
src = work / "source.mp4"
if not src.exists():
    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:size=1280x720:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
         "-t", "12", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)],
        check=True, capture_output=True,
    )

# Words: 1.00 -> 5.00, spoken every 0.35s
words = []
t = 1.0
for w in ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]:
    words.append({"word": w, "start": t, "end": t + 0.32})
    t += 0.35

out = work / "clip.mp4"
renderer.render_clip(src, out, work, words, start=1.0, end=4.0, ass_name="clip.ass")
print("rendered OK")

# Caption region in the 1080x1920 output: text sits around y=1400-1750 (MarginV 560 from bottom)
def pixel_stats(video, at):
    raw = work / "frame.raw"
    subprocess.run(
        [ffmpeg, "-y", "-ss", str(at), "-i", str(video), "-frames:v", "1",
         "-vf", "crop=1080:500:0:1100", "-pix_fmt", "rgb24", "-f", "rawvideo", str(raw)],
        check=True, capture_output=True,
    )
    data = raw.read_bytes()
    white = yellow = total = 0
    for i in range(0, len(data), 3):
        r, g, b = data[i], data[i + 1], data[i + 2]
        total += 1
        if r > 220 and g > 220 and b > 220:
            white += 1
        elif r > 180 and g > 180 and b < 90:
            yellow += 1
    return white, yellow, total

for at in (1.15, 2.20, 2.80):
    w, y, t_ = pixel_stats(out, at)
    print(f"t={at:>4}s  white={w:>6}  yellow={y:>6}  ({100*(w+y)/t_:.2f}% text pixels)")
