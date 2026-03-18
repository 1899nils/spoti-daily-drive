import json
import os
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
CONFIG_FILE = DATA_DIR / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "playlist_name": "Daily Drive 🎵",
    "total_tracks": 30,
    "top_tracks_ratio": 0.4,
    "recommendations_ratio": 0.4,
    "podcast_episodes": 4,
    "schedule_times": ["06:00"],
    "selected_podcasts": [],
    "playlist_id": None,
    "last_build": None,
    "statsfm_user_id": None,
    "statsfm_display_name": None,
    "excluded_artists": [],
}


def load_config() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    with open(CONFIG_FILE) as f:
        data = json.load(f)
    # Merge with defaults to handle missing keys after updates
    merged = {**DEFAULT_CONFIG, **data}
    # Migrate old single schedule_time to schedule_times array
    if "schedule_time" in merged and "schedule_times" not in data:
        merged["schedule_times"] = [merged["schedule_time"]]
    merged.pop("schedule_time", None)
    return merged


def save_config(config: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
