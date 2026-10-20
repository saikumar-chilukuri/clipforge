import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
JOBS_DIR = DATA_DIR / "jobs"
SETTINGS_FILE = DATA_DIR / "settings.json"

DATA_DIR.mkdir(exist_ok=True)
JOBS_DIR.mkdir(exist_ok=True)

DEFAULT_SETTINGS = {
    "groq_api_key": "",
    "llm_model": "openai/gpt-oss-120b",
    "whisper_model": "whisper-large-v3-turbo",
    "max_height": 720,
}


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            settings.update(json.loads(SETTINGS_FILE.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
    if not settings.get("groq_api_key"):
        settings["groq_api_key"] = os.environ.get("GROQ_API_KEY", "")
    return settings


def save_settings(updates: dict) -> dict:
    settings = load_settings()
    for key, value in updates.items():
        if value is not None and key in DEFAULT_SETTINGS:
            settings[key] = value
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2))
    return settings
