"""Render one clip in each mode and verify output dimensions."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from app import renderer, ffutil

work = Path(__file__).parent / "data" / "modes"
work.mkdir(parents=True, exist_ok=True)
ffmpeg = ffutil.best_ffmpeg()

src = work / "source.mp4"
if not src.exists():
    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
         "-t", "10", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)],
        check=True, capture_output=True,
    )

words = []
t = 1.0
for w in ["layout", "test", "every", "word", "stays", "inside", "the", "frame"]:
    words.append({"word": w, "start": t, "end": t + 0.32})
    t += 0.35

expected = {"vertical_blur": "1080x1920", "vertical": "1080x1920", "square": "1080x1080", "original": "1080x608"}
ok = True
for mode in renderer.MODES:
    out = work / f"clip_{mode}.mp4"
    try:
        renderer.render_clip(src, out, work, words, 1.0, 5.0, f"{mode}.ass", mode=mode)
    except renderer.RenderError as e:
        print(f"{mode}: RENDER FAILED -> {e}")
        ok = False
        continue
    probe = subprocess.run(
        [ffutil.find_ffprobe(), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True,
    )
    size = probe.stdout.strip().replace(",", "x")
    size_ok = size == expected[mode]
    ok = ok and size_ok
    print(f"{mode:>14}: {size} (expected {expected[mode]}) {'✓' if size_ok else '✗'}  {round(out.stat().st_size/1e6,2)} MB")
print("ALL OK" if ok else "SOME FAILED")
