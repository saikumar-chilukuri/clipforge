# ⚡ ClipForge

Turn YouTube videos into short vertical clips with **free AI** — a local, self-hosted take on snazo.app.

**Paste a YouTube link → get unique 9:16 clips with burned captions, hooks and post copy.**

## How it works

1. **Download** — `yt-dlp` pulls the video (720p/1080p, configurable).
2. **Transcribe** — audio is chunked and sent to **Groq Whisper** (free tier) with word-level timestamps.
3. **Find highlights** — a free Groq LLM (Llama 3.3 70B / GPT-OSS) reads the transcript and picks the most viral, self-contained moments, writing a hook, caption and hashtags for each.
4. **Render** — `ffmpeg` cuts each moment, crops to **9:16 (1080×1920)** and burns in **karaoke-style captions** that highlight word-by-word as they're spoken.

Everything runs on your machine. The only external calls are free Groq API calls.

## Setup

```bash
# 1. System deps (macOS)
brew install ffmpeg ffmpeg-full   # ffmpeg-full provides the subtitles filter (libass)

# 2. Python env (created automatically by run.sh, or manually)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Run
./run.sh            # → http://localhost:7860
```

## One-time setup

Open **⚙ Settings** in the app and paste a free Groq API key from
[console.groq.com/keys](https://console.groq.com/keys) (takes 30 seconds, no credit card).

The key is stored locally in `data/settings.json` and is only ever used to call Groq.

## Options

| Setting | Values |
|---|---|
| Clips per video | 5 / 8 / 10 / 12 |
| Clip length | 30–45s / **30–60s (default)** / 45–60s / 30–90s |
| Layout | **Full frame 9:16 (default, nothing cut off)** / Close-up 9:16 (crops sides) / Square 1:1 / Original aspect |
| Transcription | whisper-large-v3-turbo (default) / whisper-large-v3 |
| Highlights | llama-3.3-70b-versatile (default), llama-3.1-8b-instant, gpt-oss-120b |
| Quality | 720p (faster) / 1080p (sharper) |

## Output

For each clip you get:

- `clip_XX.mp4` — clip in your chosen layout (1080×1920 vertical by default) with burned captions
- A hook (first caption line), a ready-to-post caption, hashtags, and a one-line reason
- **Download** button + **Copy post** button (caption + hashtags) in the UI

## Project layout

```
clipforge/
├── app/
│   ├── main.py         # FastAPI server + API
│   ├── pipeline.py     # Job orchestration (background threads)
│   ├── downloader.py   # yt-dlp download
│   ├── transcriber.py  # Groq Whisper, chunked for the 25MB limit
│   ├── analyzer.py     # Groq LLM highlight selection
│   ├── renderer.py     # ffmpeg crop + karaoke ASS captions
│   ├── ffutil.py       # ffmpeg binary resolution
│   ├── store.py        # Job persistence
│   └── config.py       # Settings
├── static/             # Frontend (vanilla HTML/CSS/JS)
├── data/               # Settings + job files (created at runtime)
├── requirements.txt
└── run.sh
```

## Notes

- Every output clip is **30–60 seconds by default** (the "Clip length" selector controls this). The only "10 minutes" anywhere is an internal detail: long audio is *transcribed* in 10-minute pieces behind the scenes, then stitched back into one timeline — no clip is ever that long.
- Failed individual clips are skipped automatically instead of failing the job.
- Delete old jobs from the job history or by removing `data/jobs/<id>/`.
