"""Determine karaoke highlight semantics: PRIMARY vs SECONDARY over time."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from app import renderer, ffutil

work = Path(__file__).parent / "data" / "karaoke"
work.mkdir(parents=True, exist_ok=True)
ffmpeg = ffutil.best_ffmpeg()

src = work / "source.mp4"
if not src.exists():
    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:size=1280x720:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
         "-t", "12", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)],
        check=True, capture_output=True,
    )

# 4 words, spoken at 1.00, 1.35, 1.70, 2.05 (clip starts at 1.0)
words = [{"word": w, "start": s, "end": s + 0.32}
         for w, s in [("AAAA", 1.00), ("BBBB", 1.35), ("CCCC", 1.70), ("DDDD", 2.05)]]

ass = renderer.build_ass(words, 1.0, 3.0)
# Force unambiguous colors: primary=RED, secondary=GREEN, outline=black
ass = ass.replace("&H00FFFFFF", "&H000000FF").replace("&H0000FFFF&", "&H0000FF00&")
(work / "k.ass").write_text(ass)

out = work / "clip.mp4"
vf = "crop=ih*9/16:ih,scale=1080:1920:flags=lanczos,subtitles=k.ass"
r = subprocess.run(
    [ffmpeg, "-y", "-ss", "1.0", "-i", "source.mp4", "-t", "2.0", "-vf", vf,
     "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "copy", "clip.mp4"],
    capture_output=True, text=True, cwd=work,
)
if r.returncode != 0:
    print(r.stderr[-400:]); sys.exit(1)

def counts(video, at):
    raw = work / "f.raw"
    subprocess.run(
        [ffmpeg, "-y", "-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1",
         "-vf", "crop=1080:500:0:1100", "-pix_fmt", "rgb24", "-f", "rawvideo", str(raw)],
        capture_output=True,
    )
    data = raw.read_bytes()
    red = green = 0
    for i in range(0, len(data), 3):
        r_, g_, b_ = data[i], data[i + 1], data[i + 2]
        if r_ > 170 and g_ < 100 and b_ < 100:
            red += 1
        elif g_ > 170 and r_ < 100 and b_ < 100:
            green += 1
    return red, green

print("word speech windows: AAAA 0.00-0.32 | BBBB 0.35-0.67 | CCCC 0.70-1.02 | DDDD 1.05-1.37 (relative to clip)")
print("t(s rel)  RED(=primary)  GREEN(=secondary)")
for rel in [0.10, 0.25, 0.45, 0.60, 0.80, 0.95, 1.15, 1.30, 1.60, 1.90]:
    red, green = counts(out, rel)
    print(f"{rel:>6.2f}  {red:>10}  {green:>10}")
